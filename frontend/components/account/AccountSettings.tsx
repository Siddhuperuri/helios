'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { Field, Notice, SubmitButton } from '@/components/auth/AuthShell';
import { useSession } from '@/components/auth/SessionProvider';
import { Icon } from '@/components/site/Icon';
import { auth, AuthError, type AccountDetail } from '@/lib/auth';

const MIN_PASSWORD_LENGTH = 10;
const PROVIDER_LABELS: Record<string, string> = { google: 'Google', github: 'GitHub' };

/**
 * Account settings.
 *
 * Four things, in the order somebody actually needs them: what this account is, whether
 * the address is confirmed, the password, and the connected sign-in providers. Nothing
 * else — there is no usage chart, no plan, no activity feed, because none of those exist
 * and inventing them would be padding a settings page with fiction.
 *
 * The one screen in the product where a destructive action is genuinely available is the
 * provider list, so that is where the care goes: disconnecting the last way into an
 * account is refused by the API, and this page explains why *before* the attempt rather
 * than reporting an error after it.
 */
export function AccountSettings() {
  const router = useRouter();
  const { status, user, signOut } = useSession();

  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [error, setError] = useState<AuthError | null>(null);

  const load = useCallback(async () => {
    try {
      setDetail(await auth.me());
      setError(null);
    } catch (err) {
      if (err instanceof AuthError && err.status === 401) return;
      setError(
        err instanceof AuthError ? err : new AuthError('We could not load your account.', 0),
      );
    }
  }, []);

  useEffect(() => {
    if (status === 'anonymous') {
      router.replace('/login?redirect_to=%2Faccount');
      return;
    }
    if (status === 'authenticated') void load();
  }, [status, load, router]);

  if (status === 'loading' || (!detail && !error)) {
    return (
      <div className="mx-auto max-w-[720px] px-5 py-12 sm:px-8" role="status">
        <span className="sr-only">Loading your account…</span>
        <div className="h-8 w-48 animate-pulse bg-surface-2" />
        <div className="mt-8 space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse bg-surface-2" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[720px] px-5 py-10 sm:px-8 lg:py-14">
      <p className="eyebrow mb-4">Account</p>
      <h1 className="text-2xl font-medium tracking-tight text-ink-1 sm:text-3xl">Settings</h1>

      {error ? (
        <div className="mt-8">
          <Notice tone="error">{error.message}</Notice>
        </div>
      ) : null}

      {detail ? (
        <div className="mt-10 space-y-12">
          <IdentitySection detail={detail} onChanged={load} />
          <PasswordSection detail={detail} />
          <ProvidersSection detail={detail} onChanged={load} />
          <SessionSection
            onSignOut={async () => {
              const { confirmed } = await signOut();
              if (!confirmed) return false;
              router.replace('/');
              return true;
            }}
          />
        </div>
      ) : null}

      {user ? (
        <p className="mt-12 text-2xs leading-relaxed text-ink-4">
          Deleting an account is not self-service yet. If you ask us to remove one, your
          saved estimates are not destroyed with it — they revert to being reachable only by
          their own links, so a link you have already sent to an installer keeps working.
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------------- identity */

function IdentitySection({
  detail,
  onChanged,
}: {
  detail: AccountDetail;
  onChanged: () => Promise<void>;
}) {
  const [name, setName] = useState(detail.user.display_name ?? '');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resent, setResent] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSaved(false);
    try {
      await auth.updateProfile(name.trim() || null);
      setSaved(true);
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    try {
      const body = await auth.resendVerification(detail.user.email);
      setResent(body.message);
    } catch (err) {
      setResent(
        err instanceof AuthError
          ? `${err.message}${err.remedy ? ` ${err.remedy}` : ''}`
          : 'We could not send that link.',
      );
    }
  }

  return (
    <section>
      <p className="eyebrow mb-4">Who you are</p>

      <dl className="border border-line bg-surface-1">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line p-4">
          <dt className="w-32 shrink-0 font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
            Email
          </dt>
          <dd className="min-w-0 flex-1 break-all text-sm text-ink-1">{detail.user.email}</dd>
          <dd className="shrink-0">
            {detail.user.is_verified ? (
              <span className="tag border-positive/40 text-positive">
                <Icon name="check" size={12} />
                Confirmed
              </span>
            ) : (
              <span className="tag border-warning/40 text-warning">Unconfirmed</span>
            )}
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line p-4">
          <dt className="w-32 shrink-0 font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
            Member since
          </dt>
          <dd className="text-sm text-ink-2">
            {detail.user.created_at
              ? new Date(detail.user.created_at).toLocaleDateString(undefined, {
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric',
                })
              : '—'}
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 p-4">
          <dt className="w-32 shrink-0 font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
            Estimates
          </dt>
          <dd className="text-sm text-ink-2">
            {detail.estimate_count === 0 ? (
              <Link href="/start" className="link-underline text-ink-1">
                None yet — run one
              </Link>
            ) : (
              <Link href="/projects" className="link-underline text-ink-1">
                {detail.estimate_count} saved
              </Link>
            )}
          </dd>
        </div>
      </dl>

      {!detail.user.is_verified ? (
        <div className="mt-4">
          <Notice tone="info" title="Your address is not confirmed yet">
            <p>
              Nothing is blocked by this — the calculator, saving estimates and the analysis
              console all work. It matters only so we can reach you about your account.
            </p>
            {resent ? (
              <p className="mt-2 text-ink-1">{resent}</p>
            ) : (
              <button
                type="button"
                onClick={() => void resend()}
                className="mt-3 border border-line-strong px-3 py-2 text-xs text-ink-1
                  transition-colors hover:border-solar hover:text-solar"
              >
                Send a new confirmation link
              </button>
            )}
          </Notice>
        </div>
      ) : null}

      <form onSubmit={save} className="mt-6 space-y-4">
        <Field
          label="Display name"
          value={name}
          onChange={setName}
          required={false}
          autoComplete="name"
          placeholder="Optional"
          hint="Only shown to you. Estimates are labelled by location, not by name."
          disabled={busy}
        />
        {saved ? <Notice tone="success">Saved.</Notice> : null}
        <div className="max-w-[200px]">
          <SubmitButton busy={busy}>Save</SubmitButton>
        </div>
      </form>
    </section>
  );
}

/* ------------------------------------------------------------------------- password */

function PasswordSection({ detail }: { detail: AccountDetail }) {
  const hasPassword = detail.user.has_password;
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<AuthError | null>(null);

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD_LENGTH;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const body = await auth.changePassword(hasPassword ? current : null, next);
      setDone(body.message);
      setCurrent('');
      setNext('');
    } catch (err) {
      setError(
        err instanceof AuthError ? err : new AuthError('We could not change that.', 0),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <p className="eyebrow mb-4">Password</p>
      <p className="mb-5 max-w-prose text-sm leading-relaxed text-ink-2">
        {hasPassword
          ? 'Changing your password signs you out on every other device. This one stays signed in.'
          : 'You signed up with a connected account, so there is no password yet. Setting one gives you a second way in — and it is what lets you disconnect a provider later.'}
      </p>

      <form onSubmit={submit} className="max-w-[420px] space-y-5">
        {done ? <Notice tone="success">{done}</Notice> : null}
        {error ? (
          <Notice tone="error">
            <p>{error.message}</p>
            {error.remedy ? <p className="mt-1 text-ink-3">{error.remedy}</p> : null}
          </Notice>
        ) : null}

        {hasPassword ? (
          <Field
            label="Current password"
            type="password"
            value={current}
            onChange={setCurrent}
            autoComplete="current-password"
            disabled={busy}
          />
        ) : null}
        <Field
          label={hasPassword ? 'New password' : 'Set a password'}
          type="password"
          value={next}
          onChange={setNext}
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          error={tooShort ? `A few more characters — ${MIN_PASSWORD_LENGTH} at minimum.` : null}
          disabled={busy}
        />
        <div className="max-w-[240px]">
          <SubmitButton busy={busy} disabled={tooShort || !next || (hasPassword && !current)}>
            {hasPassword ? 'Change password' : 'Set password'}
          </SubmitButton>
        </div>
      </form>
    </section>
  );
}

/* ------------------------------------------------------------------------ providers */

function ProvidersSection({
  detail,
  onChanged,
}: {
  detail: AccountDetail;
  onChanged: () => Promise<void>;
}) {
  const [available, setAvailable] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<AuthError | null>(null);

  useEffect(() => {
    auth
      .providers()
      .then(({ providers }) => setAvailable(providers))
      .catch(() => setAvailable([]));
  }, []);

  const linked = new Map(detail.oauth_accounts.map((a) => [a.provider, a]));
  // The API refuses to remove the last way in. Knowing that here means the button can
  // explain itself instead of failing.
  const isLastMethod = detail.authentication_methods <= 1;

  async function unlink(provider: string) {
    setBusy(provider);
    setError(null);
    try {
      await auth.unlinkProvider(provider);
      await onChanged();
    } catch (err) {
      setError(
        err instanceof AuthError ? err : new AuthError('We could not disconnect that.', 0),
      );
    } finally {
      setBusy(null);
    }
  }

  if (available.length === 0) return null;

  return (
    <section>
      <p className="eyebrow mb-4">Connected accounts</p>
      <p className="mb-5 max-w-prose text-sm leading-relaxed text-ink-2">
        Connecting an account gives you another way to sign in. We never link one
        automatically, even when the email addresses match — the connection has to be made
        from here, by someone already signed in.
      </p>

      {error ? (
        <div className="mb-5">
          <Notice tone="error">
            <p>{error.message}</p>
            {error.remedy ? <p className="mt-1 text-ink-3">{error.remedy}</p> : null}
          </Notice>
        </div>
      ) : null}

      <ul className="space-y-px bg-line">
        {available.map((provider) => {
          const account = linked.get(provider);
          const label = PROVIDER_LABELS[provider] ?? provider;
          const blocked = Boolean(account) && isLastMethod;

          return (
            <li key={provider} className="flex flex-wrap items-center gap-4 bg-surface-1 p-4">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink-1">{label}</p>
                <p className="mt-0.5 truncate text-xs text-ink-3">
                  {account
                    ? `Connected${account.provider_email ? ` as ${account.provider_email}` : ''}`
                    : 'Not connected'}
                </p>
              </div>

              {account ? (
                <div className="flex flex-col items-end gap-1.5">
                  <button
                    type="button"
                    onClick={() => void unlink(provider)}
                    disabled={busy === provider || blocked}
                    aria-describedby={blocked ? `${provider}-blocked` : undefined}
                    className="tap border border-line px-4 py-2 text-xs text-ink-2 transition-colors
                      hover:border-critical hover:text-critical disabled:cursor-not-allowed
                      disabled:opacity-50 disabled:hover:border-line disabled:hover:text-ink-2"
                  >
                    Disconnect
                  </button>
                  {blocked ? (
                    <p id={`${provider}-blocked`} className="max-w-[220px] text-right text-2xs leading-relaxed text-ink-4">
                      This is currently your only way to sign in. Set a password first.
                    </p>
                  ) : null}
                </div>
              ) : (
                <a
                  href={auth.oauthUrl(provider, { link: true, redirectTo: '/account' })}
                  className="tap border border-line-strong px-4 py-2 text-xs text-ink-1
                    transition-colors hover:border-solar hover:text-solar"
                >
                  Connect
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* -------------------------------------------------------------------------- session */

function SessionSection({ onSignOut }: { onSignOut: () => Promise<boolean> }) {
  const [busy, setBusy] = useState<'one' | 'all' | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);

  return (
    <section>
      <p className="eyebrow mb-4">Sessions</p>

      {unconfirmed ? (
        <div className="mb-4">
          <Notice tone="error" title="Signed out here, but not on the server">
            <p>
              We could not reach the server to end the session, so it is still valid and
              this browser may sign back in on its own. Try again when you have a
              connection — or use <span className="text-ink-1">Sign out everywhere</span>,
              which is what you want if you are worried about who else has access.
            </p>
          </Notice>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={async () => {
            setBusy('one');
            const ok = await onSignOut();
            if (!ok) {
              setUnconfirmed(true);
              setBusy(null);
            }
          }}
          disabled={busy !== null}
          className="tap border border-line-strong px-5 py-3 text-sm text-ink-1 transition-colors
            hover:border-solar hover:text-solar disabled:opacity-50"
        >
          Sign out
        </button>
        <button
          type="button"
          onClick={async () => {
            setBusy('all');
            const { confirmed } = await auth.logoutEverywhere();
            const ok = await onSignOut();
            if (!confirmed || !ok) {
              setUnconfirmed(true);
              setBusy(null);
            }
          }}
          disabled={busy !== null}
          className="tap border border-line px-5 py-3 text-sm text-ink-2 transition-colors
            hover:border-critical hover:text-critical disabled:opacity-50"
        >
          Sign out everywhere
        </button>
      </div>
      <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-3">
        <span className="text-ink-2">Sign out</span> ends this device&apos;s session only —
        signing out on a borrowed computer should not sign out your phone.{' '}
        <span className="text-ink-2">Sign out everywhere</span> ends all of them, which is
        what you want if you think somebody else has access.
      </p>
    </section>
  );
}
