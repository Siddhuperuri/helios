'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { MapPicker } from '@/components/estimate/map/MapPicker';
import { Icon } from '@/components/site/Icon';
import type { Draft } from '@/lib/draft';
import { estimateApi, type LocationDto } from '@/lib/estimate';
import { translate } from '@/lib/i18n';

/**
 * Choosing a location (§9), and surviving it going wrong (§10).
 *
 * Three routes in, offered side by side rather than as a primary with fallbacks hidden
 * behind a failure: someone sitting at a desk planning a farm they are not standing on
 * wants search, and someone on the roof wants GPS. Neither is the "real" way.
 *
 * The design rule that shapes this component: **coordinates are never the interface.**
 * A GPS fix and a dropped pin are both reverse-geocoded to a place name, and latitude and
 * longitude appear only as a small confirmation line underneath. Showing somebody
 * "16.5062, 80.6480" as the answer to "where are you?" is a failure to answer.
 *
 * Permission failure is handled as a normal branch rather than an error state. The browser
 * denying geolocation is not the user's mistake and not a problem — the other two routes
 * are right there, and the copy says so without apology or alarm.
 */

type Method = 'geolocation' | 'search' | 'map';

interface Props {
  value: Draft['location'];
  onChange: (location: NonNullable<Draft['location']>) => void;
}

/** Where the map opens before anything is chosen. Central India, wide enough to orient. */
const DEFAULT_CENTER = { lat: 20.59, lon: 78.96 };

