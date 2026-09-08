'use client';

import dynamic from 'next/dynamic';

import { TileMap } from '@/components/estimate/map/TileMap';
import type { MapPickerProps } from '@/components/estimate/map/types';

/**
 * The swap point between map implementations.
 *
 * `NEXT_PUBLIC_MAP_ENGINE=leaflet` mounts the Leaflet adapter; anything else (including
 * the default of unset) mounts the hand-rolled tile map. The adapter is behind
 * `next/dynamic` with `ssr: false`, so when it is not selected its code is never
 * requested — choosing the built-in map costs nothing, and choosing Leaflet costs nothing
 * until the map is actually on screen.
 *
 * Both satisfy the same props contract in `./types`, so no caller changes either way.
 */

const LeafletMap = dynamic(
  () => import('@/components/estimate/map/LeafletMap').then((m) => m.LeafletMap),
  {
    ssr: false,
    loading: () => (
      <div
        className="flex w-full items-center justify-center border border-line bg-surface-2
          text-xs text-ink-3"
        style={{ height: 320 }}
      >
        Loading map…
      </div>
    ),
  },
);

export function MapPicker(props: MapPickerProps) {
  const engine = process.env.NEXT_PUBLIC_MAP_ENGINE;
  if (engine === 'leaflet') return <LeafletMap {...props} />;
  return <TileMap {...props} />;
}

export type { MapPickerProps } from '@/components/estimate/map/types';
