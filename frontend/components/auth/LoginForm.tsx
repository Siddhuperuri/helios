'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

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

/**
 * Sign in.
 *
 * Also the landing place for a failed OAuth attempt, which is why it reads `auth_error`
 * from the query string. The callback cannot render an explanation itself — the user is
 * mid-navigation in a browser — so it redirects here with the reason attached, and this
 * page is where "we do not link accounts automatically" actually gets said to somebody.
 */
export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { adopt } = useSession();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AuthError | null>(null);

  const redirectTo = params.get('redirect_to') ?? '/projects';
  const oauthError = params.get('auth_error');
  const oauthMessage = params.get('auth_message');
  const justReset = params.get('reset') === '1';
  const justVerified = params.get('verified') === '1';

  // An OAuth callback that succeeded redirects here with a one-time code rather than a
  // token: a token in a URL ends up in browser history, in the Referer header of the next
  // request, and in every proxy log along the way.
  const handoffCode = params.get('auth_code');

  useEffect(() => {
    if (!handoffCode) return;
    let cancelled = false;
    setBusy(true);
    auth
      .exchangeOAuthCode(handoffCode)
      .then((session) => {
        if (cancelled) return;
        adopt(session.user);
        router.replace(redirectTo);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof AuthError
            ? err
            : new AuthError('That sign-in could not be completed.', 0),
        );
        setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [handoffCode, adopt, router, redirectTo]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await auth.login(email, password);
      adopt(session.user);
      router.replace(redirectTo);
    } catch (err) {
      setError(
        err instanceof AuthError ? err : new AuthError('We could not sign you in.', 0),
      );
      setBusy(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Account"
      title="Sign in"
      intro="Your saved estimates, on whichever device you are using."
      footer={
        <p>
          No account yet?{' '}
          <Link
            href={`/register?redirect_to=${encodeURIComponent(redirectTo)}`}
            className="link-underline text-ink-1"
          >
            Create one
          </Link>
          . You can also keep using the calculator without one.
        </p>
      }
    >
      <div className="space-y-6">
        {oauthError ? (
          <Notice
            tone={oauthError === 'link_required' ? 'info' : 'error'}
            title={
              oauthError === 'link_required'
                ? 'Sign in first to connect that account'
                : 'That sign-in did not complete'
            }
          >
            {oauthMessage ??
              'Something interrupted the sign-in. Try again, or use your email and password.'}
          </Notice>
        ) : null}

        {justReset ? (
          <Notice tone="success" title="Password changed">
            Sign in with your new password. Every other device has been signed out.
          </Notice>
        ) : null}

        {justVerified ? (
          <Notice tone="success" title="Email confirmed">
            Your address is confirmed. Sign in to pick up where you left off.
          </Notice>
        ) : null}

        <ErrorNotice error={error} />

        <ProviderButtons redirectTo={redirectTo} />
        <Divider />

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
          <div>
            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              disabled={busy}
            />
            <p className="mt-2 text-right">
              <Link href="/forgot-password" className="text-xs text-ink-3 link-underline">
                Forgotten your password?
              </Link>
            </p>
          </div>
          <SubmitButton busy={busy}>Sign in</SubmitButton>
        </form>
      </div>
    </AuthShell>
  );
}
