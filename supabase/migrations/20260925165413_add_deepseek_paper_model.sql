alter table public.predictions
  add column if not exists p_deepseek double precision
    check (p_deepseek between 0 and 1),
  add column if not exists deepseek_latency_ms double precision
    check (deepseek_latency_ms >= 0),
  add column if not exists deepseek_error text,
  add column if not exists deepseek_provider text;

alter table public.trades
  drop constraint if exists trades_model_check;

alter table public.trades
  add constraint trades_model_check
    check (model in ('gbm', 'trend_gbm', 'jev', 'jev_mkt', 'deepseek')),
  add constraint trades_deepseek_paper_only
    check (model <> 'deepseek' or mode = 'paper');

create index if not exists predictions_deepseek_attempts_idx
  on public.predictions(ts)
  where deepseek_latency_ms is not null or deepseek_error is not null;
