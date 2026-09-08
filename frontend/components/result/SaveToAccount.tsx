'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

import { useSession } from '@/components/auth/SessionProvider';
import { Icon } from '@/components/site/Icon';
import { auth, AuthError } from '@/lib/auth';

/**
 * Offer to attach an anonymous estimate to an account.
 *
 * This is the moment the whole optional-accounts design exists for. Somebody ran an
 * estimate without signing up, which the product actively encourages, and now has a result
 * worth keeping. Asking here — after the value has been delivered, on a result they are
 * already looking at — is the honest version of the prompt. Asking before the estimate ran
 * would have been a signup wall wearing a different hat.
 *
 * It appears only for estimates that have no owner. An estimate that already belongs to
 * somebody shows nothing, because offering to claim it would suggest that holding the link
 * is enough to take it — and it is not.
 */
export function SaveToAccount({
  estimateId,
  owned,
  onClaimed,
}: {
  estimateId: string;
  owned: boolean;
  onClaimed?: () => void;
}) {
  const pathname = usePathname();
  const { status } = useSession();
  const [state, setState] = useState<'idle' | 'busy' | 'done'>('idle');
  const [error, setError] = useState<string | null>(null);

  // Already someone's. Nothing to offer, and nothing to say about whose it is.
  if (owned) return null;
  if (status === 'loading') return null;

  if (state === 'done') {
    return (
      <div className="mt-8 flex items-center gap-2.5 border border-positive/40 bg-positive/5 px-4 py-3">
        <Icon name="check" size={16} className="shrink-0 text-positive" />
        <p className="text-sm text-ink-2">
          Saved to your account.{' '}
          <Link href="/projects" className="link-underline text-ink-1">
            See all your estimates
          </Link>
          .
        </p>
      </div>
    );
  }

  async function claim() {
    setState('busy');
    setError(null);
    try {
      await auth.claimEstimate(estimateId);
      setState('done');
      onClaimed?.();
    } catch (err) {
      setError(
        err instanceof AuthError ? err.message : 'We could not add that to your account.',
      );
      setState('idle');
    }
  }

  return (
    <div className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-3 border border-line bg-surface-1 px-4 py-3.5">
      <Icon name="info" size={16} className="shrink-0 text-steel" />
      <p className="min-w-0 flex-1 text-sm leading-relaxed text-ink-2">
        {status === 'authenticated'
          ? 'This estimate is not attached to your account yet. Add it and it will appear in your list on any device.'
          : 'Keep this estimate. The link works on its own, but an account collects your estimates in one place and opens them anywhere.'}
        {error ? <span className="mt-1 block text-critical">{error}</span> : null}
      </p>

      {status === 'authenticated' ? (
        <button
          type="button"
          onClick={() => void claim()}
          disabled={state === 'busy'}
          className="tap shrink-0 border border-solar px-4 py-2 text-xs font-medium text-solar
            transition-colors hover:bg-solar hover:text-base disabled:opacity-50"
        >
          {state === 'busy' ? 'Saving…' : 'Save to my account'}
        </button>
      ) : (
        <div className="flex shrink-0 flex-wrap gap-2">
          {/*
            The redirect brings them straight back here, so signing in does not cost them
            the result they were reading. Without it this prompt would be asking somebody
            to leave the page in order to keep the page.
          */}
          <Link
            href={`/register?redirect_to=${encodeURIComponent(pathname)}`}
            className="tap border border-solar px-4 py-2 text-xs font-medium text-solar
              transition-colors hover:bg-solar hover:text-base"
          >
            Create an account
          </Link>
          <Link
            href={`/login?redirect_to=${encodeURIComponent(pathname)}`}
            className="tap border border-line px-4 py-2 text-xs text-ink-2 transition-colors
              hover:border-line-bright hover:text-ink-1"
          >
            Sign in
          </Link>
        </div>
      )}
    </div>
  );
}
