'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Icon } from '@/components/site/Icon';
import {
  TILE_SIZE,
  polygonAreaM2,
  project,
  scaleBar,
  unproject,
} from '@/components/estimate/map/projection';
import type { LatLon, MapPickerProps } from '@/components/estimate/map/types';

/**
 * A slippy map, hand-rolled.
 *
 * Roughly two hundred lines against a hundred and fifty kilobytes of library, for a
 * component that has to do four things: show tiles, pan, zoom, and let someone put a point
 * or trace a shape. The codebase already draws its own charts rather than shipping a
 * charting library; this is the same trade made for the same reason (§41).
 *
 * Three details that are easy to get wrong and matter here:
 *
 * **Zoom anchors on the cursor**, not on the centre. Zooming toward the middle when the
 * user is pointing at their roof means they have to chase it across the screen.
 *
 * **Pointer Events, not mouse and touch separately.** One code path covers mouse, touch
 * and stylus, and pointer capture means a drag that leaves the element still tracks.
 *
 * **A drag is not a click.** Panning the map must not drop a pin. The distinguisher is
 * distance moved, not timing, because a slow deliberate drag is still a drag.
 *
 * Accessibility: a map is a pointer-first control, so the keyboard path is explicit —
 * arrow keys pan, +/- zoom, Enter places a point at the crosshair. The surrounding step
 * also offers search and current-location entry, so nobody is forced through the map at
 * all (§9, §31).
 */

const OSM_TILE_URL = 'https://tile.openstreetmap.org';
const MIN_ZOOM = 3;
const MAX_ZOOM = 19;
/** Movement beyond this many pixels counts as a pan rather than a tap. */
const DRAG_THRESHOLD_PX = 6;

interface Size {
  width: number;
  height: number;
}

