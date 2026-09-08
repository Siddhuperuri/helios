import Link from 'next/link';

/**
 * The account surface.
 *
 * Its own route group rather than a page inside `(site)`, for one reason: these screens
 * deliberately drop the main navigation. A person on the sign-in page has one thing to do,
 * and offering them six other destinations is an invitation to leave without doing it.
 *
 * It keeps the site's palette, type and rules — this is the same product, not a portal
 * bolted onto the side of it — and it keeps one way out, back to the calculator, because
 * the calculator has never required an account and this page must not imply otherwise.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <main id="main" className="flex-1">
        {children}
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[420px] flex-wrap items-center gap-x-5 gap-y-2 px-5 py-6 text-xs text-ink-3">
          <Link href="/start" className="link-underline">
            Use the calculator without an account
          </Link>
          <Link href="/about" className="link-underline">
            About
          </Link>
        </div>
      </footer>
    </div>
  );
}
