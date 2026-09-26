import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { readDashboardConfig, type DashboardConfig } from '../config';

let browserClient: SupabaseClient | null = null;

export function getSupabaseClient(config: DashboardConfig = readDashboardConfig()): SupabaseClient {
  if (browserClient) return browserClient;

  browserClient = createClient(config.supabaseUrl, config.supabasePublishableKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true
    }
  });
  return browserClient;
}
