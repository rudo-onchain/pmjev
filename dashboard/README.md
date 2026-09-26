# PMJEV dashboard

The dashboard reads a sanitized snapshot from Supabase and receives updates over
Supabase Realtime. It never reads the operational `windows`, `predictions`, or
`trades` tables directly. Access requires a Supabase Auth email/password session;
the browser no longer has anonymous read access to the snapshot.

```bash
cp .env.example .env
npm install
npm run dev
```

Required browser configuration:

```dotenv
VITE_DASHBOARD_MODE=paper
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
```

`VITE_DASHBOARD_MODE` accepts only `paper` or `live`. It selects which snapshot
the dashboard displays; it cannot arm live trading or change the worker's
`MODE`. Vite embeds these values at build time, so changing the displayed mode
requires a rebuild/redeploy.

Only the publishable browser key belongs here. Never put `DB_URL`, a database
password, a Supabase secret key, or a service-role key in a `VITE_*` variable.

## Dashboard access

1. Apply the latest Supabase migrations.
2. In **Authentication → Providers → Email**, keep email/password enabled and
   disable public user sign-ups for this private dashboard.
3. In **Authentication → Users**, create or invite each dashboard user.

The app deliberately offers sign-in and sign-out only. Database RLS grants
`dashboard_snapshots` reads to authenticated sessions and rejects the `anon`
role, so bypassing the login screen does not expose dashboard data.

Freshness is separate from trading activity. Each snapshot carries
`snapshot_updated_at`, `market_data_at`, and `last_trade_at`. A stale-market
warning appears only while positions are open and their oldest current bid is
more than 180 seconds old. Positions awaiting resolution do not trigger the
warning, and the absence of a new trade does not trigger it.
