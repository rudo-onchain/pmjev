import React from 'react';
import { MotionConfig } from 'framer-motion';
import { Dashboard } from './components/Dashboard';

type Scenario = 'profit' | 'loss' | 'empty' | 'loading' | 'error' | 'stale';

interface AppProps {
  scenario?: Scenario;
}

export function App({ scenario = 'profit' }: AppProps) {
  return (
    <MotionConfig reducedMotion="user">
      <Dashboard scenario={scenario} />
    </MotionConfig>);

}