import type { Metadata } from 'next';

import { EstimateWizard } from '@/components/estimate/EstimateWizard';

export const metadata: Metadata = {
  title: 'Your details',
  description: 'Answer a few questions and we will work out your solar potential.',
};

export default function EstimatePage() {
  return <EstimateWizard />;
}
