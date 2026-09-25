import React from 'react';
import type { PositionStatus } from '../../types/portfolio';

const config: Record<PositionStatus, {label: string;className: string;dot: string;}> = {
  open: { label: 'Open', className: 'border-line bg-raised text-ink', dot: 'bg-ink/70' },
  exiting: { label: 'Exiting', className: 'border-info/30 bg-info/10 text-info', dot: 'bg-info' },
  awaiting_resolution: {
    label: 'Awaiting resolution',
    className: 'border-warn/30 bg-warn/10 text-warn',
    dot: 'bg-warn'
  }
};

export function StatusBadge({ status }: {status: PositionStatus;}) {
  const c = config[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${c.className}`}>
      
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} aria-hidden="true" />
      {c.label}
    </span>);

}