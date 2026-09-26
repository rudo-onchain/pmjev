alter table public.predictions
  add column if not exists p_deepseek_direct double precision
    check (p_deepseek_direct between 0 and 1),
  add column if not exists deepseek_direct_action text
    check (deepseek_direct_action in ('buy_up', 'buy_down', 'skip')),
  add column if not exists deepseek_direct_latency_ms double precision
    check (deepseek_direct_latency_ms >= 0),
  add column if not exists deepseek_direct_error text,
  add column if not exists deepseek_direct_provider text;

alter table public.trades
  drop constraint if exists trades_model_check,
  drop constraint if exists trades_deepseek_direct_paper_only;

alter table public.trades
  add constraint trades_model_check
    check (
      model in ('gbm', 'trend_gbm', 'jev', 'jev_mkt', 'deepseek', 'deepseek_direct')
    ),
  add constraint trades_deepseek_direct_paper_only
    check (model <> 'deepseek_direct' or mode = 'paper');

create index if not exists predictions_deepseek_direct_attempts_idx
  on public.predictions(ts)
  where deepseek_direct_latency_ms is not null or deepseek_direct_error is not null;
