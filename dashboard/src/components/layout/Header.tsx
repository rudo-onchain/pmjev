import { FlaskConicalIcon, LoaderCircleIcon, LogOutIcon, ZapIcon } from 'lucide-react';
import { Logo } from './Logo';
import { ConnectionIndicator } from './ConnectionIndicator';
import { SegmentedControl } from '../ui/SegmentedControl';
import type {
  Asset,
  AssetFilterValue,
  ConnectionState,
  DashboardMode
} from '../../types/portfolio';

interface HeaderProps {
  connection: ConnectionState;
  secondsAgo: number;
  assetFilter: AssetFilterValue;
  onAssetChange: (value: AssetFilterValue) => void;
  assets: Asset[];
  mode: DashboardMode;
  userEmail?: string;
  signingOut?: boolean;
  onSignOut?: () => void;
}

export function Header({
  connection,
  secondsAgo,
  assetFilter,
  onAssetChange,
  assets,
  mode,
  userEmail,
  signingOut = false,
  onSignOut
}: HeaderProps) {
  const assetOptions: readonly AssetFilterValue[] = ['All', ...assets];
  const ModeIcon = mode === 'live' ? ZapIcon : FlaskConicalIcon;
  return (
    <header className="sticky top-0 z-20 border-b border-line-soft bg-canvas/90 backdrop-blur">
      <div className="mx-auto max-w-[1360px] px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <Logo />
            <span
              className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1 text-xs font-medium ${
                mode === 'live'
                  ? 'border-warn/40 bg-warn/10 text-warn'
                  : 'border-line bg-surface text-muted'
              }`}
            >
              <ModeIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {mode === 'live' ? 'Live' : 'Paper'}
              <span className="hidden sm:inline"> trading</span>
            </span>
          </div>
          <div className="flex items-center gap-4">
            <SegmentedControl
              className="hidden md:inline-flex"
              options={assetOptions}
              value={assetFilter}
              onChange={onAssetChange}
              label="Filter by asset"
              layoutId="asset-filter-desktop" />

            <ConnectionIndicator connection={connection} secondsAgo={secondsAgo} />
            {onSignOut && (
              <div className="flex items-center gap-2 border-l border-line pl-3">
                <span className="hidden max-w-40 truncate text-xs text-muted xl:block">
                  {userEmail}
                </span>
                <button
                  type="button"
                  onClick={onSignOut}
                  disabled={signingOut}
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-line text-muted transition hover:border-line hover:bg-raised hover:text-ink focus:outline-none focus:ring-2 focus:ring-profit/60 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Sign out"
                  title="Sign out"
                >
                  {signingOut ? (
                    <LoaderCircleIcon className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <LogOutIcon className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="pb-3 md:hidden">
          <SegmentedControl
            className="w-full [&>button]:flex-1"
            options={assetOptions}
            value={assetFilter}
            onChange={onAssetChange}
            label="Filter by asset"
            layoutId="asset-filter-mobile" />
          
        </div>
      </div>
    </header>);

}
