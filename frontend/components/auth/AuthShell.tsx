'use client';

import Link from 'next/link';
import { useEffect, useId, useState, type ReactElement, type ReactNode } from 'react';

import { Icon, Mark } from '@/components/site/Icon';
import { auth, AuthError } from '@/lib/auth';

/**
 * The shared furniture of the account screens.
 *
 * These pages are the one part of the product where the temptation to reach for a generic
 * SaaS template is strongest, and giving in would be obvious: the calculator is set in IBM
 * Plex on hairline rules with square corners and a single amber accent, and a rounded
 * card with a gradient button in the middle of it would read as a different product.
 *
 * So everything here is built from the primitives the rest of the site already uses — the
 * `eyebrow` rule, the hairline `panel`, the same input treatment as the interview, the
 * same square amber button as *Run my estimate*. Nothing new is invented. A person who
 * signs in should feel they never left.
 */

export function AuthShell({
  eyebrow,
  title,
  intro,
  children,
  footer,
}: {
  eyebrow: string;
  title: string;
  intro?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-[420px] px-5 py-12 sm:py-16">
      <Link
        href="/"
        className="mb-10 inline-flex items-center gap-2.5 text-ink-1 transition-colors hover:text-solar"
        aria-label="Helios — home"
      >
        <Mark size={22} />
        <span className="font-mono text-sm font-medium tracking-[0.06em]">Helios</span>
      </Link>

      <p className="eyebrow mb-4">{eyebrow}</p>
      <h1 className="text-2xl font-medium tracking-tight text-ink-1">{title}</h1>
      {intro ? (
        <div className="mt-2.5 text-sm leading-relaxed text-ink-2">{intro}</div>
      ) : null}

      <div className="mt-8">{children}</div>

      {footer ? (
        <div className="mt-8 border-t border-line pt-6 text-sm text-ink-2">{footer}</div>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------------------- field */

export function Field({
  label,
  type = 'text',
  value,
  onChange,
  autoComplete,
  placeholder,
  hint,
  error,
  required = true,
  autoFocus = false,
  disabled = false,
}: {
  label: string;
  type?: 'text' | 'email' | 'password';
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  placeholder?: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const [revealed, setRevealed] = useState(false);
  const isPassword = type === 'password';

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-ink-1">
        {label}
      </label>
      <div className="relative mt-2">
        <input
          id={id}
          // A reveal toggle has to change the input's type, which means this cannot be a
          // static `type`. Password managers handle the swap correctly; screen readers
          // announce it through the button's own label below.
          type={isPassword && revealed ? 'text' : type}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          required={required}
          autoFocus={autoFocus}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={[hint ? hintId : null, error ? errorId : null]
            .filter(Boolean)
            .join(' ') || undefined}
          className={`w-full border bg-surface-1 px-3 py-3 text-base text-ink-1
            placeholder:text-ink-4 focus:outline-none disabled:opacity-60
            ${isPassword ? 'pr-12' : ''}
            ${error ? 'border-critical' : 'border-line-strong focus:border-solar'}`}
        />
        {isPassword ? (
          <button
            type="button"
            onClick={() => setRevealed((current) => !current)}
            className="absolute right-0 top-0 flex h-full items-center px-3 text-xs text-ink-3
              transition-colors hover:text-ink-1"
            aria-label={revealed ? 'Hide password' : 'Show password'}
          >
            {revealed ? 'Hide' : 'Show'}
          </button>
        ) : null}
      </div>
      {hint ? (
        <p id={hintId} className="mt-1.5 text-xs leading-relaxed text-ink-3">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="mt-1.5 flex items-start gap-1.5 text-sm text-critical">
          <Icon name="alert" size={15} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- button */

export function SubmitButton({
  children,
  busy = false,
  disabled = false,
}: {
  children: ReactNode;
  busy?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="submit"
      disabled={busy || disabled}
      className="tap flex w-full items-center justify-center gap-2 border border-solar bg-solar
        px-5 py-3 text-sm font-medium text-base transition-opacity hover:opacity-90
        disabled:cursor-not-allowed disabled:opacity-55"
    >
      {busy ? 'Working…' : children}
    </button>
  );
}

/* --------------------------------------------------------------------------- alert */

export function Notice({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: 'info' | 'error' | 'success';
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  const toneClass = {
    info: 'border-steel/40 bg-steel/5',
    error: 'border-critical/40 bg-critical/5',
    success: 'border-positive/40 bg-positive/5',
  }[tone];
  const iconName = { info: 'info', error: 'alert', success: 'check' } as const;
  const iconClass = {
    info: 'text-steel',
    error: 'text-critical',
    success: 'text-positive',
  }[tone];

  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={`border p-4 ${toneClass}`}
    >
      <div className="flex gap-2.5">
        <Icon name={iconName[tone]} size={16} className={`mt-0.5 shrink-0 ${iconClass}`} />
        <div className="min-w-0 flex-1">
          {title ? <p className="text-sm font-medium text-ink-1">{title}</p> : null}
          <div className={`text-sm leading-relaxed text-ink-2 ${title ? 'mt-1' : ''}`}>
            {children}
          </div>
          {action ? <div className="mt-3">{action}</div> : null}
        </div>
      </div>
    </div>
  );
}

/**
 * Render whatever went wrong, using the words the backend chose.
 *
 * The API returns a message written for a person plus a remedy stating what to change, and
 * both are shown verbatim. Replacing them with "Something went wrong" throws away the only
 * part of the response that could help.
 */
export function ErrorNotice({ error }: { error: AuthError | null }) {
  if (!error) return null;
  return (
    <Notice tone="error">
      <p>{error.message}</p>
      {error.remedy ? <p className="mt-1 text-ink-3">{error.remedy}</p> : null}
    </Notice>
  );
}

/* ------------------------------------------------------------------------ providers */

/**
 * Brand marks for the identity providers.
 *
 * Deliberately not added to `Icon.tsx`. That set is schematic and internally consistent by
 * design; these are third-party trademarks whose whole purpose is to be recognised
 * exactly, so they cannot be redrawn to match and should not pretend to belong.
 */
function GoogleMark() {
  return (
    <svg viewBox="0 0 18 18" width="17" height="17" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

const MARKS: Record<string, () => ReactElement> = {
  google: GoogleMark,
  github: GitHubMark,
};

const LABELS: Record<string, string> = { google: 'Google', github: 'GitHub' };

/**
 * Provider buttons, rendered only for providers this deployment has configured.
 *
 * The list comes from the API rather than being hard-coded, so an instance without GitHub
 * credentials does not show a button that leads to a 503.
 */
export function ProviderButtons({
  redirectTo,
  verb = 'Continue with',
}: {
  redirectTo?: string;
  verb?: string;
}) {
  const [providers, setProviders] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    auth
      .providers()
      .then(({ providers: available }) => {
        if (!cancelled) setProviders(available);
      })
      .catch(() => {
        // Not being able to list providers is not worth an error message on a sign-in
        // page: the email and password form below still works.
        if (!cancelled) setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (providers === null) {
    return <div className="h-[46px] animate-pulse bg-surface-2" aria-hidden="true" />;
  }
  if (providers.length === 0) return null;

  return (
    <div className="space-y-2.5">
      {providers.map((provider) => {
        const Mark = MARKS[provider];
        return (
          <a
            key={provider}
            href={auth.oauthUrl(provider, { redirectTo })}
            className="tap flex w-full items-center justify-center gap-2.5 border border-line-strong
              bg-surface-1 px-5 py-3 text-sm font-medium text-ink-1 transition-colors
              hover:border-line-bright hover:bg-surface-2"
          >
            {Mark ? <Mark /> : null}
            {verb} {LABELS[provider] ?? provider}
          </a>
        );
      })}
    </div>
  );
}

export function Divider({ label = 'or' }: { label?: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-px flex-1 bg-line" />
      <span className="font-mono text-2xs uppercase tracking-[0.12em] text-ink-4">
        {label}
      </span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}
