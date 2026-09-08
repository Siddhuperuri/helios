'use client';

import { useEffect } from 'react';

/**
 * Makes the favicon actually animate.
 *
 * `app/icon.svg` is a spec-correct animated SVG — real SMIL, matching the source Lottie's
 * timing and easing exactly — and it does not animate as a favicon. That was checked, not
 * assumed: a browser tab renders its icon as a static image resource rather than a live
 * document, and Chromium's rendering path for that does not run an SVG's internal
 * animation timeline. The file still animates correctly if opened directly in a tab, and
 * it remains what non-JS clients (crawlers, view-source, a browser with scripting off)
 * see — this component only enhances it once the page can run script.
 *
 * The technique that does work, used by GitHub's build-status favicon and others: redraw
 * the tab icon by periodically pointing `<link rel="icon">` at a new image. A browser
 * repaints the tab for a changed `href` the same way it would for any other updated image
 * source — there is no animated-format requirement to satisfy, which is what makes this
 * reliable where an animated file is not.
 *
 * Every frame is generated from the same numbers `icon.svg` documents: the rotation sweep
 * (0deg to 45deg, eased with the Lottie's own cubic-bezier(0.167, 0.167, 0.833, 0.833)),
 * the two scale pulses (eased with its cubic-bezier(0.333, 0, 0.667, 1)), and the 24fps,
 * 28-frame loop length. `frameAt(0)` is therefore identical to the static file — the
 * animation does not jump when this component takes over.
 */

export const FRAME_COUNT = 24;
const LOOP_MS = (28 / 24) * 1000; // 28 frames at 24fps, matching the source exactly

const RAY_POINTS =
  '13,5 18,0 13,-5 13,-13 5,-13 0,-18 -5,-13 -13,-13 -13,-5 -18,0 -13,5 -13,13 -5,13 0,18 5,13 13,13';

/**
 * The CSS/SMIL cubic-bezier timing function, evaluated by Newton-Raphson.
 *
 * This is what a browser does internally for `keySplines` and for CSS's own
 * `cubic-bezier()` — solving `x(u) = t` for the bezier parameter `u`, then reading `y(u)`.
 * Reimplemented here only because the two easing curves need evaluating in plain JS to
 * build a lookup frame, not because SMIL's own math needed second-guessing.
 */
export function cubicBezierEase(t: number, x1: number, y1: number, x2: number, y2: number): number {
  let u = t;
  for (let i = 0; i < 8; i++) {
    const x = 3 * (1 - u) ** 2 * u * x1 + 3 * (1 - u) * u * u * x2 + u ** 3;
    const dx = 3 * (1 - u) ** 2 * x1 + 6 * (1 - u) * u * (x2 - x1) + 3 * u * u * (1 - x2);
    if (Math.abs(dx) < 1e-6) break;
    u = Math.min(1, Math.max(0, u - (x - t) / dx));
  }
  return 3 * (1 - u) ** 2 * u * y1 + 3 * (1 - u) * u * u * y2 + u ** 3;
}

export function rotationAt(t: number): number {
  return 45 * cubicBezierEase(t, 0.167, 0.167, 0.833, 0.833);
}

/** A scale pulse: 1 -> peak -> 1 over the loop, eased the same way on each half. */
export function pulseAt(t: number, peak: number): number {
  const inFirstHalf = t < 0.5;
  const local = inFirstHalf ? t / 0.5 : (t - 0.5) / 0.5;
  const eased = cubicBezierEase(local, 0.333, 0, 0.667, 1);
  const [from, to] = inFirstHalf ? [1, peak] : [peak, 1];
  return from + eased * (to - from);
}

export function frameAt(index: number): string {
  const t = index / FRAME_COUNT;
  const angle = rotationAt(t);
  const raysScale = pulseAt(t, 1.1);
  const circleScale = pulseAt(t, 1.05);

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">` +
    `<g transform="translate(24,24) rotate(${angle.toFixed(2)}) scale(${raysScale.toFixed(3)})">` +
    `<polygon fill="#FF9800" points="${RAY_POINTS}"/></g>` +
    `<g transform="translate(24,24) scale(${circleScale.toFixed(3)})">` +
    `<circle cx="0" cy="0" r="11" fill="#FFEB3B"/></g></svg>`;

  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

// Built once per page load. Twenty-four tiny SVG strings, not twenty-four network
// requests — every frame is a data URI, so cycling them is a DOM write, nothing more.
const FRAMES = Array.from({ length: FRAME_COUNT }, (_, i) => frameAt(i));

export function AnimatedFavicon() {
  useEffect(() => {
    // A perpetually spinning tab icon is exactly the kind of motion
    // `prefers-reduced-motion` exists to suppress. The static file underneath is the
    // correct fallback, not a degraded one.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) return;

    const originalHref = link.href;
    let frame = 0;
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer) return;
      timer = setInterval(() => {
        frame = (frame + 1) % FRAME_COUNT;
        link.href = FRAMES[frame]!;
      }, LOOP_MS / FRAME_COUNT);
    };
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };

    // No reason to redraw a tab icon nobody can see, and every redraw while backgrounded
    // is wasted work the moment the tab is switched away from.
    const onVisibility = () => {
      if (document.visibilityState === 'visible') start();
      else stop();
    };

    if (document.visibilityState === 'visible') start();
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      stop();
      // Restored on unmount so the tab does not get stuck on an odd frame — this
      // component is expected to live for the page's lifetime, but cheap to be correct.
      link.href = originalHref;
    };
  }, []);

  return null;
}
