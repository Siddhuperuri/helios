'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/SessionProvider';
import { Icon, Mark } from '@/components/site/Icon';
import { translate } from '@/lib/i18n';

/**
 * Primary navigation (§42).
 *
 * Six destinations, which is the ceiling before a navigation bar stops being a map and
 * starts being a list. The analysis console is not one of them: it is a different product
 * for a different reader, reached from the footer and from the result page, so that a
 * homeowner never has to decide whether "Model Laboratory" is something they need.
 *
 * The account control is not one of them either, and for a related reason: the nav is a
 * map of the product, and an account is a property of the reader rather than a place. It
 * sits beside the theme toggle, which is the other control of that kind.
 *
 * On small screens the menu is toggled with `hidden` rather than translated off-canvas. A
 * nav moved off-screen with a transform stays in the tab order and in the accessibility
 * tree, so a keyboard or screen-reader user walks through every hidden link before
 * reaching the page. `hidden` removes it from both.
 */

const ITEMS: { href: string; key: string }[] = [
  { href: '/', key: 'nav.home' },
  { href: '/start', key: 'nav.calculator' },
  { href: '/how-it-works', key: 'nav.howItWorks' },
  { href: '/projects', key: 'nav.projects' },
  { href: '/resources', key: 'nav.resources' },
  { href: '/about', key: 'nav.about' },
];

export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // A route change must close the menu, or the user taps a link and lands on the new page
  // with the old menu still covering it.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const t = (key: string) => translate('en', key);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-base/90 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1180px] items-center gap-4 px-5 py-3 sm:px-8">
        <Link
          href="/"
          className="flex min-h-touch items-center gap-2.5 text-ink-1 transition-colors hover:text-solar"
          aria-label={`${t('brand')} — home`}
        >
          <Mark size={22} />
          <span className="font-mono text-sm font-medium tracking-[0.06em]">{t('brand')}</span>
        </Link>

        <nav aria-label="Main" className="ml-auto hidden lg:block">
          <ul className="flex items-center gap-1">
            {ITEMS.map((item) => {
              const active =
                item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className={`block px-3 py-2 text-sm transition-colors ${
                      active
                        ? 'text-solar'
                        : 'text-ink-2 hover:text-ink-1'
                    }`}
                  >
                    {t(item.key)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="ml-auto flex items-center gap-1 lg:ml-0">
          <AccountLink />
          <ThemeToggle />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="mobile-nav"
            className="tap flex items-center justify-center border border-line text-ink-2
              transition-colors hover:border-line-bright hover:text-ink-1 lg:hidden"
          >
            <Icon name={open ? 'close' : 'menu'} title={open ? t('nav.close') : t('nav.menu')} />
          </button>
        </div>
      </div>

      <nav
        id="mobile-nav"
        aria-label="Main"
        className={`border-t border-line lg:hidden ${open ? 'block' : 'hidden'}`}
      >
        <ul className="mx-auto max-w-[1180px] px-5 py-2 sm:px-8">
          {ITEMS.map((item) => {
            const active =
              item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={active ? 'page' : undefined}
                  className={`flex min-h-touch items-center border-b border-line text-base
                    transition-colors ${active ? 'text-solar' : 'text-ink-2 hover:text-ink-1'}`}
                >
                  {t(item.key)}
                </Link>
              </li>
            );
          })}
          <AccountMenuItem />
        </ul>
      </nav>
    </header>
  );
}

/**
 * The account control, on desktop.
 *
 * Sits with the theme toggle rather than in the six-item navigation, which is deliberate:
 * the nav is a map of the product, and an account is not a place in the product. It is a
 * property of the person reading it.
 *
 * Renders nothing at all while the session is resolving. The alternative — showing "Sign
 * in" and swapping it for the account link a moment later — puts a visible flicker in the
 * header on every page load for people who *are* signed in, which reads as a bug.
 */
function AccountLink() {
  const { status, user } = useSession();

  if (status === 'loading') {
    return <span className="tap block" aria-hidden="true" />;
  }

  if (status === 'anonymous') {
    return (
      <Link
        href="/login"
        className="hidden min-h-touch items-center px-3 text-sm text-ink-2 transition-colors
          hover:text-ink-1 sm:flex"
      >
        Sign in
      </Link>
    );
  }

  return (
    <Link
      href="/account"
      title={user?.email}
      className="tap relative flex items-center justify-center border border-line text-ink-2
        transition-colors hover:border-line-bright hover:text-ink-1"
    >
      <Icon name="gauge" title="Account settings" />
      {user && !user.is_verified ? (
        // A quiet marker rather than a badge with a count. Verification is not urgent —
        // nothing is blocked by it — so it gets a dot, not an alarm.
        <span
          aria-hidden="true"
          className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-warning"
        />
      ) : null}
    </Link>
  );
}

/** The same control on small screens, where it belongs in the menu with everything else. */
function AccountMenuItem() {
  const { status, user } = useSession();
  if (status === 'loading') return null;

  const href = status === 'authenticated' ? '/account' : '/login';
  const label = status === 'authenticated' ? (user?.email ?? 'Account') : 'Sign in';

  return (
    <li>
      <Link
        href={href}
        className="flex min-h-touch items-center gap-2 border-b border-line text-base
          text-ink-2 transition-colors hover:text-ink-1"
      >
        <span className="truncate">{label}</span>
        {status === 'authenticated' && user && !user.is_verified ? (
          <span className="tag border-warning/40 text-warning">Unconfirmed</span>
        ) : null}
      </Link>
    </li>
  );
}

/**
 * Theme toggle.
 *
 * The consumer surface defaults to light because it is read on a phone, outdoors, in
 * sunlight (§32). The analysis console scopes itself to dark, where dense charts live for
 * long sessions. This control overrides both and remembers the choice.
 *
 * The stored preference is applied by an inline script in the document head, before first
 * paint, so a reader who chose dark never sees a white flash on the way there.
 */
function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark' | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem('helios.theme');
    setTheme(stored === 'dark' ? 'dark' : 'light');
  }, []);

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem('helios.theme', next);
    } catch {
      /* storage may be unavailable; the toggle still works for this page view */
    }
  }

  // Render nothing until the stored preference is known, so the button never shows the
  // wrong state for a frame.
  if (theme === null) return <span className="tap block" aria-hidden="true" />;

  return (
    <button
      type="button"
      onClick={toggle}
      className="tap flex items-center justify-center border border-line text-ink-2
        transition-colors hover:border-line-bright hover:text-ink-1"
    >
      <Icon
        name={theme === 'dark' ? 'sun' : 'moon'}
        title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      />
    </button>
  );
}
