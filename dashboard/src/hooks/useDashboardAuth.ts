import { useCallback, useEffect, useState } from 'react';
import type { SupabaseClient, User } from '@supabase/supabase-js';

export interface DashboardAuth {
  ready: boolean;
  user: User | null;
  busy: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  clearError: () => void;
}

export function useDashboardAuth(client: SupabaseClient): DashboardAuth {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    void client.auth.getUser().then(({ data, error: authError }) => {
      if (!active) return;
      setUser(authError ? null : data.user);
      setReady(true);
    });

    const {
      data: { subscription }
    } = client.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      setUser(session?.user ?? null);
      setReady(true);
      setError(null);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [client]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      setBusy(true);
      setError(null);
      try {
        const { error: signInError } = await client.auth.signInWithPassword({
          email: email.trim(),
          password
        });
        if (signInError) throw signInError;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'Unable to sign in. Please try again.');
      } finally {
        setBusy(false);
      }
    },
    [client]
  );

  const signOut = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { error: signOutError } = await client.auth.signOut({ scope: 'local' });
      if (signOutError) throw signOutError;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to sign out. Please try again.');
    } finally {
      setBusy(false);
    }
  }, [client]);

  return {
    ready,
    user,
    busy,
    error,
    signIn,
    signOut,
    clearError: () => setError(null)
  };
}
