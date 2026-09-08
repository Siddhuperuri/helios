import { Footer } from '@/components/site/Footer';
import { Nav } from '@/components/site/Nav';

/**
 * The consumer surface: everything a non-specialist sees.
 *
 * It carries the site chrome and inherits the light palette from `:root`. The analysis
 * console lives outside this group under `/advanced`, where it scopes itself to the dark
 * instrument palette it was designed for — the two surfaces share a design system and a
 * server, but not a reader.
 */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main id="main" className="flex-1">
        {children}
      </main>
      <Footer />
    </div>
  );
}
