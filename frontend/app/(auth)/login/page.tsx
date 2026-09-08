import type { Metadata } from 'next';
import { Suspense } from 'react';

import { LoginForm } from '@/components/auth/LoginForm';

export const metadata: Metadata = {
  title: 'Sign in',
  description: 'Sign in to see your saved solar estimates on any device.',
};

export default function LoginPage() {
  // The form reads `redirect_to` and the OAuth error parameters from the query string,
  // which requires `useSearchParams` and therefore a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
