import type { Metadata } from 'next';

import { PredictView } from '@/components/predict/PredictView';

export const metadata: Metadata = {
  title: 'Predict an hour',
  description:
    'Pick a place, a date and an hour, and see the energy a declared array produced in ' +
    'it — predicted by a model trained only on weather from before that hour.',
};

export default function PredictPage() {
  return <PredictView />;
}
