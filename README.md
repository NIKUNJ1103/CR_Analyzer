# CR Player Pool — 2,500-player portfolio tracker (standalone)

Fully separate from any other CR project — own repo, own Supabase
project. Auto-builds a pool of ~2,500 unique Path of Legend players
by walking seasons backward, fetches all their battles (ladder,
duels, friendlies) 3x/day forever, and generates the same portfolio
report as the "Performance Analysis Report" screenshot for any
player in the pool.

## How the pieces fit together

| File | Runs | Purpose |
|---|---|---|
| `pool_builder.py` | 1x/day | Walks PoL seasons backward until 2,500 unique players are found, adds them to `player_watchlist` |
| `collector.py` | 3x/day | Fetches new battles for everyone currently in `player_watchlist` — parallelized (15 workers) since sequential would take too long at this scale |
| `report.py` | on demand | Builds the full stats report for one player tag from everything accumulated so far |

No alt-account guessing — every player in the pool comes directly
from a real PoL leaderboard, nothing inferred.

## Step 1: New Supabase project
1. supabase.com → **New project** (free tier to start — see storage
   note at the bottom before committing to a month)
2. Project Settings → Database → Connection string → **Session pooler**
   tab → copy it, you'll need it in Step 3

## Step 2: New GitHub repo
1. github.com → new repository, **private** recommended, no README/gitignore
   (empty repo — you're uploading everything fresh)

## Step 3: Clash Royale API key
GitHub Actions has no fixed IP, and Supercell only allows specific
IPs — not wildcards. Same fix as before: route through RoyaleAPI's
proxy.
- **If you already have a proxy-whitelisted key from another project**
  (IP `45.79.218.79` added to it) — reuse that same token, no need
  to create a new one. It's just an API credential, unrelated to
  which database it writes to.
- **If not:** developer.clashroyale.com → Create New Key → in
  Allowed IP Addresses, add `45.79.218.79` (RoyaleAPI's proxy IP) →
  Create Key → copy the token

## Step 4: Upload the files
Add every file below to the new repo (drag-and-drop upload works, or
create each one individually via **Add file → Create new file** —
just make sure `.github/workflows/*.yml` land at the repo root, not
nested in a subfolder).

## Step 5: Add secrets
Repo → **Settings → Secrets and variables → Actions**:
- `CR_API_KEY` — the proxy-whitelisted token from Step 3
- `DATABASE_URL` — the Supabase Session pooler string from Step 1,
  with your real password substituted in, URL-encoded (every `!`
  becomes `%21`, `@` becomes `%40`, etc. if present)

## Step 6: First run
1. Actions tab → **Build player pool** → **Run workflow** — watch it
   walk seasons and climb toward 2,500 unique tags (takes a few
   minutes; each season lookup has a small delay to stay polite to
   the API)
2. Once that finishes, Actions tab → **Collect player battles** →
   **Run workflow** — this fetches the first batch for all ~2,500
   players (this one will take longer on the very first run, since
   everyone's brand new — later runs are faster since most players
   won't need a fresh fetch every single time)

## From here — fully automated
- Pool refreshes itself 1x/day
- Battles collect 3x/day, automatically, forever — no manual runs needed
- Duplicate battles are structurally impossible: `player_battles` has
  `UNIQUE(player_tag, battle_time, own_deck_key, opp_deck_key)` with
  `ON CONFLICT DO NOTHING`, so re-running never double-stores anything

## Getting a report for any of the 2,500 players
Actions tab → **Player report** → **Run workflow** → type a tag →
the full breakdown (battles analyzed, win rate, unique decks, card
usage by role, win-condition archetypes, deck-by-deck stats) prints
into that run's log. Same format as the screenshot, including
community-style archetype names (Bait, Piggies, Drill, etc. instead
of raw card names).

## Storage — read this before letting it run unattended for a month
At 2,500 players × all battle types × 3x/day polling, rough estimate:
tens of thousands of new rows/day, roughly **~35-40MB/day**, which
means **Supabase's free 500MB tier likely fills up within 2-3 weeks**,
not a full month. This is an estimate, not measured — check real
usage after week 1 (Supabase dashboard → Database → usage) and
decide then:
- Upgrade to Supabase Pro (~$25/mo, 8GB+) — simplest, no compromises
- Or edit `collector.py` to skip storing `friendly` battles (usually
  low-signal test games) — cuts volume meaningfully
- Or add a periodic prune (e.g. delete rows older than 90 days per
  player) — not built yet, ask if you want this added

## Files in this repo
- `schema.sql` — `player_watchlist` + `player_battles` tables
- `db.py` — Postgres connection helper
- `pool_builder.py` — season-walking pool builder
- `collector.py` — parallelized battle fetcher
- `report.py` — report generator
- `requirements.txt` — Python deps
- `.github/workflows/pool_builder.yml` — 1x/day
- `.github/workflows/collector.yml` — 3x/day
- `.github/workflows/report.yml` — on-demand, manual trigger
