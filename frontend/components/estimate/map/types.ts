/**
 * The map contract.
 *
 * One interface, two possible implementations. The default is a hand-rolled tile map
 * (`TileMap`) that costs nothing in bundle size and matches a codebase which already
 * declines a charting library and draws its own SVG. A Leaflet-backed adapter can be
 * swapped in behind the same props if the hand-rolled one ever proves unequal to a device
 * — the seam exists so that is a one-line change rather than a rewrite of every caller.
 *
 * Nothing above this file knows which implementation is mounted.
 */

export interface LatLon {
  lat: number;
  lon: number;
}

export type MapMode = 'pin' | 'polygon';

export interface MapPickerProps {
  /** Where the map opens. */
  center: LatLon;
  /** Initial zoom. 13 shows a town; 17 shows individual rooftops. */
  zoom?: number;
  /** Dropping a pin, or tracing an area. */
  mode?: MapMode;
  /** The currently placed pin, if any. */
  pin?: LatLon | null;
  /** The polygon being traced, in order. */
  polygon?: LatLon[];
  onPinChange?: (pin: LatLon) => void;
  onPolygonChange?: (polygon: LatLon[]) => void;
  /** Height of the map viewport. Width always fills the container. */
  height?: number;
  className?: string;
  /** Accessible description of what this particular map is for. */
  label: string;
}
