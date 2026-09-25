alter table public.windows
  add column if not exists window_seconds integer not null default 300
    check (window_seconds > 0),
  add column if not exists fee_rate double precision not null default 0
    check (fee_rate >= 0),
  add column if not exists fee_exponent integer not null default 1
    check (fee_exponent > 0);

create table if not exists public.dashboard_snapshots (
  mode text primary key check (mode in ('paper', 'live')),
  version bigint not null default 1 check (version > 0),
  snapshot jsonb not null,
  series jsonb not null default '{"1H": [], "24H": [], "7D": [], "ALL": []}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.dashboard_equity_points (
  mode text not null check (mode in ('paper', 'live')),
  ts double precision not null check (ts >= 0),
  equity double precision not null,
  primary key (mode, ts)
);

create index if not exists dashboard_equity_points_mode_ts_idx
  on public.dashboard_equity_points(mode, ts desc);

alter table public.dashboard_snapshots enable row level security;
alter table public.dashboard_equity_points enable row level security;

revoke all on table
  public.dashboard_snapshots,
  public.dashboard_equity_points
from public, anon, authenticated;

grant select on table public.dashboard_snapshots to anon, authenticated;

create policy "dashboard snapshots are read only"
  on public.dashboard_snapshots
  for select
  to anon, authenticated
  using (true);

comment on table public.dashboard_snapshots is
  'Sanitized paper/live dashboard read model. Browser roles have SELECT only.';

comment on table public.dashboard_equity_points is
  'Private equity history used to build the dashboard chart series.';

do $$
begin
  if exists (
    select 1 from pg_publication where pubname = 'supabase_realtime'
  ) and not exists (
    select 1
    from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'dashboard_snapshots'
  ) then
    alter publication supabase_realtime add table public.dashboard_snapshots;
  end if;
end
$$;
