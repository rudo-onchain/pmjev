import React from 'react';
import { formatCountdown } from '../../utils/format';
import { MARKET_WINDOW_SECONDS, marketSecondsRemaining } from '../../utils/time';
import type { PositionStatus } from '../../types/portfolio';

interface TimeRemainingProps {
  endAt: string;
  now: number;
  status: PositionStatus;
}

export function TimeRemaining({ endAt, now, status }: TimeRemainingProps) {
  if (status === 'awaiting_resolution') {
    return <span className="whitespace-nowrap text-sm text-muted">Market ended</span>;
  }
  const remaining = marketSecondsRemaining(endAt, now);
  const pct = remaining / MARKET_WINDOW_SECONDS * 100;

  return (
    <div className="flex w-[72px] flex-col gap-1.5">
      <span className={`text-sm tabular-nums ${remaining < 30 ? 'font-semibold text-ink' : 'text-ink'}`}>
        <span className="sr-only">Time remaining </span>
        {formatCountdown(remaining)}
      </span>
      <span className="h-1 w-full overflow-hidden rounded-full bg-line" aria-hidden="true">
        <span className="block h-full rounded-full bg-muted" style={{ width: `${pct}%` }} />
      </span>
    </div>);

}