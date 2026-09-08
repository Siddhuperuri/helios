import type { Metadata } from 'next';

import { AccountSettings } from '@/components/account/AccountSettings';
import { Footer } from '@/components/site/Footer';
import { Nav } from '@/components/site/Nav';

export const metadata: Metadata = {
  title: 'Account settings',
  robots: { index: false, follow: false },
};

/**
 * Settings keeps the site chrome, unlike the sign-in screens.
 *
 * The difference is what the reader is doing. Someone signing in has one task and the nav
 * is a distraction; someone who is already signed in and adjusting a setting is in the
 * middle of using the product, and taking the navigation away would strand them.
 */
export default function AccountPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main id="main" className="flex-1">
        <AccountSettings />
      </main>
      <Footer />
    </div>
  );
}
