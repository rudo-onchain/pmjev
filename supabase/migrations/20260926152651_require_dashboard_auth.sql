-- Dashboard snapshots contain sanitized data, but they are no longer public.
-- The dashboard intentionally has no self-service sign-up flow; provision users
-- through Supabase Auth and keep public sign-ups disabled for this private app.
revoke select on table public.dashboard_snapshots from anon;

drop policy if exists "dashboard snapshots are read only"
  on public.dashboard_snapshots;

create policy "authenticated users can read dashboard snapshots"
  on public.dashboard_snapshots
  for select
  to authenticated
  using ((select auth.uid()) is not null);

comment on table public.dashboard_snapshots is
  'Sanitized paper/live dashboard read model. Authenticated users have SELECT only.';
