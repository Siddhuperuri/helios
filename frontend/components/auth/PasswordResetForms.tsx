'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';

import {
  AuthShell,
  ErrorNotice,
  Field,
  Notice,
  SubmitButton,
} from '@/components/auth/AuthShell';
import { auth, AuthError } from '@/lib/auth';

const MIN_PASSWORD_LENGTH = 10;

/**
 * Ask for a reset link.
 *
 * The success state is deliberately the same whether or not the address has an account.
 * The API answers identically for both — telling the caller "no account with that address"
 * would turn this form into a way to test which addresses are registered — and the
 * interface must not undo that by rendering two different screens.
 *
 * So the confirmation says *if* there is an account. That reads as slightly hedged, which
 * is the honest cost of not running an enumeration oracle on a public page.
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<AuthError | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(
        err instanceof AuthError ? err : new AuthError('We could not send that link.', 0),
      );
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthShell
        eyebrow="Account"
        title="Check your email"
        footer={
          <p>
            <Link href="/login" className="link-underline text-ink-1">
              Back to sign in
            </Link>
          </p>
        }
      >
        <Notice tone="success" title="If that address has an account, a link is on its way">
          <p>
            It works once and expires in an hour. Setting a new password signs you out
            everywhere else.
          </p>
          <p className="mt-2 text-ink-3">
            Nothing yet? Check your spam folder, and confirm you typed{' '}
            <span className="text-ink-2">{email}</span> correctly.
          </p>
        </Notice>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Account"
      title="Reset your password"
      intro="Tell us the address on the account and we will send a link to set a new password."
      footer={
        <p>
          Remembered it?{' '}
          <Link href="/login" className="link-underline text-ink-1">
            Sign in
          </Link>
          .
        </p>
      }
    >
      <div className="space-y-6">
        <ErrorNotice error={error} />
        <form onSubmit={submit} className="space-y-5" noValidate>
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            placeholder="you@example.com"
            autoFocus
            disabled={busy}
          />
          <SubmitButton busy={busy} disabled={!email}>
            Send reset link
          </SubmitButton>
        </form>
      </div>
    </AuthShell>
  );
}

/**
 * Set a new password from a link.
 *
 * The screen says plainly that this ends every other session, because it does and because
 * a user who is resetting because they think someone else has access needs to know it
 * worked.
 */
export function ResetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AuthError | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.resetPassword(token, password);
      router.replace('/login?reset=1');
    } catch (err) {
      setError(
        err instanceof AuthError ? err : new AuthError('We could not set that password.', 0),
      );
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthShell eyebrow="Account" title="That link is incomplete">
        <Notice tone="error" title="No reset token in the address">
          <p>
            Open the link from the email directly rather than retyping it — the token at the
            end is what identifies the request.
          </p>
          <p className="mt-3">
            <Link href="/forgot-password" className="link-underline text-ink-1">
              Request a new link
            </Link>
          </p>
        </Notice>
      </AuthShell>
    );
  }

  // `token_expired` is a distinct code from the API precisely so this screen can offer the
  // one action that helps rather than a dead end.
  const expired = error?.code === 'token_expired';

  return (
    <AuthShell
      eyebrow="Account"
      title="Choose a new password"
      intro="This link works once. Setting a new password signs you out on every other device."
    >
      <div className="space-y-6">
        {expired ? (
          <Notice tone="error" title="That link has expired">
            <p>Reset links last an hour. Ask for another and it will arrive straight away.</p>
            <p className="mt-3">
              <Link href="/forgot-password" className="link-underline text-ink-1">
                Send me a new link
              </Link>
            </p>
          </Notice>
        ) : (
          <ErrorNotice error={error} />
        )}

        <form onSubmit={submit} className="space-y-5" noValidate>
          <Field
            label="New password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
            error={tooShort ? `A few more characters — ${MIN_PASSWORD_LENGTH} at minimum.` : null}
            autoFocus
            disabled={busy || expired}
          />
          <SubmitButton busy={busy} disabled={tooShort || !password || expired}>
            Set new password
          </SubmitButton>
        </form>
      </div>
    </AuthShell>
  );
}
