'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { AuthShell, Field, Notice, SubmitButton } from '@/components/auth/AuthShell';
import { useSession } from '@/components/auth/SessionProvider';
import { auth, AuthError } from '@/lib/auth';

type State = 'verifying' | 'done' | 'expired' | 'invalid' | 'no-token';

/**
 * Confirm an email address.
 *
 * The screen exists mostly to handle its failure cases well, which is why it distinguishes
 * *expired* from *invalid* rather than showing one apology for both. An expired link is
 * the common case — people open mail hours later — and it has an obvious fix, so it gets a
 * button that performs it. An invalid link usually means the address was already confirmed
 * or a newer link superseded this one, and offering "send another" there would send people
 * round a loop.
 *
 * The distinction is only possible because the API returns `token_expired` as a code
 * instead of a generic 400.
 */
export function VerifyEmailView() {
  const params = useSearchParams();
  const router = useRouter();
  const { user, status } = useSession();
  const token = params.get('token') ?? '';

  const [state, setState] = useState<State>(token ? 'verifying' : 'no-token');
  const [message, setMessage] = useState<string>('');
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    // React 18's StrictMode double-invokes effects in development. The token is
    // single-use, so without this guard the second call always reports "already used" and
    // a perfectly good link looks broken.
    attempted.current = true;

    auth
      .verifyEmail(token)
      .then(() => setState('done'))
      .catch((err) => {
        const failure = err instanceof AuthError ? err : null;
        setMessage(failure?.message ?? 'That link could not be used.');
        setState(failure?.code === 'token_expired' ? 'expired' : 'invalid');
      });
  }, [token]);

  if (state === 'verifying') {
    return (
      <AuthShell eyebrow="Account" title="Confirming your address">
        <div role="status" className="space-y-2">
          <span className="sr-only">Confirming…</span>
          <div className="h-4 w-2/3 animate-pulse bg-surface-2" />
          <div className="h-4 w-1/3 animate-pulse bg-surface-2" />
        </div>
      </AuthShell>
    );
  }

  if (state === 'done') {
    return (
      <AuthShell eyebrow="Account" title="Address confirmed">
        <Notice tone="success" title="That is everything">
          <p>
            Your email address is confirmed. Nothing else to do — the calculator worked
            before this and works the same now.
          </p>
        </Notice>
        <div className="mt-6">
          <button
            type="button"
            onClick={() => router.replace(status === 'authenticated' ? '/projects' : '/login?verified=1')}
            className="tap flex w-full items-center justify-center border border-solar bg-solar
              px-5 py-3 text-sm font-medium text-base transition-opacity hover:opacity-90"
          >
            {status === 'authenticated' ? 'Go to my estimates' : 'Sign in'}
          </button>
        </div>
      </AuthShell>
    );
  }

  if (state === 'expired') {
    return (
      <AuthShell eyebrow="Account" title="That link has expired">
        <div className="space-y-6">
          <Notice tone="error">{message}</Notice>
          <ResendForm defaultEmail={user?.email ?? ''} />
        </div>
      </AuthShell>
    );
  }

  if (state === 'invalid') {
    return (
      <AuthShell eyebrow="Account" title="That link is not valid">
        <div className="space-y-6">
          <Notice tone="error">
            <p>{message}</p>
            <p className="mt-2 text-ink-3">
              If you have already confirmed this address, you are all set and can ignore
              this.
            </p>
          </Notice>
          <ResendForm defaultEmail={user?.email ?? ''} />
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Account"
      title="Confirm your email"
      intro="Open the link in the message we sent. If it has been a while, ask for a fresh one."
      footer={
        <p>
          <Link href="/login" className="link-underline text-ink-1">
            Back to sign in
          </Link>
        </p>
      }
    >
      <ResendForm defaultEmail={user?.email ?? ''} />
    </AuthShell>
  );
}

/**
 * Ask for another confirmation link.
 *
 * Throttled server-side to one message every two minutes per address. A 429 here is a
 * normal outcome rather than an error, so it is shown as information — the user pressed a
 * button twice, which is not a fault.
 */
function ResendForm({ defaultEmail }: { defaultEmail: string }) {
  const [email, setEmail] = useState(defaultEmail);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ tone: 'info' | 'success' | 'error'; text: string } | null>(
    null,
  );

  useEffect(() => {
    if (defaultEmail) setEmail(defaultEmail);
  }, [defaultEmail]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const body = await auth.resendVerification(email);
      setResult({ tone: 'success', text: body.message });
    } catch (err) {
      const failure = err instanceof AuthError ? err : null;
      setResult({
        tone: failure?.status === 429 ? 'info' : 'error',
        text:
          failure?.remedy && failure.status === 429
            ? `${failure.message} ${failure.remedy}`
            : failure?.message ?? 'We could not send that link.',
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {result ? <Notice tone={result.tone}>{result.text}</Notice> : null}
      <Field
        label="Email"
        type="email"
        value={email}
        onChange={setEmail}
        autoComplete="email"
        placeholder="you@example.com"
        disabled={busy}
      />
      <SubmitButton busy={busy} disabled={!email}>
        Send a new link
      </SubmitButton>
    </form>
  );
}
