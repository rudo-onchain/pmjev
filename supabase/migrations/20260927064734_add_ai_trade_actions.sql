alter table public.predictions
  add column if not exists jev_action text
    check (jev_action in ('buy_up', 'buy_down', 'skip')),
  add column if not exists jev_mkt_action text
    check (jev_mkt_action in ('buy_up', 'buy_down', 'skip')),
  add column if not exists deepseek_action text
    check (deepseek_action in ('buy_up', 'buy_down', 'skip'));
