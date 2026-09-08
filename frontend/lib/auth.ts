/**
 * The session client.
 *
 * Three decisions here, each of which has a wrong answer that is easier to write.
 *
 * **The access token lives in memory, never in `localStorage`.** Anything in
 * `localStorage` is readable by every script on the page, so one compromised dependency
 * is one stolen session that survives until the token expires. Keeping it in a module
 * variable means a page reload loses it — which is fine, because the refresh cookie is
 * httpOnly, survives the reload, and mints a new one. The cookie is the durable half; the
 * token is the disposable half.
 *
 * **A 401 triggers exactly one refresh, no matter how many requests saw it.** A results
 * page fires half a dozen calls at once. Without care, an expired token means six parallel
 * refreshes, five of which present a refresh token that the first one has already rotated
 * away — which the backend correctly reads as token theft and responds to by revoking every
 * session on the account. So the refresh is single-flight: the first caller starts it, the
 * rest await the same promise.
 *
 * **A failed refresh clears the session and stops.** It does not retry, and it does not
 * redirect from here. Redirecting inside a fetch helper is how a background poll on a
 * public page throws the reader out of an article they were happily reading; the decision
 * of whether a 401 deserves a redirect belongs to the screen that made the call.
 */

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  has_password: boolean;
  created_at: string | null;
  last_login_at: string | null;
  providers: string[];
}

export interface OAuthAccountDto {
  provider: string;
  provider_account_id: string;
  provider_email: string | null;
  provider_username: string | null;
  linked_at: string | null;
}

export interface SessionPayload {
  access_token: string;
  token_type: string;
  expires_in: number;
  csrf_token: string;
  user: AuthUser;
}

export interface AccountDetail {
  user: AuthUser;
  oauth_accounts: OAuthAccountDto[];
  authentication_methods: number;
  estimate_count: number;
}

/**
 * Errors carry the backend's machine-readable code alongside its human message.
 *
 * The code is what the interface branches on — `token_expired` gets a "send me another
 * one" button, `token_invalid` does not — and the message is what it shows. Collapsing
 * both into a string would force the UI to match on prose.
 */
export class AuthError extends Error {
  readonly status: number;
  readonly code: string;
  readonly remedy?: string;
  readonly fieldErrors?: { field: string; message: string }[];

  constructor(
    message: string,
    status: number,
    code = 'error',
    remedy?: string,
    fieldErrors?: { field: string; message: string }[],
  ) {
    super(message);
    this.name = 'AuthError';
    this.status = status;
    this.code = code;
    this.remedy = remedy;
    this.fieldErrors = fieldErrors;
  }
}

/* ------------------------------------------------------------------ token state */

let accessToken: string | null = null;
let currentUser: AuthUser | null = null;
let refreshInFlight: Promise<boolean> | null = null;

type Listener = (user: AuthUser | null) => void;
const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener(currentUser);
}

/** Subscribe to sign-in and sign-out. Returns an unsubscribe function. */
export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getCurrentUser(): AuthUser | null {
  return currentUser;
}

function setSession(payload: SessionPayload): SessionPayload {
  accessToken = payload.access_token;
  currentUser = payload.user;
  notify();
  return payload;
}

export function clearSession(): void {
  accessToken = null;
  currentUser = null;
  notify();
}

/**
 * The CSRF token, read from the cookie the server set.
 *
 * Deliberately read from the cookie rather than remembered from the login response: the
 * server reissues it alongside every refresh-token rotation, and a client that keeps
 * echoing the token it got at login starts failing after its first refresh.
 */
function csrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)helios_csrf=([^;]*)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

/* ----------------------------------------------------------------------- fetch */

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').replace(/\/$/, '');

async function parseError(response: Response): Promise<AuthError> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    return new AuthError(
      (body.message as string) ?? 'That did not work.',
      response.status,
      (body.error as string) ?? 'error',
      body.remedy as string | undefined,
      body.field_errors as { field: string; message: string }[] | undefined,
    );
  }
  return new AuthError('That did not work.', response.status);
}

