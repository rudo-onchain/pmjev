# pmjev

`pmjev` measures whether Jev predicts Polymarket five-minute crypto Up/Down
markets better than the market midpoint, a driftless GBM baseline, and a
bounded trend-adjusted GBM benchmark. The trend benchmark combines normalized
10s/30s/60s/5m momentum with 60-second order flow. `TREND_GBM_TRADE=true`
paper-trades that probability with the same edge, fees, and checkpoint gates
as the other models. `GBM_TRADE` stays independent. Paper remains the default;
shadow execution records intended orders without sending them, and live execution
is implemented behind an explicit multi-setting safety gate.

## Setup

Python 3.11 or newer is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

For Phase 1, put your TypeSafe API key in `.env` as `TYPESAFE_API_KEY`. Do not
commit `.env`. Phase 0 needs no secrets.

Telegram alerts are optional. Set both `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` in `.env`; leaving both blank disables them. Trade alerts
are sent immediately as compact two-line messages. Hourly PnL is sent at minute
02, and daily PnL at 07:05 Asia/Bangkok time. Telegram delivery is queued so a
slow or failed request cannot delay a trading checkpoint.
For a forum group topic, also set the optional `TELEGRAM_MESSAGE_THREAD_ID`.

Validate configuration and all public upstreams without writing to the database:

```bash
python -m pmjev doctor
```

The probes in `scripts/` remain available for inspecting raw upstream responses:

```bash
python scripts/probe_gamma_slugs.py
python scripts/probe_chainlink_ws.py --messages 10
python scripts/probe_price_to_beat.py --symbol btc/usd
python scripts/probe_hyperliquid.py
python scripts/probe_fee_schedule.py btc-updown-5m-REPLACE_WITH_WINDOW_START
```

`REFERENCE_FEED=auto` uses one authenticated PolyBolt connection for all enabled
assets when all three `POLY_API_*` values are present, otherwise it retains the
legacy RTDS adapter. Binance/Hyperliquid remain predictive feature feeds; PolyBolt
60-second TWAP remains the resolution-aligned anchor. The exact boundary-tick
convention is still isolated in `select_price_to_beat` and should be audited with
the boundary probe.

## Run

Phase 0, with market and GBM data but no Jev calls:

```bash
python -m pmjev run --no-jev
```

Phase 1 paper collection:

```bash
python -m pmjev run
```

Phase 1 fails immediately with a clear error if `TYPESAFE_API_KEY` is blank.

DeepSeek V4.1 Flash can run beside Jev as an independent blind predictor through
OpenRouter. It is deliberately restricted to paper mode in configuration, execution,
and the PostgreSQL schema. Add an OpenRouter key, then enable both collection and paper
entries:

```dotenv
MODE=paper
DEEPSEEK_ENABLED=true
DEEPSEEK_TRADE=true
OPENROUTER_API_KEY=sk-or-v1-REPLACE_ME
```

DeepSeek receives the same blind numeric state as Jev, never the Polymarket bid/ask/mid.
Its probability, latency, error, and routed provider are stored separately. Set
`DEEPSEEK_TRADE=false` to collect predictions without opening simulated positions.

Shadow mode uses the same entry logic but does not send an order:

```bash
MODE=shadow python -m pmjev run
```

## Live safety gate

Live sends a BUY FOK through the official `polymarket-client`, caps execution at
the observed ask, caps all-in spend at `STAKE_USD`, and never retries an ambiguous
order. It holds matched positions to resolution and retries redemption on later
resolver passes. Paper-style early exits are disabled in live mode.

Live startup requires all of these values: `MODE=live`,
`LIVE_TRADING_ENABLED=true`, `MAX_NOTIONAL_USD`, `POLY_PRIVATE_KEY`,
`POLY_WALLET`, and all three `POLY_API_*` credentials. The committed example and
local configuration keep `LIVE_TRADING_ENABLED=false`; implementation does not arm
or place a real order by itself.

Before arming it, verify account/wallet funding and approvals, run shadow for seven
days, confirm local legal eligibility, and create a `STOP` file whenever new orders
must stop immediately. The live guard also blocks stale reference data, Jev errors
above the configured 30-minute threshold, excessive open notional, daily loss,
consecutive losses, and maximum drawdown. A transport-ambiguous order permanently
latches the process until the CLOB account is reconciled and the process restarted.

Resolve and report from another process (or after stopping the collector):

```bash
python -m pmjev resolve
python -m pmjev report
```

The collector waits for the next complete window after startup. At every
checkpoint it processes all enabled assets concurrently; an adapter failure is
logged for that asset without cancelling the others.
The per-checkpoint deadline is derived as `HTTP_TIMEOUT_S + longest enabled
predictor timeout + 1 second` (8.5 seconds with the current Jev/DeepSeek
settings). Set `CHECKPOINT_BUDGET_S` only when an explicit override is needed.

