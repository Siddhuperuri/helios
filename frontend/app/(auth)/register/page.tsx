import type { Metadata } from 'next';
import { Suspense } from 'react';

import { RegisterForm } from '@/components/auth/RegisterForm';

export const metadata: Metadata = {
  title: 'Create an account',
  description: 'Optional. Keep your solar estimates together and open them from any device.',
};

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
