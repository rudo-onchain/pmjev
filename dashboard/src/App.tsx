import { MotionConfig } from 'framer-motion';
import { Dashboard } from './components/Dashboard';
import type { Scenario } from './types/portfolio';

interface AppProps {
  scenario?: Scenario;
}

export function App({ scenario }: AppProps) {
  return (
    <MotionConfig reducedMotion="user">
      <Dashboard scenario={scenario} />
    </MotionConfig>);

}
