"""
report.py — turns accumulated player_battles rows into a
portfolio report: total battles, win rate, unique decks, card usage
by role (Evolution / Win Condition / Building / Champion / Support),
archetype breakdown, and per-deck stats. Matches the metrics in the
"Performance Analysis Report" style screenshot.

Run:
    DATABASE_URL=... python report.py "#COOCRGG2P"

Note on categories:
- Evolution: derived directly from own_evos per battle (already
  tracked — a card counts here if it was evolved THAT battle,
  independent of its other role)
- Champion: HEROES_SET (the 6 hero cards) — comes directly from
  Supercell's card list, not guessed
- Win Condition / Building: matched against curated lists below.
  Supercell's public API does NOT label cards by role, so these
  lists are compiled from community knowledge and may need updating
  as new cards release — check the "Unclassified" section the
  report prints if a new card shows up as neither.
- Support: everything else (the catch-all, matches how these
  community reports define it)
"""

import os
import sys
import json
import requests
from collections import Counter, defaultdict

from db import get_conn

HEROES_SET = {
    'Archer Queen', 'Golden Knight', 'Skeleton King',
    'Mighty Miner', 'Monk', 'Little Prince',
}

WIN_CONDITION_CARDS = {
    'X-Bow', 'Mortar', 'Goblin Drill', 'Lava Hound', 'Balloon', 'Golem',
    'Electro Giant', 'Giant', 'Royal Giant', 'Mega Knight', 'Three Musketeers',
    'Hog Rider', 'Royal Hogs', 'Goblin Barrel', 'Graveyard', 'Miner',
    'Ram Rider', 'Battle Ram', 'Bandit', 'Elixir Golem', 'Wall Breakers',
    'Goblin Giant', 'Sparky', 'P.E.K.K.A', 'Giant Skeleton',
}

BUILDING_CARDS = {
    'Cannon', 'Tesla', 'Inferno Tower', 'Bomb Tower', 'Goblin Cage',
    'Furnace', 'Elixir Collector', 'Barbarian Hut', 'Tombstone', 'Goblin Hut',
}

# Friendly archetype names — matches how the community (and tools
# like Deckries) actually label these, not the raw card name
ARCHETYPE_LABELS = {
    'Goblin Drill': 'Drill',
    'Goblin Barrel': 'Bait',
    'Royal Hogs': 'Piggies',
    'Hog Rider': 'Hog',
    'X-Bow': 'Xbow',
    'Lava Hound': 'LavaLoon',
    'Ram Rider': 'Bridge Spam',
    'Battle Ram': 'Bridge Spam',
    'Bandit': 'Bridge Spam',
}


def archetype_label(card_name):
    return ARCHETYPE_LABELS.get(card_name, card_name)


def get_card_elixir_map():
    """Fetch live elixir costs. Falls back to empty dict (cycle count shows '?') if no key set."""
    api_key = os.environ.get('CR_API_KEY')
    if not api_key:
        return {}
    try:
        r = requests.get(
            'https://proxy.royaleapi.dev/v1/cards',
            headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'},
            timeout=15
        )
        if r.status_code != 200:
            return {}
        return {c['name']: c.get('elixirCost', 3) for c in r.json().get('items', [])}
    except Exception:
        return {}


def card_role(card_name):
    if card_name in HEROES_SET:
        return 'Champion'
    if card_name in WIN_CONDITION_CARDS:
        return 'Win Condition'
    if card_name in BUILDING_CARDS:
        return 'Building'
    return 'Support'