interface RequestOptions extends RequestInit {
  /** Attach the access token. Off for the endpoints that establish a session. */
  auth?: boolean;
  /** Attach the CSRF header. On for the two endpoints that authenticate by cookie. */
  csrf?: boolean;
  /** Internal: prevents a refreshed request from trying to refresh again. */
  retry?: boolean;
  timeoutMs?: number;
}

async function rawRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const { auth = false, csrf = false, timeoutMs = 30_000, retry, ...init } = options;

  const headers = new Headers(init.headers);
  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (auth && accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  if (csrf) {
    const token = csrfToken();
    if (token) headers.set('X-CSRF-Token', token);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      // Required for the refresh cookie to travel at all.
      credentials: 'include',
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Attempt a silent refresh. Returns whether a session is now in hand.
 *
 * Single-flight: concurrent callers share one in-flight promise. See the module docstring
 * for why parallel refreshes are actively harmful rather than merely wasteful.
 */
export function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  // No CSRF cookie means no session cookie either — the two are set together, with the
  // same lifetime, and only ever cleared together. The refresh cookie itself is httpOnly
  // and cannot be checked from here, so this is the readable half of the pair standing in
  // for it.
  //
  // Skipping the call matters for more than a saved round trip. Without this, every cold
  // page load by a signed-out visitor POSTs to /api/auth/refresh, gets a 403 because there
  // is no CSRF token to submit, and logs a CSRF failure on the server. That would put a
  // steady stream of false CSRF warnings into the logs of the busiest path in the product
  // — and a genuine CSRF failure, which is worth alerting on, would be indistinguishable
  // from the background noise.
  if (!csrfToken()) {
    clearSession();
    return Promise.resolve(false);
  }

  refreshInFlight = (async () => {
    try {
      const response = await rawRequest('/api/auth/refresh', {
        method: 'POST',
        csrf: true,
        timeoutMs: 15_000,
      });
      if (!response.ok) {
        clearSession();
        return false;
      }
      setSession((await response.json()) as SessionPayload);
      return true;
    } catch {
      // Offline, or the request was aborted. Not evidence that the session is invalid, so
      // the token is left alone; the next call will try again.
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/**
 * An authenticated request, with one silent refresh-and-retry on 401.
 *
 * The retry happens at most once per call — `retry: true` on the second attempt is what
 * stops a server that returns 401 to everything from producing an infinite loop.
 */
export async function authedFetch(
  path: string,
  options: RequestOptions = {},
): Promise<Response> {
  const response = await rawRequest(path, { ...options, auth: true });

  if (response.status !== 401 || options.retry) return response;

  const refreshed = await refreshSession();
  if (!refreshed) return response;

  return rawRequest(path, { ...options, auth: true, retry: true });
}

async function json<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = options.auth
      ? await authedFetch(path, options)
      : await rawRequest(path, options);
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === 'AbortError';
    throw new AuthError(
      aborted ? 'That took too long.' : 'We could not reach the server.',
      0,
      'network_error',
      'Check your connection and try again.',
    );
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* --------------------------------------------------------------------- the API */

export const auth = {
  /**
   * Create an account, then sign in.
   *
   * Two calls, and deliberately so: registration returns no session, because a response
   * that carried a token for a new address and no token for an existing one would tell an
   * attacker which addresses are registered. Signing in immediately afterwards restores
   * the single-step experience without the oracle. See `app/auth/routes.py::register`.
   */
  async register(email: string, password: string): Promise<SessionPayload> {
    await json<{ message: string }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    return auth.login(email, password);
  },

  async login(email: string, password: string): Promise<SessionPayload> {
    const payload = await json<SessionPayload>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    return setSession(payload);
  },

  /**
   * End this device's session. Never throws.
   *
   * Returns whether the *server* confirmed it. That distinction is not pedantic. Local
   * state is cleared either way, because a user who pressed "sign out" must not still look
   * signed in — but if the request never landed, the refresh cookie is still in the browser
   * and the refresh token is still valid, so the next page load would silently restore the
   * session. The caller is told so it can say so, rather than the interface quietly
   * claiming something that did not happen.
   */
  async logout(): Promise<{ confirmed: boolean }> {
    let confirmed = false;
    try {
      const response = await rawRequest('/api/auth/logout', { method: 'POST', csrf: true });
      confirmed = response.ok;
    } catch {
      confirmed = false;
    } finally {
      clearSession();
    }
    return { confirmed };
  },

  async logoutEverywhere(): Promise<{ confirmed: boolean }> {
    let confirmed = false;
    try {
      const response = await authedFetch('/api/auth/logout-all', { method: 'POST' });
      confirmed = response.ok;
    } catch {
      confirmed = false;
    } finally {
      clearSession();
    }
    return { confirmed };
  },

  me: () => json<AccountDetail>('/api/auth/me', { auth: true }),

  updateProfile: (displayName: string | null) =>
    json<{ user: AuthUser }>('/api/auth/me', {
      method: 'PATCH',
      auth: true,
      body: JSON.stringify({ display_name: displayName }),
    }).then((body) => {
      currentUser = body.user;
      notify();
      return body.user;
    }),

  verifyEmail: (token: string) =>
    json<{ verified: boolean; already_verified: boolean; user: AuthUser }>(
      '/api/auth/verify-email',
      { method: 'POST', body: JSON.stringify({ token }) },
    ).then((body) => {
      // The signed-in user's verified flag is stale until their next refresh; update the
      // local copy so the banner disappears immediately.
      if (currentUser && currentUser.id === body.user.id) {
        currentUser = body.user;
        notify();
      }
      return body;
    }),

  resendVerification: (email: string) =>
    json<{ sent: boolean; message: string }>('/api/auth/resend-verification', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  forgotPassword: (email: string) =>
    json<{ sent: boolean; message: string }>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  resetPassword: (token: string, password: string) =>
    json<{ reset: boolean; message: string }>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, password }),
    }),

  changePassword: (currentPassword: string | null, newPassword: string) =>
    json<SessionPayload & { message: string }>('/api/auth/change-password', {
      method: 'POST',
      auth: true,
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }).then((payload) => {
      setSession(payload);
      return payload;
    }),

  claimEstimate: (estimateId: string) =>
    json<{ claimed: boolean; already_owned: boolean; estimate_id: string }>(
      '/api/auth/claim-estimate',
      { method: 'POST', auth: true, body: JSON.stringify({ estimate_id: estimateId }) },
    ),

  providers: () => json<{ providers: string[] }>('/api/auth/providers'),

  /** Swap the one-time code an OAuth callback redirected with for a session. */
  exchangeOAuthCode: (code: string) =>
    json<SessionPayload>('/api/auth/oauth/exchange', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }).then(setSession),

  unlinkProvider: (provider: string) =>
    json<{ unlinked: string; user: AuthUser }>(`/api/auth/oauth/${provider}`, {
      method: 'DELETE',
      auth: true,
    }),

  /**
   * The URL that starts a provider flow.
   *
   * A full navigation rather than a fetch: OAuth is a browser redirect chain, and an XHR
   * cannot follow it through the provider's consent screen.
   */
  oauthUrl(provider: string, options: { link?: boolean; redirectTo?: string } = {}): string {
    const action = options.link ? 'link' : 'authorize';
    const query = options.redirectTo
      ? `?redirect_to=${encodeURIComponent(options.redirectTo)}`
      : '';
    return `${API_BASE}/api/auth/oauth/${provider}/${action}${query}`;
  },
};

/**
 * Restore a session on page load.
 *
 * Called once by the session provider. The access token did not survive the reload but
 * the refresh cookie did, so this is what turns "the browser remembers me" into an actual
 * session. A failure here is the ordinary signed-out case, not an error.
 */
export async function restoreSession(): Promise<AuthUser | null> {
  const ok = await refreshSession();
  return ok ? currentUser : null;
}