`CHECKPOINTS` controls prediction collection. Optionally set
`ENTRY_CHECKPOINTS` and `EXIT_CHECKPOINTS` to subsets of it to keep collecting
predictions without allowing a trade action at every checkpoint. If either is
unset, that action remains enabled at every collected checkpoint for backwards
compatibility. `JEV_TRADE=false` and `TREND_GBM_TRADE=false` still record their
probabilities and can evaluate existing exits, but do not open new entries.
Entry safety also skips every model when the resolution-aligned Chainlink spot
and the feature-feed spot are on opposite sides of `price_to_beat`. When a
Polymarket midpoint is available, an individual model is skipped if
`abs(model_p_up - market_p_up) > MAX_MODEL_MARKET_GAP` (default `0.25`).
The default five-minute schedule records a prediction at t+60, permits entries
at t+150/t+180/t+240, and evaluates exits every 30 seconds from t+180 through
t+270 plus one final check at t+280.

## Add or select an asset

Add one block to `assets.yaml`; application code does not change. Select a
feature adapter with `feature_source.type`, provide the Polymarket slug prefix
and Chainlink symbol, then run the slug/WS probes. Existing adapters are
`binance` (`symbol`) and `hyperliquid` (`coin`). Defaults are merged into every
asset and the fully merged file is validated before any network connection is
opened.

Temporarily select configured assets with an environment override:

```bash
ASSETS=btc,hype python -m pmjev run --no-jev
```

Unknown asset names, extra YAML fields, invalid checkpoints, and malformed
adapter blocks make startup fail immediately.

## Read the report

Each asset/checkpoint section contains:

- sample count, Brier score, and log loss for market midpoint, GBM, trend GBM,
  blind Jev, market-visible Jev, and DeepSeek;
- realized paper PnL at resolution or at a model-driven early exit against the
  bid, using the Gamma fee schedule, plus a 1.5× fee stress case;
- blind-Jev calibration by ten probability buckets;
- Jev request latency p50/p95; and
- a 2,000-resample paired 95% bootstrap interval for
  `Brier(Jev) - Brier(market)`.

Lower Brier/log loss is better. A bootstrap interval entirely below zero
supports Jev outperforming the market at that checkpoint. Empty Jev metrics in
a `--no-jev` database are expected. Each window stores the current Gamma fee
schedule; `FEE_PEAK` is only a backwards-compatible fallback if it is absent.

## Railway worker

The worker supports SQLite for local development and Supabase PostgreSQL for
production. Copy the direct Supabase connection string from **Connect** into
`DB_URL` when the runtime supports IPv6. Otherwise use the session-pooler string
on port 5432. The process keeps a small application-side pool, so start with one
worker replica and `DB_POOL_MIN_SIZE=1`, `DB_POOL_MAX_SIZE=4`.

### Create and migrate the Supabase database

The operational tables live in the `public` schema so they can later support the
dashboard through Supabase's Data API. RLS is enabled and the migration creates
no browser-facing policy, so `anon` and `authenticated` cannot read or write the
tables yet. The worker bypasses those API roles by connecting directly with the
database role in `DB_URL`.

```bash
npx supabase login
npx supabase link --project-ref YOUR_PROJECT_REF
npx supabase db push
```

To copy an existing SQLite database before switching the worker, set a temporary
admin connection string and run the importer. Re-running it with the same source
snapshot updates the same primary keys instead of duplicating rows:

```bash
export SUPABASE_DB_URL='postgresql://...'
python scripts/migrate_sqlite_to_postgres.py --source pmjev.sqlite
```

Keep the worker stopped while running the final import. Then set `DB_URL` to the
same Supabase connection string, start one worker, and verify:

```bash
python -m pmjev db-check
python -m pmjev resolve
python -m pmjev report
```

`python -m pmjev doctor` checks market-data APIs with an in-memory SQLite store;
it does not verify Supabase. Use `db-check` for that. The dashboard migration
exposes only the sanitized `dashboard_snapshots` read model. Raw trading tables
stay inaccessible to browser roles. Never place the database password in Vite
client environment variables.

### Realtime dashboard

Apply all migrations and configure `DASHBOARD_STARTING_BALANCE_USD` on the worker.
The worker publishes a mode-specific snapshot after every market checkpoint and
resolution.

Configure the static dashboard separately in `dashboard/.env`:

```dotenv
VITE_DASHBOARD_MODE=paper
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
```

The display mode is build-time configuration and does not change or arm the
worker execution mode. See `dashboard/README.md` for local commands and security
notes.

For Railway, set the start command to `python -m pmjev run --no-jev` for Phase 0,
copy non-secret values from `.env.example`, add secrets in Railway variables,
and use a region near Supabase and the upstream APIs. Add `TYPESAFE_API_KEY` only
for Phase 1. Deployment is not performed automatically by this repository.

## Development checks

```bash
pytest
ruff check .
mypy pmjev
```
