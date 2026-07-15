"""
collector.py — fetches battle history for specific watchlisted
players (not the whole leaderboard), keeping ALL battle types (ladder,
duels, challenges, everything) since a player portfolio should reflect
their whole footprint, not just ranked play.

This is what turns "25 battles right now" into "371 battles over time"
in a report like the one you shared — same constraint as the
leaderboard collector (25 max per call), same fix (poll regularly,
keep everything, never overwrite).

Run manually:
    CR_API_KEY=... DATABASE_URL=... python collector.py

Run automatically:
    add as a step in .github/workflows/collector.yml (see note below)

Manage your watchlist:
    python collector.py --add "#COOCRGG2P" "Lens"
    python collector.py --remove "#COOCRGG2P"
    python collector.py --list
"""

import os
import sys
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from tqdm import tqdm

from db import get_conn, init_schema, deck_key

CR_API_KEY = os.environ.get('CR_API_KEY')
if not CR_API_KEY:
    sys.exit('❌ CR_API_KEY environment variable is not set')

CR_BASE = 'https://proxy.royaleapi.dev/v1'   # same proxy fix as collector.py
CR_HEADERS = {
    'Authorization': f'Bearer {CR_API_KEY}',
    'Accept':        'application/json',
}

HEROES_SET = {
    'Archer Queen', 'Golden Knight', 'Skeleton King',
    'Mighty Miner', 'Monk', 'Little Prince',
}


def get_card_elixir_map():
    r = requests.get(f'{CR_BASE}/cards', headers=CR_HEADERS, timeout=15)
    if r.status_code != 200:
        return {}
    return {c['name']: c.get('elixirCost', 3) for c in r.json().get('items', [])}


def add_player(tag, label=None):
    t = tag.strip().replace('#', '').upper()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO player_watchlist (tag, label, added_at) VALUES (%s, %s, %s)
        ON CONFLICT (tag) DO UPDATE SET label = EXCLUDED.label
    ''', (t, label, datetime.now().isoformat()))
    conn.commit()
    cur.close()
    conn.close()
    print(f'✅ Added #{t} ({label or "no label"}) to watchlist')


def bulk_add_from_csv(path):
    """CSV format: season,placement,name,tag (header required)"""
    import csv
    added = 0
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            tag = row.get('tag', '').strip()
            if not tag:
                print(f'  ⚠️  skipping row with no tag: {row}')
                continue
            name = row.get('name', '').strip()
            season = row.get('season', '').strip()
            placement = row.get('placement', '').strip()
            label = f'{name} ({season} #{placement})' if season else name
            add_player(tag, label)
            added += 1
    print(f'\n✅ Bulk-added {added} players from {path}')


def remove_player(tag):
    t = tag.strip().replace('#', '').upper()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM player_watchlist WHERE tag = %s', (t,))
    conn.commit()
    cur.close()
    conn.close()
    print(f'✅ Removed #{t} from watchlist')


def list_players():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT tag, label, added_at FROM player_watchlist ORDER BY added_at')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        print('Watchlist is empty. Add someone with --add "#TAG" "Name"')
    for tag, label, added in rows:
        print(f'#{tag:<12} {label or "":<20} added {added}')


def fetch_player_battles(tag, card_elixir):
    t = tag.strip().replace('#', '').upper()
    r = requests.get(f'{CR_BASE}/players/%23{t}/battlelog', headers=CR_HEADERS, timeout=15)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(f'{CR_BASE}/players/%23{t}/battlelog', headers=CR_HEADERS, timeout=15)
    if r.status_code != 200:
        print(f'  ⚠️  #{t}: HTTP {r.status_code}')
        return 0

    rows = []
    for b in r.json():
        try:
            team = b.get('team', [{}])
            opp  = b.get('opponent', [{}])
            if not team or not opp:
                continue
            td, od = team[0], opp[0]

            own_deck = [c.get('name', '') for c in td.get('cards', []) if c.get('name')]
            opp_deck = [c.get('name', '') for c in od.get('cards', []) if c.get('name')]
            if len(own_deck) < 8 or len(opp_deck) < 8:
                continue

            tc, oc = td.get('crowns', 0), od.get('crowns', 0)
            result = 'win' if tc > oc else ('loss' if tc < oc else 'draw')

            own_evos   = [c for c in own_deck if 'Evo' in c]
            own_heroes = [c for c in own_deck if c in HEROES_SET]
            own_elixir = round(sum(card_elixir.get(c, 3) for c in own_deck) / 8, 2)

            rows.append((
                t, b.get('battleTime', ''), b.get('type', 'unknown'),
                (b.get('gameMode') or {}).get('name', ''),
                deck_key(own_deck), json.dumps(own_deck), json.dumps(own_evos), json.dumps(own_heroes),
                own_elixir, tc,
                deck_key(opp_deck), json.dumps(opp_deck), oc,
                result,
            ))
        except Exception:
            continue

    if not rows:
        return 0

    conn = get_conn()
    cur = conn.cursor()
    cur.executemany('''
        INSERT INTO player_battles
        (player_tag, battle_time, battle_type, game_mode,
         own_deck_key, own_deck_cards, own_evos, own_heroes, own_elixir, own_crowns,
         opp_deck_key, opp_deck_cards, opp_crowns, result)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (player_tag, battle_time, own_deck_key, opp_deck_key) DO NOTHING
    ''', rows)
    conn.commit()
    cur.close()
    conn.close()
    return len(rows)


def main():
    args = sys.argv[1:]

    if args and args[0] == '--add':
        add_player(args[1], args[2] if len(args) > 2 else None)
        return
    if args and args[0] == '--bulk-add':
        bulk_add_from_csv(args[1])
        return
    if args and args[0] == '--remove':
        remove_player(args[1])
        return
    if args and args[0] == '--list':
        list_players()
        return

    init_schema()

    # Auto-import: if a crl_watchlist.csv file is sitting in the repo,
    # load it on every run. Safe to re-run repeatedly — bulk_add_from_csv
    # uses ON CONFLICT DO UPDATE, so already-added players just get their
    # label refreshed, never duplicated. This is what lets you manage the
    # whole watchlist by editing a file on GitHub — no terminal needed.
    default_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crl_watchlist.csv')
    if os.path.exists(default_csv):
        print(f'Found {default_csv} — importing before fetch...')
        bulk_add_from_csv(default_csv)
        print()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT tag FROM player_watchlist')
    tags = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not tags:
        print('Watchlist is empty — nothing to fetch. Add players with:')
        print('  python collector.py --add "#TAG" "Name"')
        return

    print(f'Fetching {len(tags)} watchlisted player(s)...')
    card_elixir = get_card_elixir_map()

    # Parallel fetch — sequential would take far too long at this scale.
    # MAX_WORKERS is tunable via env var if you see 429 (rate limited)
    # entries climbing in the output — drop it if so.
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 15))
    total, errors = 0, 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_player_battles, tag, card_elixir): tag
            for tag in tags
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc='Fetching'):
            tag = futures[future]
            try:
                n = future.result()
                total += n
                if n == 0:
                    errors += 1
            except Exception as e:
                errors += 1
                print(f'  ⚠️  #{tag} failed: {e}')

    print(f'\n✅ Stored {total} new battles across {len(tags)} watchlisted player(s)')
    print(f'   Players with 0 new battles / errors: {errors}')


if __name__ == '__main__':
    main()
