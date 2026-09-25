import { createClient, type RealtimeChannel, type SupabaseClient } from '@supabase/supabase-js';
import type { DashboardConfig } from '../config';
import type { ChartRange, EquityPoint, PortfolioSnapshot } from '../types/portfolio';

export interface DashboardRow {
  version: number;
  snapshot: PortfolioSnapshot;
  series: Record<ChartRange, EquityPoint[]>;
  updated_at: string;
}

export type ChannelState = 'connecting' | 'live' | 'error';

export interface DashboardSubscription {
  load: () => Promise<DashboardRow>;
  subscribe: (
    onData: (row: DashboardRow) => void,
    onState: (state: ChannelState) => void
  ) => RealtimeChannel;
  remove: (channel: RealtimeChannel) => Promise<void>;
}

function asDashboardRow(value: unknown, expectedMode: string): DashboardRow {
  if (!value || typeof value !== 'object') throw new Error('Dashboard row is malformed');
  const row = value as Partial<DashboardRow>;
  if (!row.snapshot || row.snapshot.mode !== expectedMode || !row.series) {
    throw new Error(`Dashboard row does not match mode=${expectedMode}`);
  }
  return row as DashboardRow;
}

export function createDashboardSubscription(config: DashboardConfig): DashboardSubscription {
  const client: SupabaseClient = createClient(
    config.supabaseUrl,
    config.supabasePublishableKey,
    {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false }
    }
  );

  return {
    async load() {
      const { data, error } = await client
        .from('dashboard_snapshots')
        .select('version,snapshot,series,updated_at')
        .eq('mode', config.mode)
        .maybeSingle();
      if (error) throw error;
      if (!data) throw new Error(`No dashboard snapshot exists for mode=${config.mode}`);
      return asDashboardRow(data, config.mode);
    },

    subscribe(onData, onState) {
      onState('connecting');
      return client
        .channel(`dashboard-${config.mode}`)
        .on(
          'postgres_changes',
          {
            event: '*',
            schema: 'public',
            table: 'dashboard_snapshots',
            filter: `mode=eq.${config.mode}`
          },
          (payload) => {
            try {
              onData(asDashboardRow(payload.new, config.mode));
            } catch {
              onState('error');
            }
          }
        )
        .subscribe((status) => {
          if (status === 'SUBSCRIBED') onState('live');
          if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
            onState('error');
          }
        });
    },

    async remove(channel) {
      await client.removeChannel(channel);
    }
  };
}