export function TileMap({
  center,
  zoom: initialZoom = 15,
  mode = 'pin',
  pin = null,
  polygon = [],
  onPinChange,
  onPolygonChange,
  height = 320,
  className = '',
  label,
}: MapPickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>({ width: 0, height });
  const [view, setView] = useState({ lat: center.lat, lon: center.lon, zoom: initialZoom });

  // Drag bookkeeping lives in a ref: it changes on every pointer move and must not
  // re-render the map sixty times a second.
  const drag = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originLat: number;
    originLon: number;
    moved: number;
  } | null>(null);
  const pinchStart = useRef<{ distance: number; zoom: number } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());

  // Re-centre when the caller moves the map (a search result, a GPS fix), but not while
  // the user is dragging it.
  useEffect(() => {
    if (drag.current) return;
    setView((v) => ({ ...v, lat: center.lat, lon: center.lon }));
  }, [center.lat, center.lon]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setSize({ width: rect.width, height: rect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const centerWorld = useMemo(
    () => project(view.lat, view.lon, view.zoom),
    [view.lat, view.lon, view.zoom],
  );

  /** Screen position of a coordinate, in container pixels. */
  const toScreen = useCallback(
    (point: LatLon) => {
      const world = project(point.lat, point.lon, view.zoom);
      return {
        x: world.x - centerWorld.x + size.width / 2,
        y: world.y - centerWorld.y + size.height / 2,
      };
    },
    [centerWorld.x, centerWorld.y, size.width, size.height, view.zoom],
  );

  /** The coordinate under a point on screen. */
  const fromScreen = useCallback(
    (x: number, y: number) =>
      unproject(
        centerWorld.x + x - size.width / 2,
        centerWorld.y + y - size.height / 2,
        view.zoom,
      ),
    [centerWorld.x, centerWorld.y, size.width, size.height, view.zoom],
  );

  // ------------------------------------------------------------------------ tiles
  const tiles = useMemo(() => {
    if (size.width === 0) return [];
    const scale = Math.pow(2, view.zoom);
    const left = centerWorld.x - size.width / 2;
    const top = centerWorld.y - size.height / 2;

    const minTileX = Math.floor(left / TILE_SIZE);
    const maxTileX = Math.floor((left + size.width) / TILE_SIZE);
    const minTileY = Math.max(0, Math.floor(top / TILE_SIZE));
    const maxTileY = Math.min(scale - 1, Math.floor((top + size.height) / TILE_SIZE));

    const out: { key: string; url: string; left: number; top: number }[] = [];
    for (let ty = minTileY; ty <= maxTileY; ty += 1) {
      for (let tx = minTileX; tx <= maxTileX; tx += 1) {
        // Wrap horizontally so panning across the date line shows map rather than void.
        const wrappedX = ((tx % scale) + scale) % scale;
        out.push({
          key: `${view.zoom}/${tx}/${ty}`,
          url: `${OSM_TILE_URL}/${view.zoom}/${wrappedX}/${ty}.png`,
          left: tx * TILE_SIZE - left,
          top: ty * TILE_SIZE - top,
        });
      }
    }
    return out;
  }, [centerWorld.x, centerWorld.y, size.width, size.height, view.zoom]);

  // ------------------------------------------------------------------- interaction
  const zoomBy = useCallback(
    (delta: number, anchorX?: number, anchorY?: number) => {
      setView((v) => {
        const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom + delta));
        if (next === v.zoom) return v;
        if (anchorX === undefined || anchorY === undefined || size.width === 0) {
          return { ...v, zoom: next };
        }
        // Keep the coordinate under the cursor fixed: find it, zoom, then shift the
        // centre so it lands back under the cursor.
        const world = project(v.lat, v.lon, v.zoom);
        const target = unproject(
          world.x + anchorX - size.width / 2,
          world.y + anchorY - size.height / 2,
          v.zoom,
        );
        const targetWorldNext = project(target.lat, target.lon, next);
        const centreNext = unproject(
          targetWorldNext.x - (anchorX - size.width / 2),
          targetWorldNext.y - (anchorY - size.height / 2),
          next,
        );
        return { lat: centreNext.lat, lon: centreNext.lon, zoom: next };
      });
    },
    [size.width, size.height],
  );

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    pointers.current.set(event.pointerId, {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    });

    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinchStart.current = {
        distance: Math.hypot(a!.x - b!.x, a!.y - b!.y),
        zoom: view.zoom,
      };
      drag.current = null;
      return;
    }

    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originLat: view.lat,
      originLon: view.lon,
      moved: 0,
    };
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (pointers.current.has(event.pointerId)) {
      pointers.current.set(event.pointerId, {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      });
    }

    // Two fingers: pinch to zoom, in fractional steps so it tracks the gesture.
    if (pointers.current.size === 2 && pinchStart.current) {
      const [a, b] = [...pointers.current.values()];
      const distance = Math.hypot(a!.x - b!.x, a!.y - b!.y);
      if (pinchStart.current.distance > 0) {
        const ratio = distance / pinchStart.current.distance;
        const target = pinchStart.current.zoom + Math.log2(ratio);
        const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(target)));
        if (clamped !== view.zoom) {
          zoomBy(clamped - view.zoom, (a!.x + b!.x) / 2, (a!.y + b!.y) / 2);
        }
      }
      return;
    }

    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;

    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    state.moved = Math.max(state.moved, Math.hypot(dx, dy));

    const origin = project(state.originLat, state.originLon, view.zoom);
    const next = unproject(origin.x - dx, origin.y - dy, view.zoom);
    setView((v) => ({ ...v, lat: next.lat, lon: next.lon }));
  }

  function onPointerUp(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const state = drag.current;
    pointers.current.delete(event.pointerId);
    if (pointers.current.size < 2) pinchStart.current = null;

    if (state && state.pointerId === event.pointerId) {
      drag.current = null;
      // Only a genuine tap places anything.
      if (state.moved <= DRAG_THRESHOLD_PX) {
        placeAt(event.clientX - rect.left, event.clientY - rect.top);
      }
    }
  }

  function placeAt(x: number, y: number) {
    const point = fromScreen(x, y);
    if (mode === 'polygon') {
      onPolygonChange?.([...polygon, point]);
    } else {
      onPinChange?.(point);
    }
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const panStep = 60;
    const handlers: Record<string, () => void> = {
      ArrowUp: () => panByPixels(0, -panStep),
      ArrowDown: () => panByPixels(0, panStep),
      ArrowLeft: () => panByPixels(-panStep, 0),
      ArrowRight: () => panByPixels(panStep, 0),
      '+': () => zoomBy(1),
      '=': () => zoomBy(1),
      '-': () => zoomBy(-1),
      Enter: () => placeAt(size.width / 2, size.height / 2),
      ' ': () => placeAt(size.width / 2, size.height / 2),
    };
    const handler = handlers[event.key];
    if (handler) {
      event.preventDefault();
      handler();
    }
  }

  function panByPixels(dx: number, dy: number) {
    setView((v) => {
      const world = project(v.lat, v.lon, v.zoom);
      const next = unproject(world.x + dx, world.y + dy, v.zoom);
      return { ...v, lat: next.lat, lon: next.lon };
    });
  }

  // A non-passive wheel listener, because zooming has to prevent the page scrolling and
  // React's synthetic wheel handler is registered passively.
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    function handler(event: WheelEvent) {
      event.preventDefault();
      const rect = element!.getBoundingClientRect();
      zoomBy(
        event.deltaY < 0 ? 1 : -1,
        event.clientX - rect.left,
        event.clientY - rect.top,
      );
    }
    element.addEventListener('wheel', handler, { passive: false });
    return () => element.removeEventListener('wheel', handler);
  }, [zoomBy]);

  const bar = scaleBar(view.lat, view.zoom);
  const polygonPoints = polygon.map((p) => toScreen(p));
  const area = polygon.length >= 3 ? polygonAreaM2(polygon) : 0;
  const pinScreen = pin ? toScreen(pin) : null;

  return (
    <div className={className}>
      <div
        ref={containerRef}
        role="application"
        aria-label={`${label}. Drag to move the map, use plus and minus to zoom, and press Enter to place a point at the centre.`}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        style={{ height, touchAction: 'none' }}
        className="relative w-full cursor-crosshair select-none overflow-hidden border border-line
          bg-surface-2"
      >
        {/* tiles */}
        {tiles.map((tile) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={tile.key}
            src={tile.url}
            alt=""
            aria-hidden="true"
            draggable={false}
            width={TILE_SIZE}
            height={TILE_SIZE}
            loading="lazy"
            className="pointer-events-none absolute"
            style={{ left: tile.left, top: tile.top }}
          />
        ))}

        {/* traced area */}
        {polygonPoints.length >= 2 ? (
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            aria-hidden="true"
          >
            <polygon
              points={polygonPoints.map((p) => `${p.x},${p.y}`).join(' ')}
              fill="rgb(var(--c-solar) / 0.22)"
              stroke="rgb(var(--c-solar))"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            {polygonPoints.map((p, index) => (
              <circle
                key={index}
                cx={p.x}
                cy={p.y}
                r="5"
                fill="rgb(var(--c-base))"
                stroke="rgb(var(--c-solar))"
                strokeWidth="2"
              />
            ))}
          </svg>
        ) : null}

        {/* pin */}
        {pinScreen ? (
          <div
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-full text-solar"
            style={{ left: pinScreen.x, top: pinScreen.y }}
          >
            <Icon name="map-pin" size={32} className="drop-shadow" />
          </div>
        ) : null}

        {/* centre crosshair: the keyboard target, and a sight for precise placement */}
        <div
          className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
            text-ink-1/40"
          aria-hidden="true"
        >
          <Icon name="crosshair" size={22} />
        </div>

        {/* zoom controls: large enough to hit on a phone (§32) */}
        <div className="absolute right-2 top-2 flex flex-col">
          <button
            type="button"
            onClick={() => zoomBy(1)}
            className="tap flex items-center justify-center border border-line-strong bg-base/90
              text-lg text-ink-1 transition-colors hover:bg-surface-2"
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => zoomBy(-1)}
            className="tap -mt-px flex items-center justify-center border border-line-strong
              bg-base/90 text-lg text-ink-1 transition-colors hover:bg-surface-2"
            aria-label="Zoom out"
          >
            −
          </button>
        </div>

        {/* scale bar */}
        <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1.5">
          <div
            className="h-2 border-x border-b border-ink-1/70"
            style={{ width: bar.widthPx }}
          />
          <span className="num text-2xs text-ink-1/80">{bar.label}</span>
        </div>

        {/* attribution is a licence condition of the tile service, not a courtesy */}
        <div className="pointer-events-auto absolute bottom-0 right-0 bg-base/80 px-1.5 py-0.5">
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noopener noreferrer"
            className="text-2xs text-ink-3 underline decoration-line-bright underline-offset-2"
          >
            © OpenStreetMap
          </a>
        </div>
      </div>

      {mode === 'polygon' ? (
        <div className="mt-2 flex flex-wrap items-center gap-3 border border-line border-t-0
          bg-surface-1 px-3 py-2">
          <p className="text-xs text-ink-2">
            {polygon.length === 0
              ? 'Tap each corner of the area.'
              : polygon.length < 3
                ? `${polygon.length} corner${polygon.length === 1 ? '' : 's'} — at least three are needed.`
                : `${polygon.length} corners · about ${Math.round(area).toLocaleString()} m² (${Math.round(area * 10.7639).toLocaleString()} sq ft)`}
          </p>
          {polygon.length > 0 ? (
            <div className="ml-auto flex gap-2">
              <button
                type="button"
                onClick={() => onPolygonChange?.(polygon.slice(0, -1))}
                className="border border-line px-2.5 py-1.5 text-xs text-ink-2 transition-colors
                  hover:border-line-bright hover:text-ink-1"
              >
                Undo corner
              </button>
              <button
                type="button"
                onClick={() => onPolygonChange?.([])}
                className="border border-line px-2.5 py-1.5 text-xs text-ink-2 transition-colors
                  hover:border-critical hover:text-critical"
              >
                Clear
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
