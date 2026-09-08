'use client';

import { useEffect, useRef, useState } from 'react';
import type { Map as LeafletMapInstance, Marker, Polygon } from 'leaflet';

// Static, because a CSS import is extracted at build time rather than executed. This
// module is only ever reached through a dynamic import, so Next code-splits the stylesheet
// with it and nobody using the default map downloads it.
import 'leaflet/dist/leaflet.css';

import { polygonAreaM2 } from '@/components/estimate/map/projection';
import type { LatLon, MapPickerProps } from '@/components/estimate/map/types';

/**
 * The Leaflet-backed alternative to the hand-rolled map.
 *
 * Selected with `NEXT_PUBLIC_MAP_ENGINE=leaflet`. It exists so that pan, zoom and touch
 * behaviour can fall back to a battle-tested implementation on a device where the built-in
 * map misbehaves, without any caller changing — both mount through `MapPicker` and satisfy
 * the same props.
 *
 * Notes specific to this adapter:
 *
 * - **Leaflet itself is imported at runtime**, inside the effect, because it touches
 *   `window` at module scope and a static import would break server rendering. Its
 *   stylesheet is imported statically instead: a CSS import is extracted at build time
 *   rather than executed, and Next code-splits it along with this module, so it reaches
 *   nobody who is using the default map.
 * - **No `leaflet-draw`.** Tracing an area is click-to-add-vertex, which plain Leaflet
 *   handles in a dozen lines. A second dependency to draw a polygon is not a trade worth
 *   making.
 * - **Area is computed by the shared `polygonAreaM2`**, not by a Leaflet plugin, so the
 *   figure shown while drawing matches the hand-rolled map and the backend exactly.
 */
export function LeafletMap({
  center,
  zoom = 15,
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
  const mapRef = useRef<LeafletMapInstance | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const polygonRef = useRef<Polygon | null>(null);
  const vertexLayersRef = useRef<unknown[]>([]);
  const [ready, setReady] = useState(false);

  // Callbacks and mode are read inside Leaflet's own event handler, which is registered
  // once. A ref keeps that handler looking at current values without tearing the map down
  // and rebuilding it on every render.
  const handlers = useRef({ mode, polygon, onPinChange, onPolygonChange });
  handlers.current = { mode, polygon, onPinChange, onPolygonChange };

  useEffect(() => {
    let cancelled = false;
    let instance: LeafletMapInstance | null = null;

    (async () => {
      const L = (await import('leaflet')).default;
      if (cancelled || !containerRef.current) return;

      instance = L.map(containerRef.current, {
        center: [center.lat, center.lon],
        zoom,
        zoomControl: true,
        attributionControl: true,
      });

      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(instance);

      instance.on('click', (event: { latlng: { lat: number; lng: number } }) => {
        const point: LatLon = { lat: event.latlng.lat, lon: event.latlng.lng };
        const current = handlers.current;
        if (current.mode === 'polygon') {
          current.onPolygonChange?.([...current.polygon, point]);
        } else {
          current.onPinChange?.(point);
        }
      });

      mapRef.current = instance;
      setReady(true);
    })();

    return () => {
      cancelled = true;
      instance?.remove();
      mapRef.current = null;
      markerRef.current = null;
      polygonRef.current = null;
    };
    // Mount once. Subsequent centre and zoom changes are applied by the effects below,
    // because rebuilding the map would throw away the user's pan position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Follow the caller's centre (a search result, a GPS fix).
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    mapRef.current.setView([center.lat, center.lon], mapRef.current.getZoom());
  }, [ready, center.lat, center.lon]);

  // Pin.
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    (async () => {
      const L = (await import('leaflet')).default;
      const map = mapRef.current;
      if (!map) return;

      if (!pin) {
        markerRef.current?.remove();
        markerRef.current = null;
        return;
      }
      if (markerRef.current) {
        markerRef.current.setLatLng([pin.lat, pin.lon]);
        return;
      }
      // Leaflet's default marker images resolve against a bundler path that Next does not
      // serve. A divIcon avoids the broken-image problem entirely and matches the palette.
      const icon = L.divIcon({
        className: '',
        html:
          '<div style="width:18px;height:18px;border-radius:50%;background:rgb(var(--c-solar));' +
          'border:3px solid rgb(var(--c-base));box-shadow:0 0 0 1px rgb(var(--c-solar))"></div>',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      });
      markerRef.current = L.marker([pin.lat, pin.lon], { icon, keyboard: false }).addTo(map);
    })();
  }, [ready, pin]);

  // Traced area.
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    (async () => {
      const L = (await import('leaflet')).default;
      const map = mapRef.current;
      if (!map) return;

      polygonRef.current?.remove();
      polygonRef.current = null;
      vertexLayersRef.current.forEach((layer) => (layer as { remove: () => void }).remove());
      vertexLayersRef.current = [];

      if (polygon.length === 0) return;

      const latlngs = polygon.map((p) => [p.lat, p.lon] as [number, number]);
      if (polygon.length >= 3) {
        polygonRef.current = L.polygon(latlngs, {
          color: 'rgb(var(--c-solar))',
          weight: 2,
          fillColor: 'rgb(var(--c-solar))',
          fillOpacity: 0.22,
        }).addTo(map);
      }
      vertexLayersRef.current = latlngs.map((latlng) =>
        L.circleMarker(latlng, {
          radius: 5,
          color: 'rgb(var(--c-solar))',
          weight: 2,
          fillColor: 'rgb(var(--c-base))',
          fillOpacity: 1,
        }).addTo(map),
      );
    })();
  }, [ready, polygon]);

  const area = polygon.length >= 3 ? polygonAreaM2(polygon) : 0;

  return (
    <div className={className}>
      <div
        ref={containerRef}
        role="application"
        aria-label={label}
        style={{ height }}
        className="w-full border border-line bg-surface-2"
      />
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
