/**
 * The favicon frame math.
 *
 * Live behaviour — the `<link>` href actually cycling in a real tab — was verified by
 * hand against a running dev server, including proving it fails silently when SMIL is
 * used directly (the reason this component exists at all: see its docstring). What is
 * worth pinning down in a test is the part most likely to silently regress on a future
 * edit: the numbers. A wrong easing constant or a swapped min/max would still produce a
 * plausible-looking animation, just not the one the source file actually specifies.
 */

import { describe, expect, it } from 'vitest';

import {
  cubicBezierEase,
  FRAME_COUNT,
  frameAt,
  pulseAt,
  rotationAt,
} from '@/components/site/AnimatedFavicon';

describe('cubicBezierEase', () => {
  it('is the identity function for a linear curve', () => {
    // cubic-bezier(0,0,1,1) draws a straight line, so easing must not bend it.
    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      expect(cubicBezierEase(t, 0, 0, 1, 1)).toBeCloseTo(t, 5);
    }
  });

  it('starts at 0 and ends at 1 for any curve', () => {
    // True of every cubic-bezier timing function by construction (P0=(0,0), P3=(1,1)).
    // A solver that drifts from this at the endpoints is numerically unstable, and that
    // would show up here before it showed up as a visibly wrong frame 0 or frame 24.
    expect(cubicBezierEase(0, 0.167, 0.167, 0.833, 0.833)).toBeCloseTo(0, 4);
    expect(cubicBezierEase(1, 0.167, 0.167, 0.833, 0.833)).toBeCloseTo(1, 4);
  });
});

describe('rotationAt', () => {
  it('starts at 0deg and ends at 45deg, matching the source Lottie', () => {
    expect(rotationAt(0)).toBeCloseTo(0, 4);
    expect(rotationAt(1)).toBeCloseTo(45, 4);
  });

  it('is monotonically increasing', () => {
    // The source rotation keyframes never reverse (0 -> 45, one segment), so neither
    // should the eased curve — a bezier easing *can* overshoot past its endpoints for
    // some control points, and these specific ones must not.
    let previous = -Infinity;
    for (let i = 0; i <= 20; i++) {
      const angle = rotationAt(i / 20);
      expect(angle).toBeGreaterThanOrEqual(previous);
      previous = angle;
    }
  });
});

describe('pulseAt', () => {
  it('starts and ends at 1, peaking at the midpoint', () => {
    expect(pulseAt(0, 1.1)).toBeCloseTo(1, 4);
    expect(pulseAt(1, 1.1)).toBeCloseTo(1, 4);
    expect(pulseAt(0.5, 1.1)).toBeCloseTo(1.1, 4);
  });

  it('never exceeds the declared peak', () => {
    // A pulse that overshot its peak would mean the rays or the circle grow larger than
    // the source ever asked for — worth catching, since it is exactly the kind of thing
    // that would look fine at a glance and wrong on close inspection.
    for (let i = 0; i <= 20; i++) {
      expect(pulseAt(i / 20, 1.1)).toBeLessThanOrEqual(1.1 + 1e-6);
    }
  });
});

describe('frameAt', () => {
  it('frame 0 matches the static icon.svg exactly', () => {
    // The whole point of sharing this math with the static fallback: the animation must
    // not visibly jump the instant this component takes over from it.
    const svg = decodeURIComponent(frameAt(0).replace('data:image/svg+xml,', ''));
    expect(svg).toContain('rotate(0.00)');
    expect(svg).toContain('scale(1.000)');
    expect(svg).toContain('#FF9800');
    expect(svg).toContain('#FFEB3B');
  });

  it('produces a distinct, valid frame for every index in the loop', () => {
    const frames = Array.from({ length: FRAME_COUNT }, (_, i) => frameAt(i));
    const distinct = new Set(frames);
    // Not strictly guaranteed to all differ for a pathological easing curve, but for
    // this one every frame is visually distinct — a collision would mean the loop skips
    // or repeats a step, which is the failure this test exists to catch.
    expect(distinct.size).toBe(FRAME_COUNT);
    for (const frame of frames) {
      expect(frame.startsWith('data:image/svg+xml,')).toBe(true);
    }
  });

  it('every frame parses as well-formed SVG', () => {
    for (let i = 0; i < FRAME_COUNT; i++) {
      const svg = decodeURIComponent(frameAt(i).replace('data:image/svg+xml,', ''));
      const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
      expect(doc.querySelector('parsererror')).toBeNull();
    }
  });
});
