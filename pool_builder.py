"""
pool_builder.py — builds/refreshes a pool of ~2,000 unique
Path of Legend players by walking seasons backward from the current
one, until the target count is hit (or a safety cap of seasons is
reached). Adds them to player_watchlist so collector.py picks
them up on its next run.

Why walk backward instead of just grabbing top-2000-right-now: the
PoL leaderboard endpoint only ever returns top 200 for a GIVEN
season — there's no "top 2000" endpoint. Seasons overlap heavily
(many of the same players stay near the top month to month), so
reaching 2,000 truly unique tags requires looking across several
seasons, not just one.

This does NOT touch alt accounts — there's no reliable API for that
at this scale (see conversation notes). This only ever adds players
found directly on a real PoL leaderboard.

Run manually:
    CR_API_KEY=... DATABASE_URL=... python pool_builder.py

Run automatically:
    separate workflow, 1x/day — the pool barely changes hour to hour,
    no need to re-walk 15+ seasons every few hours
"""

import os
import sys
import time
from datetime import datetime

import requests

from db import get_conn, init_schema

CR_API_KEY = os.environ.get('CR_API_KEY')
if not CR_API_KEY:
    sys.exit('❌ CR_API_KEY environment variable is not set')

CR_BASE = 'https://proxy.royaleapi.dev/v1'
CR_HEADERS = {
    'Authorization': f'Bearer {CR_API_KEY}',
    'Accept':        'application/json',
}

TARGET_UNIQUE_PLAYERS = int(os.environ.get('TARGET_UNIQUE_PLAYERS', 2500))
MAX_SEASONS_TO_WALK    = int(os.environ.get('MAX_SEASONS_TO_WALK', 24))  # ~2 years safety cap


def get_all_seasons(limit=MAX_SEASONS_TO_WALK):
    r = requests.get(f'{CR_BASE}/locations/global/seasons', headers=CR_HEADERS, timeout=15)
    if r.status_code != 200:
        print(f'❌ Could not fetch season list ({r.status_code})')
        return []
    items = r.json().get('items', [])
    ids = sorted([it['id'] for it in items if it.get('id') is not None], reverse=True)
    return ids[:limit]


def get_top_players_from_pol(season, limit=200):
    r = requests.get(
        f'{CR_BASE}/locations/global/pathoflegend/{season}/rankings/players?limit={limit}',
        headers=CR_HEADERS, timeout=15
    )
    if r.status_code != 200:
        return []
    return [p['tag'].replace('#', '') for p in r.json().get('items', [])]


def upsert_pool_players(tags, source_label):
    if not tags:
        return
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    rows = [(t, source_label, now) for t in tags]
    cur.executemany('''
        INSERT INTO player_watchlist (tag, label, added_at) VALUES (%s, %s, %s)
        ON CONFLICT (tag) DO NOTHING
    ''', rows)
    # ON CONFLICT DO NOTHING here (not DO UPDATE) — this is deliberate:
    # if a player is ALREADY on the watchlist with a manual label (e.g.
    # a CRL placement from your CSV), the pool builder must not
    # overwrite that more specific label with a generic one.
    conn.commit()
    cur.close()
    conn.close()


def main():
    init_schema()

    seasons = get_all_seasons()
    if not seasons:
        print('❌ No seasons found, aborting')
        return

    print(f'Walking up to {len(seasons)} seasons to reach {TARGET_UNIQUE_PLAYERS} unique players...')

    seen = set()
    for i, season in enumerate(seasons):
        tags = get_top_players_from_pol(season)
        new_tags = [t for t in tags if t not in seen]
        seen.update(tags)

        if new_tags:
            upsert_pool_players(new_tags, f'PoL Leaderboard {season}')

        print(f'  Season {season}: {len(tags):>3} players ({len(new_tags):>3} new) '
              f'— running total: {len(seen):,}')

        if len(seen) >= TARGET_UNIQUE_PLAYERS:
            print(f'\n✅ Reached target after {i+1} seasons')
            break

        time.sleep(0.3)
    else:
        print(f'\n⚠️  Hit the {MAX_SEASONS_TO_WALK}-season safety cap before reaching '
              f'{TARGET_UNIQUE_PLAYERS} — got {len(seen):,} unique players instead')

    print(f'\nTotal unique players added to pool this run: {len(seen):,}')
    print('collector.py will pick up anyone new on its next run')


if __name__ == '__main__':
    main()
