import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readDashboardConfig } from '../config';
import { emptySnapshot, lossSnapshot, profitSnapshot } from '../data/portfolio';
import { emptySeries, lossSeries, profitSeries } from '../data/equitySeries';
import {
  createDashboardSubscription,
  type ChannelState,
  type DashboardRow
} from '../data/supabasePortfolio';
import { buildRangeSeries } from '../utils/series';
import type {
  ChartRange,
  ConnectionState,
  DashboardMode,
  EquityPoint,
  PortfolioSnapshot,
  Scenario
} from '../types/portfolio';

const MOCK_REFRESH_MS = 15_000;
const MOCK_LOAD_DELAY_MS = 800;
const RETRY_DELAY_MS = 1_200;
const STALE_AFTER_MS = 120_000;

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

function blankSeries(): Record<ChartRange, EquityPoint[]> {
  return { '1H': [], '24H': [], '7D': [], ALL: [] };
}

function blankSnapshot(mode: DashboardMode): PortfolioSnapshot {
  return {
    mode,
    assets: [],
    portfolio_equity: 100,
    starting_balance: 100,
    total_pnl: 0,
    total_return_pct: 0,
    realized_pnl: 0,
    unrealized_pnl: 0,
    available_balance: 100,
    open_exposure: 0,
    open_positions: [],
    recent_activity: [],
    model_performance: { '24H': [], '7D': [], ALL: [] },
    updated_at: new Date(0).toISOString()
  };
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

function useMockPortfolioData(scenario: Scenario, enabled: boolean): PortfolioData {
  const [isLoading, setIsLoading] = useState(enabled);
  const [recovered, setRecovered] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(
    () => Date.now() - initialAgeSeconds[scenario] * 1000
  );
  const retryTimer = useRef<number>();

  useEffect(() => {
    if (!enabled) return;
    setIsLoading(true);
    setRecovered(false);
    setRetrying(false);
    setUpdatedAt(Date.now() - initialAgeSeconds[scenario] * 1000);
    if (scenario === 'loading') return;
    const id = window.setTimeout(() => setIsLoading(false), MOCK_LOAD_DELAY_MS);
    return () => window.clearTimeout(id);
  }, [enabled, scenario]);

  const connection: ConnectionState = isLoading
    ? 'connecting'
    : scenario === 'error' && !recovered
      ? 'error'
      : scenario === 'stale'
        ? 'stale'
        : 'live';

  useEffect(() => {
    if (!enabled || connection !== 'live') return;
    const id = window.setInterval(() => setUpdatedAt(Date.now()), MOCK_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [connection, enabled]);

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

function useRealtimePortfolioData(enabled: boolean): PortfolioData {
  const [config] = useState(() => (enabled ? readDashboardConfig() : null));
  const [source] = useState(() => (config ? createDashboardSubscription(config) : null));
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot>(() =>
    blankSnapshot(config?.mode ?? 'paper')
  );
  const [series, setSeries] = useState<Record<ChartRange, EquityPoint[]>>(blankSeries);
  const [updatedAt, setUpdatedAt] = useState(0);
  const [isLoading, setIsLoading] = useState(enabled);
  const [transport, setTransport] = useState<ChannelState>('connecting');
  const [retrying, setRetrying] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const version = useRef(0);

  const applyRow = useCallback((row: DashboardRow) => {
    if (row.version < version.current) return;
    version.current = row.version;
    setSnapshot(row.snapshot);
    setSeries(row.series);
    setUpdatedAt(Date.parse(row.snapshot.updated_at || row.updated_at));
    setIsLoading(false);
    setRetrying(false);
  }, []);

  useEffect(() => {
    if (!enabled || !source) return;
    let active = true;
    const channel = source.subscribe(
      (row) => {
        if (active) applyRow(row);
      },
      (state) => {
        if (active) setTransport(state);
      }
    );
    void source
      .load()
      .then((row) => {
        if (active) applyRow(row);
      })
      .catch(() => {
        if (!active) return;
        setTransport('error');
        setIsLoading(false);
        setRetrying(false);
      });
    return () => {
      active = false;
      void source.remove(channel);
    };
  }, [applyRow, enabled, retryKey, source]);

  const retry = useCallback(() => {
    setRetrying(true);
    setTransport('connecting');
    setRetryKey((value) => value + 1);
  }, []);

  const connection: ConnectionState =
    transport === 'live' && updatedAt > 0 && Date.now() - updatedAt > STALE_AFTER_MS
      ? 'stale'
      : transport;
  return { isLoading, snapshot, series, connection, updatedAt, retry, retrying };
}

export function usePortfolioData(scenario?: Scenario): PortfolioData {
  const mock = useMockPortfolioData(scenario ?? 'profit', scenario !== undefined);
  const realtime = useRealtimePortfolioData(scenario === undefined);
  return scenario === undefined ? realtime : mock;
}