export function LocationStep({ value, onChange }: Props) {
  const t = (key: string) => translate('en', key);

  const [method, setMethod] = useState<Method | null>(value ? 'search' : null);
  const [query, setQuery] = useState(value?.query ?? '');
  const [results, setResults] = useState<LocationDto[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestId = useRef(0);
  // Choosing a result writes its label into the input, which would otherwise look like
  // fresh typing and immediately re-open the list the user just dismissed.
  const suppressSearch = useRef(false);

  const selected = value?.label
    ? {
        label: value.label,
        latitude: value.latitude,
        longitude: value.longitude,
        elevation_m: value.elevation_m,
      }
    : null;

  // ---------------------------------------------------------------------- search
  useEffect(() => {
    if (method !== 'search') return;
    if (timer.current) clearTimeout(timer.current);

    if (suppressSearch.current) {
      suppressSearch.current = false;
      return;
    }

    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setSearchError(null);
      return;
    }

    timer.current = setTimeout(async () => {
      const id = ++requestId.current;
      setSearching(true);
      setSearchError(null);
      try {
        const { results: found } = await estimateApi.searchLocations(trimmed, 6);
        // Discard a response that arrived after a newer one; typing fast otherwise makes
        // an earlier, staler result win.
        if (id !== requestId.current) return;
        setResults(found);
        if (found.length === 0) setSearchError(t('location.searchFailed'));
      } catch {
        if (id !== requestId.current) return;
        setResults([]);
        setSearchError(t('location.searchFailed'));
      } finally {
        if (id === requestId.current) setSearching(false);
      }
    }, 320);

    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, method]);

  // ----------------------------------------------------------------- geolocation
  const useMyLocation = useCallback(() => {
    setMethod('geolocation');
    setGeoError(null);

    // Test the value, not the key. Browsers on an insecure origin can expose
    // `navigator.geolocation` as undefined while the property itself still exists, so an
    // `in` check passes and the call below throws — turning a graceful fallback into a
    // blank screen exactly where §10 requires the opposite.
    if (typeof navigator.geolocation?.getCurrentPosition !== 'function') {
      setGeoError(
        'This browser cannot share your location. Search for your place instead, or point to it on the map.',
      );
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        setLocating(false);
        await resolveCoordinates(latitude, longitude, 'geolocation');
      },
      (error) => {
        setLocating(false);
        // Each failure gets its own sentence, because "location unavailable" and "you said
        // no" call for different next steps.
        const messages: Record<number, string> = {
          1: t('location.permissionDenied'),
          2: 'Your device could not work out where it is right now.',
          3: 'Finding your location took too long.',
        };
        setGeoError(messages[error.code] ?? t('location.permissionDenied'));
      },
      { enableHighAccuracy: true, timeout: 12_000, maximumAge: 60_000 },
    );
  }, []);

  /** Turn a coordinate pair into something a person recognises before showing it. */
  async function resolveCoordinates(lat: number, lon: number, via: Method) {
    setResolving(true);
    try {
      const { location } = await estimateApi.reverseGeocode(lat, lon);
      onChange({
        latitude: location.latitude,
        longitude: location.longitude,
        label: location.label,
        elevation_m: location.elevation_m ?? null,
        method: via,
      });
    } catch {
      // Reverse geocoding is a nicety. Losing the name must not lose the location, so the
      // coordinates stand in and the estimate proceeds unaffected.
      onChange({
        latitude: lat,
        longitude: lon,
        label: `${lat.toFixed(4)}, ${lon.toFixed(4)}`,
        method: via,
      });
    } finally {
      setResolving(false);
    }
  }

  function chooseResult(result: LocationDto) {
    suppressSearch.current = true;
    // Any search still in flight must not land after this and re-populate the list.
    requestId.current += 1;
    onChange({
      latitude: result.latitude,
      longitude: result.longitude,
      label: result.label,
      elevation_m: result.elevation_m ?? null,
      method: 'search',
    });
    setResults([]);
    setQuery(result.label);
  }

  const mapCenter =
    value?.latitude != null && value?.longitude != null
      ? { lat: value.latitude, lon: value.longitude }
      : DEFAULT_CENTER;

  return (
    <div>
      {/* -------------------------------------------------------- chosen location */}
      {selected ? (
        <div className="mb-6 animate-fade-rise border border-solar/40 bg-solar/5 p-4">
          <div className="flex items-start gap-3">
            <Icon name="check" size={20} className="mt-0.5 text-solar" />
            <div className="min-w-0 flex-1">
              <p className="font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
                {t('location.found')}
              </p>
              <p className="mt-1 break-words text-lg font-medium leading-snug text-ink-1">
                {selected.label}
              </p>
              <p className="num mt-1.5 text-2xs text-ink-3">
                {selected.latitude?.toFixed(4)}, {selected.longitude?.toFixed(4)}
                {selected.elevation_m != null
                  ? ` · ${Math.round(selected.elevation_m)} m elevation`
                  : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setMethod(null);
                setQuery('');
                setResults([]);
              }}
              className="shrink-0 border border-line px-2.5 py-1.5 text-xs text-ink-2
                transition-colors hover:border-line-bright hover:text-ink-1"
            >
              {t('location.change')}
            </button>
          </div>
        </div>
      ) : null}

      {/* ----------------------------------------------------------- method choice */}
      {!selected || method ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <MethodButton
            icon="crosshair"
            title={t('location.useMyLocation')}
            hint={t('location.useMyLocationHint')}
            active={method === 'geolocation'}
            onClick={useMyLocation}
          />
          <MethodButton
            icon="search"
            title={t('location.search')}
            hint={t('location.searchHint')}
            active={method === 'search'}
            onClick={() => setMethod('search')}
          />
          <MethodButton
            icon="map-pin"
            title={t('location.pickOnMap')}
            hint={t('location.pickOnMapHint')}
            active={method === 'map'}
            onClick={() => setMethod('map')}
          />
        </div>
      ) : null}

      {/* -------------------------------------------------------------- geolocation */}
      {method === 'geolocation' ? (
        <div className="mt-5">
          {locating || resolving ? (
            <p className="flex items-center gap-2.5 text-sm text-ink-2" role="status">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-solar opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-solar" />
              </span>
              {locating ? t('location.locating') : 'Looking up the place name…'}
            </p>
          ) : null}

          {geoError ? (
            <div className="border border-line bg-surface-1 p-4">
              <p className="flex items-start gap-2.5 text-sm text-ink-1">
                <Icon name="info" size={18} className="mt-0.5 text-warning" />
                <span>{geoError}</span>
              </p>
              <p className="mt-2 pl-7 text-sm leading-relaxed text-ink-2">
                {t('location.permissionDeniedHelp')}
              </p>
              <div className="mt-4 flex flex-wrap gap-2 pl-7">
                <button
                  type="button"
                  onClick={() => setMethod('search')}
                  className="tap inline-flex items-center gap-2 border border-line-strong px-4 py-2
                    text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
                >
                  <Icon name="search" size={16} />
                  {t('location.search')}
                </button>
                <button
                  type="button"
                  onClick={() => setMethod('map')}
                  className="tap inline-flex items-center gap-2 border border-line-strong px-4 py-2
                    text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
                >
                  <Icon name="map-pin" size={16} />
                  {t('location.pickOnMap')}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* ------------------------------------------------------------------ search */}
      {method === 'search' ? (
        <div className="mt-5">
          <label htmlFor="location-search" className="mb-2 block text-sm text-ink-1">
            {t('location.search')}
          </label>
          <div className="relative">
            <input
              id="location-search"
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Village, town, city or district"
              autoComplete="off"
              role="combobox"
              aria-expanded={results.length > 0}
              aria-controls="location-results"
              aria-autocomplete="list"
              className="w-full border border-line-strong bg-surface-1 px-3 py-3 pr-10 text-base
                text-ink-1 placeholder:text-ink-4 focus:border-solar focus:outline-none"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-4">
              <Icon name="search" size={18} />
            </span>
          </div>
          <p className="mt-2 text-xs text-ink-3">{t('location.searchHint')}</p>

          {searching ? (
            <p className="mt-3 text-xs text-ink-3" role="status">
              Searching…
            </p>
          ) : null}

          {results.length > 0 ? (
            <ul
              id="location-results"
              role="listbox"
              aria-label="Matching places"
              className="mt-3 divide-y divide-line border border-line-strong bg-surface-1"
            >
              {results.map((result) => (
                <li key={`${result.latitude},${result.longitude}`} role="option" aria-selected={false}>
                  <button
                    type="button"
                    onClick={() => chooseResult(result)}
                    className="tap flex w-full items-center justify-between gap-3 px-3 py-3 text-left
                      transition-colors hover:bg-surface-2"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-ink-1">{result.name}</span>
                      <span className="block truncate text-xs text-ink-3">
                        {[result.admin1, result.country].filter(Boolean).join(', ')}
                      </span>
                    </span>
                    <span className="num shrink-0 text-2xs text-ink-4">
                      {result.latitude.toFixed(2)}, {result.longitude.toFixed(2)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {searchError && !searching ? (
            <div className="mt-3 border border-line bg-surface-1 p-4">
              <p className="text-sm text-ink-1">{searchError}</p>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
                {t('location.searchFailedHelp')}
              </p>
              <button
                type="button"
                onClick={() => setMethod('map')}
                className="tap mt-3 inline-flex items-center gap-2 border border-line-strong px-4
                  py-2 text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
              >
                <Icon name="map-pin" size={16} />
                {t('location.pickOnMap')}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* --------------------------------------------------------------------- map */}
      {method === 'map' ? (
        <div className="mt-5">
          <p className="mb-2 text-sm text-ink-1">
            Move the map and tap where the panels will go.
          </p>
          <MapPicker
            label="Choose the location for your solar system"
            center={mapCenter}
            zoom={value?.latitude != null ? 15 : 5}
            mode="pin"
            pin={
              value?.latitude != null && value?.longitude != null
                ? { lat: value.latitude, lon: value.longitude }
                : null
            }
            onPinChange={(point) => {
              void resolveCoordinates(point.lat, point.lon, 'map');
            }}
            height={340}
          />
          {resolving ? (
            <p className="mt-2 text-xs text-ink-3" role="status">
              Looking up the place name…
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function MethodButton({
  icon,
  title,
  hint,
  active,
  onClick,
}: {
  icon: 'crosshair' | 'search' | 'map-pin';
  title: string;
  hint: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className="choice-card flex-col">
      <span className="flex w-full items-start gap-3">
        <Icon name={icon} size={22} className={active ? 'text-solar' : 'text-steel'} />
        <span className="flex-1">
          <span className="block text-sm font-medium text-ink-1">{title}</span>
          <span className="mt-1 block text-xs leading-relaxed text-ink-2">{hint}</span>
        </span>
      </span>
    </button>
  );
}
