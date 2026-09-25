import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { emptySnapshot, lossSnapshot, profitSnapshot } from '../data/portfolio';
import { emptySeries, lossSeries, profitSeries } from '../data/equitySeries';
import { buildRangeSeries } from '../utils/series';
import type { ChartRange, ConnectionState, EquityPoint, PortfolioSnapshot, Scenario } from '../types/portfolio';

const LIVE_REFRESH_MS = 15_000;
const LOAD_DELAY_MS = 800;
const RETRY_DELAY_MS = 1200;

const initialAgeSeconds: Record<Scenario, number> = {
  profit: 10,
  loss: 10,
  empty: 10,
  loading: 0,
  error: 252,
  stale: 94
};

function sourceFor(scenario: Scenario) {
  if (scenario === 'loss') return { base: lossSnapshot, series: lossSeries };
  if (scenario === 'empty') return { base: emptySnapshot, series: emptySeries };
  return { base: profitSnapshot, series: profitSeries };
}

export interface PortfolioData {
  isLoading: boolean;
  snapshot: PortfolioSnapshot;
  series: Record<ChartRange, EquityPoint[]>;
  connection: ConnectionState;
  updatedAt: number;
  retry: () => void;
  retrying: boolean;
}

export function usePortfolioData(scenario: Scenario): PortfolioData {
  const [isLoading, setIsLoading] = useState(true);
  const [recovered, setRecovered] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(() => Date.now() - initialAgeSeconds[scenario] * 1000);
  const retryTimer = useRef<number>();

  useEffect(() => {
    setIsLoading(true);
    setRecovered(false);
    setRetrying(false);
    setUpdatedAt(Date.now() - initialAgeSeconds[scenario] * 1000);
    if (scenario === 'loading') return;
    const id = window.setTimeout(() => setIsLoading(false), LOAD_DELAY_MS);
    return () => window.clearTimeout(id);
  }, [scenario]);

  const connection: ConnectionState = isLoading ?
  'connecting' :
  scenario === 'error' && !recovered ?
  'error' :
  scenario === 'stale' ?
  'stale' :
  'live';

  useEffect(() => {
    if (connection !== 'live') return;
    const id = window.setInterval(() => setUpdatedAt(Date.now()), LIVE_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [connection]);

  useEffect(() => () => window.clearTimeout(retryTimer.current), []);

  const retry = useCallback(() => {
    setRetrying(true);
    retryTimer.current = window.setTimeout(() => {
      setRetrying(false);
      setRecovered(true);
      setUpdatedAt(Date.now());
    }, RETRY_DELAY_MS);
  }, []);

  const { base, series: seriesConfig } = sourceFor(scenario);

  const snapshot = useMemo<PortfolioSnapshot>(
    () => ({ ...base, updated_at: new Date(updatedAt).toISOString() }),
    [base, updatedAt]
  );

  const series = useMemo(() => buildRangeSeries(seriesConfig, Date.now()), [seriesConfig]);

  return { isLoading, snapshot, series, connection, updatedAt, retry, retrying };
}