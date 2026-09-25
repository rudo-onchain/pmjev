import React from 'react';
import { formatAgo } from '../../utils/format';
import type { ConnectionState } from '../../types/portfolio';

interface ConnectionIndicatorProps {
  connection: ConnectionState;
  secondsAgo: number;
}

const config: Record<ConnectionState, {label: string;dot: string;text: string;}> = {
  live: { label: 'Live', dot: 'bg-profit', text: 'text-ink' },
  stale: { label: 'Stale data', dot: 'bg-warn', text: 'text-warn' },
  error: { label: 'Disconnected', dot: 'bg-loss', text: 'text-loss' },
  connecting: { label: 'Connecting…', dot: 'bg-subtle', text: 'text-muted' }
};

export function ConnectionIndicator({ connection, secondsAgo }: ConnectionIndicatorProps) {
  const c = config[connection];
  return (
    <div className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-line bg-surface px-3 py-1.5 text-xs">
      <span className={`h-2 w-2 rounded-full ${c.dot}`} aria-hidden="true" />
      <span role="status" className={`font-medium ${c.text}`}>
        {c.label}
      </span>
      {connection !== 'connecting' &&
      <span className="tabular-nums text-muted">
          <span className="hidden sm:inline">· Updated </span>
          <span className="sm:hidden">· </span>
          {formatAgo(secondsAgo)}
        </span>
      }
    </div>);

}