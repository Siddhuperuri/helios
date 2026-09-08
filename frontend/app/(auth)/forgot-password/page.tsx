import type { Metadata } from 'next';
import { Suspense } from 'react';

import { ForgotPasswordForm } from '@/components/auth/PasswordResetForms';

export const metadata: Metadata = {
  title: 'Reset your password',
  description: 'Send yourself a link to choose a new password.',
};

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ForgotPasswordForm />
    </Suspense>
  );
}
