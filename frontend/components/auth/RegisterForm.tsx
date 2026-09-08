'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';

import {
  AuthShell,
  Divider,
  ErrorNotice,
  Field,
  Notice,
  ProviderButtons,
  SubmitButton,
} from '@/components/auth/AuthShell';
import { useSession } from '@/components/auth/SessionProvider';
import { auth, AuthError } from '@/lib/auth';

const MIN_PASSWORD_LENGTH = 10;

/**
 * Create an account.
 *
 * The copy does real work here. Somebody arriving on this page has usually just run an
 * estimate and been offered the chance to keep it, so the page has to answer "why would
 * I?" honestly and briefly — and it has to make clear that declining costs them nothing,
 * because the calculator does not require an account and never will.
 *
 * There is no confirm-password field. It exists to catch typos, and a reveal toggle
 * catches them better while asking for half as much typing.
 */
export function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { adopt } = useSession();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AuthError | null>(null);

  const redirectTo = params.get('redirect_to') ?? '/projects';
  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Registers, then signs in. Two calls, because registration returns no session —
      // a response that carried a token for a new address and none for an existing one
      // would tell an attacker which addresses are registered.
      const session = await auth.register(email, password);
      adopt(session.user);
      router.replace(redirectTo);
    } catch (err) {
      const failure =
        err instanceof AuthError ? err : new AuthError('We could not create that account.', 0);

      // The one case worth rewording. Registration succeeded from the client's point of
      // view and the sign-in that followed was refused, which means the address already
      // has an account with a different password. Saying so here is safe: the person
      // typed the address themselves.
      if (failure.code === 'invalid_credentials') {
        setError(
          new AuthError(
            'That address already has a Helios account, and that password does not match it.',
            failure.status,
            'account_exists',
            'Sign in instead, or reset the password if you have forgotten it.',
          ),
        );
      } else {
        setError(failure);
      }
      setBusy(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Account"
      title="Create an account"
      intro="Keep your estimates together and open them from any device."
      footer={
        <p>
          Already have one?{' '}
          <Link
            href={`/login?redirect_to=${encodeURIComponent(redirectTo)}`}
            className="link-underline text-ink-1"
          >
            Sign in
          </Link>
          .
        </p>
      }
    >
      <div className="space-y-6">
        <Notice tone="info">
          An account is optional. The calculator works without one, and every estimate you
          run still gets its own link — an account just means they follow you between
          devices.
        </Notice>

        <ErrorNotice error={error} />

        <ProviderButtons redirectTo={redirectTo} verb="Sign up with" />
        <Divider />

        <form onSubmit={submit} className="space-y-5" noValidate>
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            placeholder="you@example.com"
            hint="We use this to confirm your account and to reset a forgotten password. Nothing else."
            autoFocus
            disabled={busy}
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            hint={`At least ${MIN_PASSWORD_LENGTH} characters. A short phrase you will remember beats a short word with symbols in it.`}
            error={tooShort ? `A few more characters — ${MIN_PASSWORD_LENGTH} at minimum.` : null}
            disabled={busy}
          />
          <SubmitButton busy={busy} disabled={tooShort || !email || !password}>
            Create account
          </SubmitButton>
        </form>
      </div>
    </AuthShell>
  );
}
