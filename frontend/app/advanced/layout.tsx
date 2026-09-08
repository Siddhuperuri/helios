import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Analysis Console',
  description:
    'Irradiance forecasting, model validation, uncertainty calibration and experiment ' +
    'tracking for technical users.',
};

/**
 * The analysis console keeps the dark instrument palette it was designed around.
 *
 * Scoping it to a wrapper element rather than to `<html>` is what makes the split
 * practical: the CSS custom properties are defined on a `[data-theme='dark']` selector, so
 * everything inside this element resolves against the dark palette while the consumer
 * surface stays light — with no flash on navigation, no script, and no duplicated
 * stylesheet.
 *
 * `bg-base` is set here rather than relying on the body, because the body is painted in
 * the consumer theme.
 */
export default function AdvancedLayout({ children }: { children: React.ReactNode }) {
  return (
    <div data-theme="dark" className="min-h-screen bg-base text-ink-1">
      {children}
    </div>
  );
}
