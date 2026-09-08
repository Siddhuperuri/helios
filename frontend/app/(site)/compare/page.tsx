import type { Metadata } from 'next';

import { CompareView } from '@/components/result/CompareView';

export const metadata: Metadata = {
  title: 'Compare system sizes',
  description: 'Generation, cost, payback and space for several system sizes, side by side.',
};

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string }>;
}) {
  const { from } = await searchParams;
  return <CompareView fromEstimateId={from ?? null} />;
}
