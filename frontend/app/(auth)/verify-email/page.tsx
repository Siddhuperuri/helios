import type { Metadata } from 'next';
import { Suspense } from 'react';

import { VerifyEmailView } from '@/components/auth/VerifyEmailView';

export const metadata: Metadata = {
  title: 'Confirm your email',
  robots: { index: false, follow: false },
};

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailView />
    </Suspense>
  );
}
