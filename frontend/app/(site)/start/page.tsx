import type { Metadata } from 'next';

import { StartFlow } from '@/components/estimate/StartFlow';

export const metadata: Metadata = {
  title: 'Solar Calculator',
  description: 'Tell us what you are planning to power and we will work out the solar.',
};

export default function StartPage() {
  return <StartFlow />;
}
