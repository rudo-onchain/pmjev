import { useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Header } from './layout/Header';
import { StatusBanner } from './layout/StatusBanner';
import { PortfolioSummary } from './portfolio/PortfolioSummary';
import { PnlBreakdown } from './portfolio/PnlBreakdown';
import { PerformanceChart } from './portfolio/PerformanceChart';
import { PerformanceChartBody } from './portfolio/PerformanceChartBody';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { OpenPositions } from './positions/OpenPositions';
import { RecentActivity } from './activity/RecentActivity';
import { ModelComparison } from './models/ModelComparison';
import { DashboardSkeleton } from './DashboardSkeleton';
import { usePortfolioData } from '../hooks/usePortfolioData';
import { useNow } from '../hooks/useNow';
import { secondsBetween } from '../utils/time';
import type { AssetFilterValue, Scenario } from '../types/portfolio';

interface DashboardProps {
  scenario?: Scenario;
}

export function Dashboard({ scenario }: DashboardProps) {
  const { isLoading, snapshot, series, connection, updatedAt, retry, retrying } = usePortfolioData(scenario);
  const now = useNow(1000);
  const isDesktop = useMediaQuery('(min-width: 1024px)');
  const [assetFilter, setAssetFilter] = useState<AssetFilterValue>('All');

  const secondsAgo = secondsBetween(updatedAt, now);
  const isStale = connection === 'stale' || connection === 'error';

  const positions = useMemo(
    () => snapshot.open_positions.filter((p) => assetFilter === 'All' || p.asset === assetFilter),
    [snapshot.open_positions, assetFilter]
  );
  const activity = useMemo(
    () => snapshot.recent_activity.filter((e) => assetFilter === 'All' || e.asset === assetFilter),
    [snapshot.recent_activity, assetFilter]
  );

  return (
    <div className="min-h-screen w-full bg-canvas font-sans text-ink antialiased">
      <Header
        connection={connection}
        secondsAgo={secondsAgo}
        assetFilter={assetFilter}
        onAssetChange={setAssetFilter}
        assets={snapshot.assets}
        mode={snapshot.mode} />
      

      <main className="mx-auto max-w-[1360px] space-y-4 px-4 py-6 sm:px-6 lg:space-y-5 lg:px-8 lg:py-6">
        <AnimatePresence initial={false}>
          {connection === 'error' &&
          <StatusBanner key="error" kind="error" secondsAgo={secondsAgo} onRetry={retry} retrying={retrying} />
          }
          {connection === 'stale' && <StatusBanner key="stale" kind="stale" secondsAgo={secondsAgo} />}
        </AnimatePresence>

        {isLoading ?
        <DashboardSkeleton /> :

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
          className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
          
            <PortfolioSummary
            snapshot={snapshot}
            secondsAgo={secondsAgo}
            isLastKnown={connection === 'error'}
            chart={
            isDesktop ?
            <PerformanceChartBody series={series} startingBalance={snapshot.starting_balance} /> :
            undefined
            }
            className="lg:col-span-8 lg:col-start-1 lg:row-start-1" />
          
            <PnlBreakdown snapshot={snapshot} className="lg:col-span-4 lg:col-start-9 lg:row-start-1" />
            <OpenPositions
            positions={positions}
            assetFilter={assetFilter}
            now={now}
            isStale={isStale}
            className="lg:col-span-8 lg:col-start-1 lg:row-start-2" />
          
            {!isDesktop && <PerformanceChart series={series} startingBalance={snapshot.starting_balance} />}
            <ModelComparison
            performance={snapshot.model_performance}
            className="lg:col-span-12 lg:col-start-1 lg:row-start-3" />
          
            <RecentActivity
            events={activity}
            assetFilter={assetFilter}
            now={now}
            className="lg:col-span-4 lg:col-start-9 lg:row-start-2" />
          
          </motion.div>
        }
      </main>

      <footer className="mx-auto max-w-[1360px] px-4 pb-10 text-xs text-subtle sm:px-6 lg:px-8">
        {snapshot.mode === 'paper'
          ? 'Paper trading with simulated funds. PMJEV places no real orders.'
          : 'Live trading dashboard. Values reflect matched orders recorded by PMJEV.'}
      </footer>
    </div>);

}
