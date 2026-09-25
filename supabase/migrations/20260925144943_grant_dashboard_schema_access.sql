-- Data API roles need namespace access before table grants and RLS are evaluated.
-- Raw trading tables remain private because they still have no table privileges.
grant usage on schema public to anon, authenticated;
grant select on table public.dashboard_snapshots to anon, authenticated;
