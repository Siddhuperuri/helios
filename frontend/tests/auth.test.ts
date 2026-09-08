/**
 * The session client's behaviour under failure.
 *
 * These test the three things that are easy to get wrong and expensive when wrong: the
 * access token must never be written to storage, an expired token must produce exactly one
 * refresh no matter how many requests noticed, and a failed refresh must stop rather than
 * loop. Everything else in `lib/auth.ts` is a thin wrapper over `fetch` and is covered by
 * the backend's own tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  auth,
  authedFetch,
  clearSession,
  getAccessToken,
  refreshSession,
} from '@/lib/auth';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const SESSION = {
  access_token: 'access-token-1',
  token_type: 'bearer',
  expires_in: 900,
  csrf_token: 'csrf-1.signature',
  user: {
    id: 'user-1',
    email: 'someone@example.com',
    display_name: null,
    is_active: true,
    is_verified: false,
    has_password: true,
    created_at: '2026-01-01T00:00:00Z',
    last_login_at: null,
    providers: [],
  },
};

describe('session storage', () => {
  beforeEach(() => {
    clearSession();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearSession();
  });

  it('keeps the access token out of localStorage and sessionStorage', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(SESSION)),
    );

    await auth.login('someone@example.com', 'a-long-enough-password');

    expect(getAccessToken()).toBe('access-token-1');

    // The whole point: a compromised dependency can read storage, and a token there
    // outlives the tab it was stolen from.
    const stored = [
      ...Object.values(window.localStorage),
      ...Object.values(window.sessionStorage),
    ].join('|');
    expect(stored).not.toContain('access-token-1');
  });

  it('sends the access token as a bearer header once signed in', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SESSION));
    vi.stubGlobal('fetch', fetchMock);

    await auth.login('someone@example.com', 'a-long-enough-password');
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await authedFetch('/api/estimates');

    const [, init] = fetchMock.mock.calls.at(-1)!;
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get('Authorization')).toBe('Bearer access-token-1');
    // Required for the httpOnly refresh cookie to travel at all.
    expect((init as RequestInit).credentials).toBe('include');
  });

  it('clears the token on sign-out even when the request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(SESSION)));
    await auth.login('someone@example.com', 'a-long-enough-password');

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    await auth.logout();

    // A user who pressed "sign out" must not still look signed in because the network
    // was down.
    expect(getAccessToken()).toBeNull();
  });
});

describe('silent refresh', () => {
  beforeEach(() => {
    clearSession();
    vi.restoreAllMocks();
    // The presence of a CSRF cookie is what tells the client a session cookie exists.
    document.cookie = 'helios_csrf=csrf-1.signature; path=/';
  });

  it('does not call the server at all when there is no session cookie', async () => {
    // Every cold page load by a signed-out visitor would otherwise POST to /refresh, get a
    // 403 for having no CSRF token, and log a CSRF failure server-side — burying the real
    // ones under a steady stream of false alarms.
    document.cookie = 'helios_csrf=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(refreshSession()).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refreshes once when several requests see a 401 together', async () => {
    // The failure this prevents is not merely wasted requests. Parallel refreshes present
    // a refresh token that the first one has already rotated away, which the backend
    // correctly reads as token theft — and responds to by revoking every session.
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith('/api/auth/refresh')) {
        refreshCalls += 1;
        // Deliberately slow, so the other callers arrive while this is in flight.
        await new Promise((resolve) => setTimeout(resolve, 20));
        return jsonResponse(SESSION);
      }
      return jsonResponse({ error: 'token_expired' }, 401);
    });
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    await Promise.all([
      refreshSession(),
      refreshSession(),
      refreshSession(),
      refreshSession(),
    ]);

    expect(refreshCalls).toBe(1);
  });

  it('retries the original request exactly once after a successful refresh', async () => {
    const calls: string[] = [];
    let refreshed = false;
    const fetchMock = vi.fn(async (url: string) => {
      const path = String(url);
      calls.push(path);
      if (path.endsWith('/api/auth/refresh')) {
        refreshed = true;
        return jsonResponse(SESSION);
      }
      return refreshed ? jsonResponse({ ok: true }) : jsonResponse({}, 401);
    });
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const response = await authedFetch('/api/estimates');

    expect(response.status).toBe(200);
    expect(calls).toEqual([
      '/api/estimates',
      '/api/auth/refresh',
      '/api/estimates',
    ]);
  });

  it('does not loop when the refresh itself fails', async () => {
    let attempts = 0;
    const fetchMock = vi.fn(async () => {
      attempts += 1;
      return jsonResponse({ error: 'token_invalid' }, 401);
    });
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const response = await authedFetch('/api/estimates');

    expect(response.status).toBe(401);
    // The original request and one refresh attempt. Nothing more: a server that answers
    // 401 to everything must not produce an infinite retry.
    expect(attempts).toBe(2);
    expect(getAccessToken()).toBeNull();
  });

  it('gives up quietly when the network is down rather than clearing a valid session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(SESSION)));
    await auth.login('someone@example.com', 'a-long-enough-password');

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const ok = await refreshSession();

    expect(ok).toBe(false);
    // Being offline is not evidence that the session is invalid, so the token survives
    // and the next call tries again.
    expect(getAccessToken()).toBe('access-token-1');
  });
});

describe('registration', () => {
  beforeEach(() => {
    clearSession();
    vi.restoreAllMocks();
  });

  it('registers and then logs in, because registration returns no session', async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      calls.push(String(url));
      return String(url).endsWith('/api/auth/register')
        ? jsonResponse({ registered: true, message: 'Check your email.' })
        : jsonResponse(SESSION);
    });
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const session = await auth.register('someone@example.com', 'a-long-enough-password');

    expect(calls).toEqual(['/api/auth/register', '/api/auth/login']);
    expect(session.user.email).toBe('someone@example.com');
  });
});

describe('csrf', () => {
  beforeEach(() => {
    clearSession();
    vi.restoreAllMocks();
    document.cookie = 'helios_csrf=token-from-cookie.sig; path=/';
  });

  it('echoes the CSRF cookie rather than a token remembered from login', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SESSION));
    vi.stubGlobal('fetch', fetchMock);

    await refreshSession();

    const [, init] = fetchMock.mock.calls.at(-1)!;
    const headers = new Headers((init as RequestInit).headers);
    // The server reissues the CSRF token on every rotation, so a client that kept sending
    // the one it got at login would start failing after its first refresh.
    expect(headers.get('X-CSRF-Token')).toBe('token-from-cookie.sig');
  });
});
