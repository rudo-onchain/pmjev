import { MotionConfig } from 'framer-motion';
import { Dashboard } from './components/Dashboard';
import { AuthLoadingScreen, LoginScreen } from './components/auth/LoginScreen';
import { getSupabaseClient } from './data/supabaseClient';
import { useDashboardAuth } from './hooks/useDashboardAuth';
import type { Scenario } from './types/portfolio';

interface AppProps {
  scenario?: Scenario;
}

export function App({ scenario }: AppProps) {
  if (scenario) {
    return (
      <MotionConfig reducedMotion="user">
        <Dashboard scenario={scenario} />
      </MotionConfig>
    );
  }

  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  const client = getSupabaseClient();
  const auth = useDashboardAuth(client);

  if (!auth.ready) return <AuthLoadingScreen />;

  if (!auth.user) {
    return (
      <LoginScreen
        busy={auth.busy}
        error={auth.error}
        onSignIn={auth.signIn}
        onInput={auth.clearError}
      />
    );
  }

  return (
    <MotionConfig reducedMotion="user">
      <Dashboard
        userEmail={auth.user.email ?? 'Signed in'}
        signingOut={auth.busy}
        onSignOut={() => void auth.signOut()}
      />
    </MotionConfig>
  );
}
