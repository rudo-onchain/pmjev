import { CircleCheckIcon, CircleXIcon, LogOutIcon, PlusIcon } from 'lucide-react';
import { Panel } from '../ui/Panel';
import { PnlDelta } from '../ui/PnlDelta';
import { formatAgo, formatPrice, formatUsd } from '../../utils/format';
import { secondsBetween } from '../../utils/time';
import type { ActivityEvent, AssetFilterValue } from '../../types/portfolio';

interface RecentActivityProps {
  events: ActivityEvent[];
  assetFilter: AssetFilterValue;
  now: number;
  className?: string;
}

const MAX_EVENTS = 6;

function describe(e: ActivityEvent): {title: string;detail: string;Icon: typeof PlusIcon;} {
  if (e.type === 'opened') {
    return {
      title: `Opened ${e.asset} ${e.side}`,
      detail: `${e.model} · ${formatUsd(e.size_usd)} at ${formatPrice(e.price ?? 0)}`,
      Icon: PlusIcon
    };
  }
  if (e.type === 'exited') {
    return {
      title: `Exited ${e.asset} ${e.side}`,
      detail: `${e.model} · sold at ${formatPrice(e.price ?? 0)}`,
      Icon: LogOutIcon
    };
  }
  return {
    title: `Resolved ${e.asset} ${e.side} · ${e.outcome === 'won' ? 'Won' : 'Lost'}`,
    detail: `${e.model} · ${formatUsd(e.size_usd)} stake`,
    Icon: e.outcome === 'won' ? CircleCheckIcon : CircleXIcon
  };
}

export function RecentActivity({ events, assetFilter, now, className = '' }: RecentActivityProps) {
  const visible = events.slice(0, MAX_EVENTS);

  return (
    <Panel aria-labelledby="activity-heading" className={`flex flex-col p-6 ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="activity-heading" className="text-sm font-medium text-ink">
          Recent activity
        </h2>
        <span className="text-xs text-subtle">{assetFilter === 'All' ? 'All assets' : assetFilter}</span>
      </div>

      {visible.length === 0 ?
      <p className="mt-6 text-sm text-muted">No {assetFilter === 'All' ? '' : `${assetFilter} `}activity yet.</p> :

      <ol className="-mx-1 mt-3 divide-y divide-line-soft">
          {visible.map((e) => {
          const { title, detail, Icon } = describe(e);
          return (
            <li key={e.id} className="flex items-center gap-3 px-1 py-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-raised text-muted">
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">{title}</p>
                  <p className="truncate text-xs text-muted">{detail}</p>
                </div>
                <div className="shrink-0 text-right">
                  {e.realized_pnl === null ?
                <p className="text-sm text-subtle">
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">No realized PnL</span>
                    </p> :

                <PnlDelta value={e.realized_pnl} className="text-sm font-medium" />
                }
                  <p className="text-xs tabular-nums text-subtle">
                    <time dateTime={e.timestamp}>
                      {formatAgo(secondsBetween(new Date(e.timestamp).getTime(), now))}
                    </time>
                  </p>
                </div>
              </li>);

        })}
        </ol>
      }
    </Panel>);

}