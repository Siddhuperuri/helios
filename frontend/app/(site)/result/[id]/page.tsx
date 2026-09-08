import type { Metadata } from 'next';

import { ResultView } from '@/components/result/ResultView';

export const metadata: Metadata = {
  title: 'Your solar potential',
  description: 'Expected generation, savings and the assumptions behind them.',
};

export default async function ResultPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ResultView estimateId={id} />;
}
