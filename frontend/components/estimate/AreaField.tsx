'use client';

import { useState } from 'react';

import { MapPicker } from '@/components/estimate/map/MapPicker';
import { polygonAreaM2 } from '@/components/estimate/map/projection';
import { Icon } from '@/components/site/Icon';
import type { AreaDraft } from '@/lib/draft';

/**
 * Available space, expressed however the user can express it (§13).
 *
 * Four routes, because "how much space do you have?" has four honest answers depending on
 * who is asked. A homeowner knows their roof is "about 30 by 20 feet". A farmer knows the
 * plot is "two acres". A commercial site manager has the figure in square metres. And many
 * people know exactly where it is but not how big — which is what the map is for, and why
 * tracing it is offered rather than demanded.
 *
 * Regional units are first-class, not an afterthought: acres, cents and gunthas appear
 * alongside square metres because those are the units land is actually discussed in across
 * much of India, and forcing a conversion on the user is a good way to collect a wrong
 * number.
 *
 * The area shown while tracing is computed by the same function the backend uses, so the
 * figure the user sees on the map is the figure the estimate is built from.
 */

const UNITS = [
  { value: 'sqft', label: 'square feet' },
  { value: 'sqm', label: 'square metres' },
  { value: 'acre', label: 'acres' },
  { value: 'cent', label: 'cents' },
  { value: 'guntha', label: 'gunthas' },
  { value: 'hectare', label: 'hectares' },
];

interface Props {
  value: AreaDraft | undefined;
  onChange: (value: AreaDraft) => void;
  /** Where to open the map, normally the location already chosen. */
  center: { lat: number; lon: number } | null;
}

