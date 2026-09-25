import { motion } from 'framer-motion';
import { RefreshCwIcon, TriangleAlertIcon, WifiOffIcon } from 'lucide-react';
import { formatAgoLong } from '../../utils/format';

interface StatusBannerProps {
  kind: 'error' | 'stale';
  secondsAgo: number | null;
  onRetry?: () => void;
  retrying?: boolean;
}

export function StatusBanner({ kind, secondsAgo, onRetry, retrying = false }: StatusBannerProps) {
  const isError = kind === 'error';
  const Icon = isError ? WifiOffIcon : TriangleAlertIcon;

  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
      className={`flex flex-col gap-3 rounded-xl border px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between ${
      isError ? 'border-loss/30 bg-loss/[0.07]' : 'border-warn/30 bg-warn/[0.07]'}`
      }>
      
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${isError ? 'text-loss' : 'text-warn'}`} aria-hidden="true" />
        <div>
          <p className="text-sm font-medium text-ink">
            {isError ? 'Data connection lost' : 'Market data is stale'}
          </p>
          <p className="mt-0.5 text-sm text-muted">
            {isError ?
            `Can’t reach the PMJEV feed. Showing last known values from ${formatAgoLong(secondsAgo ?? 0)}.` :
            secondsAgo === null ?
            'Current bid timestamps are unavailable. Unrealized PnL may not reflect live prices.' :
            `Current bids haven’t updated in ${secondsAgo}s. Unrealized PnL may not reflect live prices.`}
          </p>
        </div>
      </div>
      {isError && onRetry &&
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        className="inline-flex shrink-0 items-center justify-center gap-2 self-start rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink transition-colors duration-150 hover:bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/60 disabled:cursor-wait disabled:opacity-70 sm:self-auto">
        
          <RefreshCwIcon
          className={`h-3.5 w-3.5 ${retrying ? 'motion-safe:animate-spin' : ''}`}
          aria-hidden="true" />
        
          {retrying ? 'Reconnecting…' : 'Retry'}
        </button>
      }
    </motion.div>);

}
