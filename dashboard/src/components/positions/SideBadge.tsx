import { ArrowDownRightIcon, ArrowUpRightIcon } from 'lucide-react';
import type { Side } from '../../types/portfolio';

export function SideBadge({ side }: {side: Side;}) {
  const Icon = side === 'UP' ? ArrowUpRightIcon : ArrowDownRightIcon;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-line px-1.5 py-0.5 text-xs font-medium text-ink">
      <Icon className="h-3 w-3 text-muted" aria-hidden="true" />
      {side}
    </span>);

}