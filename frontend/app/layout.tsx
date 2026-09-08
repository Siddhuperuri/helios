import type { Metadata, Viewport } from 'next';
import { IBM_Plex_Mono, IBM_Plex_Sans } from 'next/font/google';

import { SessionProvider } from '@/components/auth/SessionProvider';
import { AnimatedFavicon } from '@/components/site/AnimatedFavicon';

import './globals.css';

/**
 * IBM Plex is a deliberate choice over the ubiquitous geometric sans.
 *
 * Plex was commissioned as an engineering identity, and the Sans/Mono pair share
 * proportions and terminals, so mixing them within a line does not read as two typefaces
 * fighting. That matters here because every numeral in this interface is set in the Mono
 * — figures are the content of a measurement instrument, and tabular monospaced numerals
 * let a column of them be compared down the page.
 *
 * Fonts are self-hosted by next/font: no runtime request to Google, no layout shift, and
 * nothing leaks the user's IP to a third party.
 */
const plexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-plex-sans',
  display: 'swap',
});

const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-plex-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: 'Helios — Know how much solar your location can produce',
    template: '%s · Helios',
  },
  description:
    'Get a personalised solar-energy estimate using your location, weather, solar ' +
    'resources, system characteristics and energy usage.',
  applicationName: 'Helios',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Both themes are declared so the browser paints its own chrome to match whichever the
  // reader ends up in.
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#FAFAF9' },
    { media: '(prefers-color-scheme: dark)', color: '#0A0B0D' },
  ],
};

/**
 * Applied before first paint so a reader who chose dark never sees a white flash.
 *
 * It is deliberately tiny and dependency-free: it reads one key and sets one attribute.
 * Anything that runs render-blocking in the head has to earn it, and preventing a
 * full-screen colour flash on every navigation does.
 */
const THEME_SCRIPT = `
try {
  var t = localStorage.getItem('helios.theme');
  if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
} catch (e) {}
`.trim();

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `suppressHydrationWarning` is required here, and only here. The theme script below
    // runs before React hydrates and stamps `data-theme` onto this element, so the server
    // HTML (no attribute) and the live DOM (attribute present) legitimately differ. This
    // tells React that difference is intended, for this element's own attributes only —
    // it does not extend to children, so a genuine mismatch anywhere else still reports.
    //
    // The alternative — rendering the attribute server-side — is not possible: the theme
    // lives in localStorage, which the server cannot read.
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50
            focus:border focus:border-solar focus:bg-surface-2 focus:px-4 focus:py-2
            focus:text-sm focus:text-ink-1"
        >
          Skip to main content
        </a>
        {/*
          The session lives above every route group, including the analysis console, so a
          signed-in user stays signed in when they cross between the two surfaces. It
          resolves to "anonymous" quickly and cheaply for the majority of visitors who do
          not have an account, and nothing below it waits on that resolution to render.
        */}
        <SessionProvider>{children}</SessionProvider>
        {/*
          `icon.svg` is the favicon and stays correct with no script running. This turns
          it from static to animated once the page can — see the component for why a
          favicon needed a workaround rather than an animated file.
        */}
        <AnimatedFavicon />
      </body>
    </html>
  );
}