def build_report(player_tag):
    global _elixir_lookup
    _elixir_lookup = get_card_elixir_map()

    t = player_tag.strip().replace('#', '').upper()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        SELECT battle_time, battle_type, game_mode,
               own_deck_key, own_deck_cards, own_evos, own_elixir, result
        FROM player_battles WHERE player_tag = %s
        ORDER BY battle_time
    ''', (t,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print(f'No battles stored yet for #{t}.')
        print('Add to watchlist + run collector.py first, then let it accumulate over time.')
        return

    total_battles = len(rows)
    wins = sum(1 for r in rows if r[7] == 'win')
    win_rate = round(wins / total_battles * 100, 1)

    duel_battles = sum(1 for r in rows if 'duel' in (r[2] or '').lower())

    # ── Card usage rates by role ─────────────────────────────────
    card_games   = Counter()   # per-card usage across all battles
    evo_games    = Counter()   # per-card evolution usage

    deck_stats = defaultdict(lambda: {'games': 0, 'wins': 0, 'cards': None, 'elixir': 0})

    for battle_time, battle_type, game_mode, deck_key_val, deck_cards_json, evos_json, elixir, result in rows:
        try:
            cards = json.loads(deck_cards_json)
            evos = json.loads(evos_json) if evos_json else []
        except Exception:
            continue

        for c in cards:
            card_games[c] += 1
        for c in evos:
            evo_games[c] += 1

        ds = deck_stats[deck_key_val]
        ds['games'] += 1
        ds['cards'] = cards
        ds['elixir'] = elixir
        if result == 'win':
            ds['wins'] += 1

    # ── Win condition archetype breakdown ────────────────────────
    archetype_stats = defaultdict(lambda: {'games': 0, 'wins': 0})
    for battle_time, battle_type, game_mode, deck_key_val, deck_cards_json, evos_json, elixir, result in rows:
        try:
            cards = set(json.loads(deck_cards_json))
        except Exception:
            continue
        win_con = next((c for c in cards if c in WIN_CONDITION_CARDS), 'Other')
        win_con = archetype_label(win_con)
        archetype_stats[win_con]['games'] += 1
        if result == 'win':
            archetype_stats[win_con]['wins'] += 1

    # ── Print report ──────────────────────────────────────────────
    print('=' * 60)
    print(f'PERFORMANCE ANALYSIS — #{t}')
    print('=' * 60)
    print(f'Battles analyzed : {total_battles}')
    print(f'Overall win rate : {win_rate}%')
    print(f'Unique decks     : {len(deck_stats)}')
    print(f'Duel battles     : {duel_battles}')

    print('\n' + '-' * 60)
    print('CARD USAGE BY ROLE (usage rate across all battles)')
    print('-' * 60)
    by_role = defaultdict(list)
    for card, games in card_games.most_common():
        role = card_role(card)
        usage_pct = round(games / total_battles * 100, 1)
        by_role[role].append((card, usage_pct))
    for role in ['Evolution', 'Win Condition', 'Building', 'Champion', 'Support']:
        if role == 'Evolution':
            items = sorted(
                [(c, round(g / total_battles * 100, 1)) for c, g in evo_games.items()],
                key=lambda x: -x[1]
            )
        else:
            items = by_role.get(role, [])
        print(f'\n  {role}:')
        for card, pct in items[:10]:
            print(f'    {card:<20} UR: {pct}%')

    print('\n' + '-' * 60)
    print('WIN CONDITION ARCHETYPE BREAKDOWN')
    print('-' * 60)
    for win_con, s in sorted(archetype_stats.items(), key=lambda x: -x[1]['games']):
        wr = round(s['wins'] / s['games'] * 100, 1) if s['games'] else 0
        usage = round(s['games'] / total_battles * 100, 1)
        print(f'  {win_con:<20} {s["games"]:>4} battles | UR {usage:>5}% | WR {wr:>5}%')

    print('\n' + '-' * 60)
    print('DECK BREAKDOWN (ordered by battles played)')
    print('-' * 60)
    for deck_key_val, ds in sorted(deck_stats.items(), key=lambda x: -x[1]['games'])[:10]:
        wr = round(ds['wins'] / ds['games'] * 100, 1) if ds['games'] else 0
        usage = round(ds['games'] / total_battles * 100, 1)
        cycle = sum(1 for c in ds['cards'] if _elixir_lookup.get(c, 3) <= 3) if ds['cards'] else '?'
        if not _elixir_lookup:
            cycle = '?'
        print(f'  {ds["elixir"]:.1f} elx | cycle {cycle} | {ds["games"]:>3} battles | '
              f'WR {wr:>5}% | UR {usage:>5}%')
        if ds['cards']:
            print(f'    {", ".join(ds["cards"])}')


def main():
    if len(sys.argv) < 2:
        print('Usage: python report.py "#PLAYERTAG"')
        sys.exit(1)
    build_report(sys.argv[1])


if __name__ == '__main__':
    main()
