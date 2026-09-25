import React from 'react';
import { ClockIcon } from 'lucide-react';
import { formatPrice } from '../../utils/format';

export function BidValue({ value, isStale }: {value: number;isStale: boolean;}) {
  if (!isStale) return <span className="tabular-nums text-ink">{formatPrice(value)}</span>;
  return (
    <span className="inline-flex items-center gap-1 tabular-nums text-muted" title="Bid may be out of date">
      {formatPrice(value)}
      <ClockIcon className="h-3 w-3 text-warn" aria-hidden="true" />
      <span className="sr-only">(stale)</span>
    </span>);

}