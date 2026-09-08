'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { auth, onAuthChange, restoreSession, type AuthUser } from '@/lib/auth';

/**
 * Who is signed in, for the whole tree.
 *
 * `status` has three values and not two, because the difference between *loading* and
 * *signed out* is visible to the user. On first paint the access token is gone (it lived
 * in memory) and the refresh cookie has not been exchanged yet, so a component that only
 * distinguishes "user or no user" renders a **Sign in** link for a moment and then swaps
 * it for the account menu. That flicker on every page load looks like a bug, and it is the
 * single most common way this pattern is got wrong.
 */
export type SessionStatus = 'loading' | 'authenticated' | 'anonymous';

interface SessionValue {
  status: SessionStatus;
  user: AuthUser | null;
  /** Adopt a session the caller already obtained — a login form, or an OAuth exchange. */
  adopt: (user: AuthUser) => void;
  /** Ends this device's session. Resolves with whether the server confirmed it. */
  signOut: () => Promise<{ confirmed: boolean }>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionValue>({
  status: 'loading',
  user: null,
  adopt: () => undefined,
  signOut: async () => ({ confirmed: false }),
  refresh: async () => undefined,
});

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<SessionStatus>('loading');

  useEffect(() => {
    let cancelled = false;

    // The token did not survive the reload; the httpOnly refresh cookie did. This is what
    // turns "the browser remembers me" into a session.
    void restoreSession().then((restored) => {
      if (cancelled) return;
      setUser(restored);
      setStatus(restored ? 'authenticated' : 'anonymous');
    });

    // Anything that changes the session elsewhere — a silent refresh after a 401, a
    // password change, a sign-out — reports through here rather than each call site
    // having to remember to update React state.
    const unsubscribe = onAuthChange((next) => {
      if (cancelled) return;
      setUser(next);
      setStatus(next ? 'authenticated' : 'anonymous');
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const adopt = useCallback((next: AuthUser) => {
    setUser(next);
    setStatus('authenticated');
  }, []);

  const signOut = useCallback(async () => {
    const result = await auth.logout();
    setUser(null);
    setStatus('anonymous');
    return result;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const detail = await auth.me();
      setUser(detail.user);
      setStatus('authenticated');
    } catch {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const value = useMemo<SessionValue>(
    () => ({ status, user, adopt, signOut, refresh }),
    [status, user, adopt, signOut, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  return useContext(SessionContext);
}
