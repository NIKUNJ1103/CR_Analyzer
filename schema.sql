-- ═══════════════════════════════════════════════════════════════
-- Standalone schema for individual player portfolios.
-- Run once (collector.py also runs this automatically every start).
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS player_watchlist (
    tag        TEXT PRIMARY KEY,
    label      TEXT,           -- optional friendly name, e.g. 'Lens'
    added_at   TEXT
);

CREATE TABLE IF NOT EXISTS player_battles (
    id             BIGSERIAL PRIMARY KEY,
    player_tag     TEXT,
    battle_time    TEXT,
    battle_type    TEXT,       -- raw 'type' field from the API
    game_mode      TEXT,       -- raw gameMode.name, used to detect duels etc.
    own_deck_key   TEXT,
    own_deck_cards TEXT,
    own_evos       TEXT,
    own_heroes     TEXT,
    own_elixir     REAL,
    own_crowns     INTEGER,
    opp_deck_key   TEXT,
    opp_deck_cards TEXT,
    opp_crowns     INTEGER,
    result         TEXT,       -- win / loss / draw
    UNIQUE(player_tag, battle_time, own_deck_key, opp_deck_key)
);

CREATE INDEX IF NOT EXISTS idx_player_battles_tag ON player_battles (player_tag);
