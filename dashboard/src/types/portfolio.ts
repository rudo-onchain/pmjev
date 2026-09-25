export type DashboardMode = 'paper' | 'live';
export type Asset = string;
export type AssetFilterValue = 'All' | Asset;
export type Model = 'JEV' | 'JEV Market' | 'Trend GBM' | 'GBM';
export type Side = 'UP' | 'DOWN';
export type PositionStatus = 'open' | 'exiting' | 'awaiting_resolution';

export interface OpenPosition {
  id: string;
  asset: Asset;
  model: Model;
  side: Side;
  entry_price: number;
  current_bid: number;
  size_usd: number;
  unrealized_pnl: number;
  market_end_at: string;
  status: PositionStatus;
}

export type ActivityType = 'opened' | 'exited' | 'resolved';

export interface ActivityEvent {
  id: string;
  type: ActivityType;
  asset: Asset;
  model: Model;
  side: Side;
  size_usd: number;
  price: number | null;
  realized_pnl: number | null;
  outcome?: 'won' | 'lost';
  timestamp: string;
}

export type ModelPeriod = '24H' | '7D' | 'ALL';

export interface ModelStats {
  model: Model;
  trades: number;
  wins: number;
  realized_pnl: number;
  unrealized_pnl: number;
  capital_deployed: number;
  open_positions: number;
}

export interface PortfolioSnapshot {
  mode: DashboardMode;
  assets: Asset[];
  portfolio_equity: number;
  starting_balance: number;
  total_pnl: number;
  total_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  available_balance: number;
  open_exposure: number;
  open_positions: OpenPosition[];
  recent_activity: ActivityEvent[];
  model_performance: Record<ModelPeriod, ModelStats[]>;
  snapshot_updated_at: string;
  market_data_at: string | null;
  last_trade_at: string | null;
  updated_at: string;
}

export type PortfolioBase = Omit<
  PortfolioSnapshot,
  'snapshot_updated_at' | 'market_data_at' | 'last_trade_at' | 'updated_at'
>;

export type ChartRange = '1H' | '24H' | '7D' | 'ALL';

export interface EquityPoint {
  t: number;
  equity: number;
}

export interface SeriesConfig {
  start: number;
  end: number;
  points: number;
  stepMinutes: number;
  volatility: number;
  seed: number;
}

export type Scenario = 'profit' | 'loss' | 'empty' | 'loading' | 'error' | 'stale';
export type ConnectionState = 'live' | 'stale' | 'error' | 'connecting';