export function AreaField({ value, onChange, center }: Props) {
  const mode = value?.mode ?? 'value';
  const [showMap, setShowMap] = useState(mode === 'polygon');

  const polygon = value?.polygon ?? [];
  const tracedArea = polygon.length >= 3
    ? polygonAreaM2(polygon.map(([lat, lon]) => ({ lat, lon })))
    : 0;

  function set(patch: Partial<AreaDraft>) {
    onChange({ ...(value ?? { mode: 'value' }), ...patch } as AreaDraft);
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {[
          { key: 'value', label: 'I know the area', icon: 'ruler' as const },
          { key: 'dimensions', label: 'I know length and width', icon: 'grid' as const },
          { key: 'polygon', label: 'Draw it on the map', icon: 'map-pin' as const },
          { key: 'unknown', label: 'Help me estimate', icon: 'help-circle' as const },
        ].map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => {
              set({ mode: option.key as AreaDraft['mode'] });
              setShowMap(option.key === 'polygon');
            }}
            aria-pressed={mode === option.key}
            className={`tap inline-flex items-center gap-2 border px-3.5 py-2 text-sm
              transition-colors ${
                mode === option.key
                  ? 'border-solar bg-surface-2 text-ink-1'
                  : 'border-line text-ink-2 hover:border-line-bright hover:text-ink-1'
              }`}
          >
            <Icon
              name={option.icon}
              size={16}
              className={mode === option.key ? 'text-solar' : 'text-steel'}
            />
            {option.label}
          </button>
        ))}
      </div>

      {/* ---------------------------------------------------------- direct entry */}
      {mode === 'value' ? (
        <div className="mt-4 flex max-w-md items-stretch gap-2">
          <input
            type="number"
            inputMode="decimal"
            min={1}
            value={value?.value ?? ''}
            onChange={(event) =>
              set({ value: event.target.value === '' ? null : Number(event.target.value) })
            }
            aria-label="Available area"
            placeholder="600"
            className="num w-full border border-line-strong bg-surface-1 px-3 py-3 text-base
              text-ink-1 placeholder:text-ink-4 focus:border-solar focus:outline-none"
          />
          <select
            value={value?.unit ?? 'sqft'}
            onChange={(event) => set({ unit: event.target.value })}
            aria-label="Area unit"
            className="border border-line-strong bg-surface-1 px-3 py-3 text-sm text-ink-1
              focus:border-solar focus:outline-none"
          >
            {UNITS.map((unit) => (
              <option key={unit.value} value={unit.value}>
                {unit.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {/* ------------------------------------------------------------ dimensions */}
      {mode === 'dimensions' ? (
        <div className="mt-4 flex max-w-md items-stretch gap-2">
          <input
            type="number"
            inputMode="decimal"
            min={1}
            value={value?.length ?? ''}
            onChange={(event) =>
              set({ length: event.target.value === '' ? null : Number(event.target.value) })
            }
            aria-label="Length"
            placeholder="Length"
            className="num w-full border border-line-strong bg-surface-1 px-3 py-3 text-base
              text-ink-1 placeholder:text-ink-4 focus:border-solar focus:outline-none"
          />
          <span className="flex items-center px-1 text-ink-3" aria-hidden="true">
            ×
          </span>
          <input
            type="number"
            inputMode="decimal"
            min={1}
            value={value?.width ?? ''}
            onChange={(event) =>
              set({ width: event.target.value === '' ? null : Number(event.target.value) })
            }
            aria-label="Width"
            placeholder="Width"
            className="num w-full border border-line-strong bg-surface-1 px-3 py-3 text-base
              text-ink-1 placeholder:text-ink-4 focus:border-solar focus:outline-none"
          />
          <select
            value={value?.dimension_unit ?? 'ft'}
            onChange={(event) => set({ dimension_unit: event.target.value })}
            aria-label="Unit"
            className="border border-line-strong bg-surface-1 px-3 py-3 text-sm text-ink-1
              focus:border-solar focus:outline-none"
          >
            <option value="ft">feet</option>
            <option value="m">metres</option>
          </select>
        </div>
      ) : null}

      {mode === 'dimensions' && value?.length && value?.width ? (
        <p className="num mt-2 text-sm text-ink-2">
          That is{' '}
          {(value.dimension_unit === 'm'
            ? value.length * value.width
            : (value.length * value.width) / 10.7639
          ).toLocaleString(undefined, { maximumFractionDigits: 0 })}{' '}
          m² of space.
        </p>
      ) : null}

      {/* ---------------------------------------------------------------- traced */}
      {mode === 'polygon' ? (
        <div className="mt-4">
          {center ? (
            <>
              {showMap ? (
                <MapPicker
                  label="Trace the area available for solar panels"
                  center={center}
                  zoom={18}
                  mode="polygon"
                  polygon={polygon.map(([lat, lon]) => ({ lat, lon }))}
                  onPolygonChange={(points) =>
                    set({
                      polygon: points.map((p) => [p.lat, p.lon] as [number, number]),
                      polygon_area_m2: points.length >= 3 ? polygonAreaM2(points) : null,
                    })
                  }
                  height={360}
                />
              ) : null}
              {tracedArea > 0 ? (
                <p className="num mt-3 text-sm text-ink-1">
                  Traced area:{' '}
                  <span className="text-solar">
                    {Math.round(tracedArea).toLocaleString()} m²
                  </span>{' '}
                  <span className="text-ink-3">
                    ({Math.round(tracedArea * 10.7639).toLocaleString()} sq ft)
                  </span>
                </p>
              ) : null}
            </>
          ) : (
            <p className="border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
              Choose your location first and the map will open there, so you can trace the
              actual roof or plot.
            </p>
          )}
        </div>
      ) : null}

      {/* --------------------------------------------------------------- unknown */}
      {mode === 'unknown' ? (
        <p className="mt-4 flex items-start gap-2.5 border border-line bg-surface-2 px-4 py-3
          text-sm leading-relaxed text-ink-2">
          <Icon name="info" size={16} className="mt-0.5 text-steel" />
          <span>
            We will size the system to your electricity use instead, and tell you how much
            space that system needs — so you can check whether you have it.
          </span>
        </p>
      ) : null}
    </div>
  );
}
