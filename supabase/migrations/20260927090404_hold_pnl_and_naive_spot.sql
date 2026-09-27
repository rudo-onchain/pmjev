-- hold_pnl: what every trade would have made if held to resolution, recorded
-- even when a paper early exit already set pnl. Live mode holds to resolution,
-- so hold_pnl is the paper number that is comparable to live.
alter table public.trades
  add column if not exists hold_pnl double precision;

update public.trades as trade
set hold_pnl = (
      case
        when (trade.side = 'up' and market_window.outcome = 1)
          or (trade.side = 'down' and market_window.outcome = 0)
        then trade.size
        else 0
      end
    ) - trade.price * trade.size - trade.fee
from public.windows as market_window
where market_window.slug = trade.window_slug
  and market_window.outcome is not null
  and trade.hold_pnl is null
  and (trade.mode <> 'live' or trade.execution_status = 'matched');

-- naive_spot: rule-based control model (buy the side the reference spot is on).
alter table public.trades
  drop constraint if exists trades_model_check;

alter table public.trades
  add constraint trades_model_check
    check (
      model in (
        'gbm', 'trend_gbm', 'jev', 'jev_mkt', 'deepseek', 'deepseek_direct', 'naive_spot'
      )
    );
