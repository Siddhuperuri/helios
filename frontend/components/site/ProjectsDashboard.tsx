'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { useSession } from '@/components/auth/SessionProvider';
import { Icon } from '@/components/site/Icon';
import { auth } from '@/lib/auth';
import { EstimateError, estimateApi, type EstimateSummary } from '@/lib/estimate';
import { formatEnergy } from '@/lib/i18n';

/**
 * The dashboard.
 *
 * This screen used to carry an apology. With no accounts there was no notion of "mine", so
 * it listed every estimate the server held and said so in a footnote: *on a shared
 * deployment, put sign-in in front of this page before relying on it for privacy*. That
 * has now happened, and the page is what the footnote was waiting for — the listing is
 * scoped to one account by the API, not by a filter here, and there is no parameter that
 * widens it.
 *
 * What has not changed is that reaching this page is optional. An estimate run without an
 * account still exists, still has its own link, and is still editable by whoever holds it.
 * The empty state says so rather than presenting the dashboard as the only way to keep a
 * result.
 */
export function ProjectsDashboard() {
  const router = useRouter();
  const { status, user } = useSession();

  const [projects, setProjects] = useState<EstimateSummary[] | null>(null);
  const [error, setError] = useState<EstimateError | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draftLabel, setDraftLabel] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [resent, setResent] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { estimates } = await estimateApi.list(50);
      setProjects(estimates);
    } catch (err) {
      // A 401 here means the silent refresh failed too, so the session is genuinely gone.
      // Sending the user to sign in is the useful response; showing an error is not.
      if (err instanceof EstimateError && err.status === 401) {
        router.replace('/login?redirect_to=%2Fprojects');
        return;
      }
      setError(
        err instanceof EstimateError
          ? err
          : new EstimateError('We could not load your saved estimates.', 500),
      );
      setProjects([]);
    }
  }, [router]);

  useEffect(() => {
    if (status === 'authenticated') void load();
  }, [status, load]);

  async function commitRename(id: string) {
    const label = draftLabel.trim();
    if (!label) {
      setRenaming(null);
      return;
    }
    setBusy(id);
    try {
      await estimateApi.rename(id, label);
      setProjects(
        (current) =>
          current?.map((project) =>
            project.estimate_id === id ? { ...project, label } : project,
          ) ?? null,
      );
    } catch {
      /* the name is cosmetic; a failure here must not lose the estimate */
    } finally {
      setBusy(null);
      setRenaming(null);
    }
  }

  async function remove(id: string, label: string) {
    if (!window.confirm(`Delete "${label}"? This cannot be undone.`)) return;
    setBusy(id);
    try {
      await estimateApi.remove(id);
      setProjects((current) => current?.filter((p) => p.estimate_id !== id) ?? null);
    } catch {
      setError(new EstimateError('That estimate could not be deleted.', 500));
    } finally {
      setBusy(null);
    }
  }

  /* ------------------------------------------------------------------ signed out */

  if (status === 'loading') {
    return (
      <div className="mx-auto max-w-[1180px] px-5 py-14 sm:px-8" role="status">
        <span className="sr-only">Loading…</span>
        <div className="h-8 w-64 animate-pulse bg-surface-2" />
        <div className="mt-10 space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse bg-surface-2" />
          ))}
        </div>
      </div>
    );
  }

  if (status === 'anonymous') {
    return <SignedOutState />;
  }

  /* ------------------------------------------------------------------- signed in */

  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 lg:py-14">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-4">Saved work</p>
          <h1 className="text-2xl font-medium tracking-tight text-ink-1 sm:text-3xl">
            My Solar Projects
          </h1>
        </div>
        <Link
          href="/start"
          className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5 py-3
            text-sm font-medium text-base transition-opacity hover:opacity-90"
        >
          New estimate
          <Icon name="arrow-right" size={16} />
        </Link>
      </div>

      {user && !user.is_verified ? (
        <VerificationBanner
          email={user.email}
          message={resent}
          onResend={async () => {
            try {
              const body = await auth.resendVerification(user.email);
              setResent(body.message);
            } catch {
              setResent('We could not send that link just now. Try again in a minute.');
            }
          }}
        />
      ) : null}

      {error ? (
        <div role="alert" className="mt-8 border border-critical/40 bg-critical/5 p-5">
          <p className="text-sm text-ink-1">{error.message}</p>
          {error.remedy ? <p className="mt-1.5 text-sm text-ink-2">{error.remedy}</p> : null}
          <button
            type="button"
            onClick={() => void load()}
            className="tap mt-4 border border-line-strong px-4 py-2 text-sm text-ink-1
              transition-colors hover:border-solar hover:text-solar"
          >
            Try again
          </button>
        </div>
      ) : null}

      {projects === null ? (
        <div className="mt-10 space-y-2" role="status">
          <span className="sr-only">Loading saved estimates…</span>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse bg-surface-2" />
          ))}
        </div>
      ) : projects.length === 0 && !error ? (
        <EmptyState />
      ) : (
        <ul className="mt-10 space-y-px bg-line">
          {projects.map((project) => {
            const annual = formatEnergy(project.annual_kwh);
            const isRenaming = renaming === project.estimate_id;

            return (
              <li key={project.estimate_id} className="bg-base">
                <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1">
                    {isRenaming ? (
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          void commitRename(project.estimate_id);
                        }}
                        className="flex flex-wrap gap-2"
                      >
                        <input
                          autoFocus
                          value={draftLabel}
                          onChange={(event) => setDraftLabel(event.target.value)}
                          aria-label="Estimate name"
                          maxLength={120}
                          className="min-w-0 flex-1 border border-line-strong bg-surface-1 px-3 py-2
                            text-sm text-ink-1 focus:border-solar focus:outline-none"
                        />
                        <button
                          type="submit"
                          className="border border-solar px-3 py-2 text-xs text-solar
                            transition-colors hover:bg-solar hover:text-base"
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          onClick={() => setRenaming(null)}
                          className="border border-line px-3 py-2 text-xs text-ink-2
                            transition-colors hover:text-ink-1"
                        >
                          Cancel
                        </button>
                      </form>
                    ) : (
                      <Link
                        href={`/result/${project.estimate_id}`}
                        className="block truncate text-base font-medium text-ink-1
                          transition-colors hover:text-solar"
                      >
                        {project.label}
                      </Link>
                    )}

                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
                      {project.location_label ? (
                        <span className="flex items-center gap-1.5">
                          <Icon name="map-pin" size={13} />
                          {project.location_label}
                        </span>
                      ) : null}
                      <span>
                        Updated{' '}
                        {new Date(project.updated_at).toLocaleDateString(undefined, {
                          day: 'numeric',
                          month: 'short',
                          year: 'numeric',
                        })}
                      </span>
                      {project.confidence ? (
                        <span className="capitalize">{project.confidence} confidence</span>
                      ) : null}
                    </p>
                  </div>

                  <dl className="flex shrink-0 gap-6">
                    <div>
                      <dt className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
                        Size
                      </dt>
                      <dd className="num mt-0.5 text-base text-ink-1">
                        {project.capacity_kwp ? `${project.capacity_kwp} kW` : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
                        Per year
                      </dt>
                      <dd className="num mt-0.5 text-base text-ink-1">
                        {project.annual_kwh ? `${annual.value} ${annual.unit}` : '—'}
                      </dd>
                    </div>
                    <div className="hidden sm:block">
                      <dt className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
                        Payback
                      </dt>
                      <dd className="num mt-0.5 text-base text-ink-1">
                        {project.payback_years ? `${project.payback_years} yr` : '—'}
                      </dd>
                    </div>
                  </dl>

                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      onClick={() => {
                        setRenaming(project.estimate_id);
                        setDraftLabel(project.label);
                      }}
                      disabled={busy === project.estimate_id}
                      aria-label={`Rename ${project.label}`}
                      className="tap flex items-center justify-center border border-line text-ink-3
                        transition-colors hover:border-line-bright hover:text-ink-1
                        disabled:opacity-50"
                    >
                      <Icon name="pencil" size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(project.estimate_id, project.label)}
                      disabled={busy === project.estimate_id}
                      aria-label={`Delete ${project.label}`}
                      className="tap flex items-center justify-center border border-line text-ink-3
                        transition-colors hover:border-critical hover:text-critical
                        disabled:opacity-50"
                    >
                      <Icon name="trash" size={16} />
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-8 max-w-2xl text-2xs leading-relaxed text-ink-4">
        Only your own estimates appear here. Each one also keeps its own link, which anyone
        you send it to can open without an account — but only you can rename, edit or delete
        it.
      </p>
    </div>
  );
}

/* ---------------------------------------------------------------------------- states */

function SignedOutState() {
  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 lg:py-14">
      <p className="eyebrow mb-4">Saved work</p>
      <h1 className="text-2xl font-medium tracking-tight text-ink-1 sm:text-3xl">
        My Solar Projects
      </h1>

      <div className="mt-10 max-w-2xl border border-line bg-surface-1 p-8">
        <h2 className="text-lg font-medium text-ink-1">Sign in to see your estimates here</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">
          An account collects your estimates in one place and lets you open them from any
          device. It is not required to use the calculator — every estimate you run gets its
          own link whether you have an account or not.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/login?redirect_to=%2Fprojects"
            className="tap inline-flex items-center gap-2 border border-solar bg-solar px-5 py-3
              text-sm font-medium text-base transition-opacity hover:opacity-90"
          >
            Sign in
          </Link>
          <Link
            href="/register?redirect_to=%2Fprojects"
            className="tap inline-flex items-center border border-line-strong px-5 py-3 text-sm
              text-ink-1 transition-colors hover:border-solar hover:text-solar"
          >
            Create an account
          </Link>
          <Link
            href="/start"
            className="tap inline-flex items-center gap-2 px-2 py-3 text-sm text-ink-2
              transition-colors hover:text-ink-1"
          >
            Or just run an estimate
            <Icon name="arrow-right" size={15} />
          </Link>
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mt-10 border border-line bg-surface-1 p-10 text-center">
      <h2 className="text-lg font-medium text-ink-1">Nothing saved yet</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-2">
        Estimates you run while signed in are collected here automatically. If you ran one
        before signing in, open its link and it can be added to your account.
      </p>
      <Link
        href="/start"
        className="tap mt-6 inline-flex items-center gap-2 border border-solar bg-solar px-5
          py-3 text-sm font-medium text-base transition-opacity hover:opacity-90"
      >
        Run your first estimate
        <Icon name="arrow-right" size={16} />
      </Link>
    </div>
  );
}

/**
 * The unverified-account notice.
 *
 * Unobtrusive on purpose: a border and a line of text, not a modal and not a blocking
 * interstitial. Nothing in the product is gated on verification, so a banner that behaved
 * as though something were would be lying about the consequence of ignoring it.
 */
function VerificationBanner({
  email,
  message,
  onResend,
}: {
  email: string;
  message: string | null;
  onResend: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);

  return (
    <div className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-2 border border-warning/40 bg-warning/5 px-4 py-3">
      <Icon name="info" size={16} className="shrink-0 text-warning" />
      <p className="min-w-0 flex-1 text-sm text-ink-2">
        {message ?? (
          <>
            Confirm <span className="text-ink-1">{email}</span> when you get a moment.
            Everything works without it — it just means we can reach you about your account.
          </>
        )}
      </p>
      {message ? null : (
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onResend();
            } finally {
              setBusy(false);
            }
          }}
          className="shrink-0 border border-line-strong px-3 py-1.5 text-xs text-ink-1
            transition-colors hover:border-solar hover:text-solar disabled:opacity-50"
        >
          {busy ? 'Sending…' : 'Resend link'}
        </button>
      )}
    </div>
  );
}
