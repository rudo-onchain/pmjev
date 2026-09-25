import type { DashboardMode } from './types/portfolio';

export interface DashboardConfig {
  mode: DashboardMode;
  supabaseUrl: string;
  supabasePublishableKey: string;
}

function required(value: string | undefined, name: string): string {
  const normalized = value?.trim();
  if (!normalized) throw new Error(`${name} is required`);
  return normalized;
}

export function readDashboardConfig(): DashboardConfig {
  const rawMode = required(import.meta.env.VITE_DASHBOARD_MODE, 'VITE_DASHBOARD_MODE');
  if (rawMode !== 'paper' && rawMode !== 'live') {
    throw new Error('VITE_DASHBOARD_MODE must be paper or live');
  }
  return {
    mode: rawMode,
    supabaseUrl: required(import.meta.env.VITE_SUPABASE_URL, 'VITE_SUPABASE_URL'),
    supabasePublishableKey: required(
      import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
      'VITE_SUPABASE_PUBLISHABLE_KEY'
    )
  };
}
