/**
 * The icon set, drawn inline.
 *
 * No icon library. Every glyph here is one this product actually uses, drawn on the same
 * 24-unit grid with the same 1.5 stroke, which is why they sit together without looking
 * assembled from three different packs. It also keeps the bundle honest (§41): a icon
 * dependency would ship a thousand glyphs to deliver the fourteen below.
 *
 * The style deliberately avoids the childish sun-with-a-face idiom §38 rules out. These
 * are schematic — closer to a legend on a technical drawing than to a sticker.
 *
 * Icons are decorative wherever a text label sits beside them, which is everywhere in this
 * interface. They are therefore `aria-hidden` by default and never carry the meaning on
 * their own (§31).
 */

export type IconName =
  | 'home'
  | 'sprout'
  | 'store'
  | 'factory'
  | 'school'
  | 'compass'
  | 'zap'
  | 'sliders'
  | 'sun'
  | 'cloud'
  | 'cloud-sun'
  | 'cloud-rain'
  | 'layers'
  | 'car'
  | 'grid'
  | 'help-circle'
  | 'receipt'
  | 'gauge'
  | 'list'
  | 'check'
  | 'arrow-right'
  | 'arrow-left'
  | 'map-pin'
  | 'crosshair'
  | 'search'
  | 'battery'
  | 'chart'
  | 'download'
  | 'share'
  | 'menu'
  | 'close'
  | 'moon'
  | 'info'
  | 'alert'
  | 'droplet'
  | 'leaf'
  | 'wallet'
  | 'ruler'
  | 'pencil'
  | 'trash';

const PATHS: Record<IconName, React.ReactNode> = {
  home: <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />,
  sprout: (
    <>
      <path d="M12 21v-7" />
      <path d="M12 14c0-3.3-2.7-6-6-6H4v2c0 2.2 1.8 4 4 4z" />
      <path d="M12 14c0-4 3-7 7-7h1v1.5c0 3-2.5 5.5-5.5 5.5z" />
    </>
  ),
  store: (
    <>
      <path d="M3 9V7l2-4h14l2 4v2a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0z" />
      <path d="M5 11.5V21h14v-9.5" />
      <path d="M9 21v-5h4v5" />
    </>
  ),
  factory: (
    <>
      <path d="M3 21V10l5 3.5V10l5 3.5V10l5 3.5V7h3v14z" />
      <path d="M7 21v-4M12 21v-4M17 21v-4" />
    </>
  ),
  school: (
    <>
      <path d="M12 3 2 8l10 5 10-5z" />
      <path d="M6 10.5V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-5.5" />
      <path d="M21 8.5v5" />
    </>
  ),
  compass: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m15.5 8.5-2 5-5 2 2-5z" />
    </>
  ),
  zap: <path d="M13 2 4 14h6l-1 8 9-12h-6z" />,
  sliders: (
    <>
      <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="10" cy="12" r="2" />
      <circle cx="18" cy="18" r="2" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  cloud: <path d="M7 18h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.6 1.6A3.5 3.5 0 0 0 7 18z" />,
  'cloud-sun': (
    <>
      <path d="M12 4V2M5.6 6.6 4.2 5.2M19 5.2l-1.4 1.4M4 12H2" />
      <circle cx="11" cy="10" r="3" />
      <path d="M9 19h9a3.5 3.5 0 0 0 .3-7 5 5 0 0 0-9.6 1.1A3 3 0 0 0 9 19z" />
    </>
  ),
  'cloud-rain': (
    <>
      <path d="M7 15h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.6 1.6A3.5 3.5 0 0 0 7 15z" />
      <path d="M9 19v2M13 19v2M17 19v2" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 13 9 5 9-5" />
    </>
  ),
  car: (
    <>
      <path d="M4 16v-3l2-5h12l2 5v3" />
      <path d="M3 16h18v3h-3v-1H6v1H3z" />
      <circle cx="7.5" cy="16" r="1.2" />
      <circle cx="16.5" cy="16" r="1.2" />
    </>
  ),
  grid: (
    <>
      <path d="M3 3h8v8H3zM13 3h8v8h-8zM3 13h8v8H3zM13 13h8v8h-8z" />
    </>
  ),
  'help-circle': (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.4v.6" />
      <path d="M12 17.5h.01" />
    </>
  ),
  receipt: (
    <>
      <path d="M5 21V3h14v18l-2.3-1.5L14.4 21l-2.4-1.5L9.6 21l-2.3-1.5z" />
      <path d="M9 8h6M9 12h6" />
    </>
  ),
  gauge: (
    <>
      <path d="M4 18a9 9 0 1 1 16 0" />
      <path d="m12 14 4-4" />
      <circle cx="12" cy="15" r="1.4" />
    </>
  ),
  list: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />,
  check: <path d="m4 12.5 5.5 5.5L20 7" />,
  'arrow-right': <path d="M4 12h15m-6-6 6 6-6 6" />,
  'arrow-left': <path d="M20 12H5m6 6-6-6 6-6" />,
  'map-pin': (
    <>
      <path d="M12 21s7-5.7 7-11a7 7 0 1 0-14 0c0 5.3 7 11 7 11z" />
      <circle cx="12" cy="10" r="2.5" />
    </>
  ),
  crosshair: (
    <>
      <circle cx="12" cy="12" r="7" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
      <circle cx="12" cy="12" r="1.5" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  battery: (
    <>
      <rect x="2" y="7" width="17" height="10" rx="2" />
      <path d="M22 10.5v3" />
      <path d="M5.5 10v4M9 10v4" />
    </>
  ),
  chart: (
    <>
      <path d="M3 3v18h18" />
      <path d="M7 15l4-5 3 3 5-7" />
    </>
  ),
  download: <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 19h16" />,
  share: (
    <>
      <path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7" />
      <path d="M12 3v13m0-13 4 4m-4-4-4 4" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3 2 20h20z" />
      <path d="M12 10v4M12 17h.01" />
    </>
  ),
  droplet: <path d="M12 3s6 6.3 6 10a6 6 0 0 1-12 0c0-3.7 6-10 6-10z" />,
  leaf: (
    <>
      <path d="M4 20c0-9 6-14 16-14 0 10-5 15-12 15-2 0-4-.4-4-1z" />
      <path d="M9 15c2-3 5-5 8-6" />
    </>
  ),
  wallet: (
    <>
      <path d="M3 7a2 2 0 0 1 2-2h12v4" />
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H5" />
      <path d="M17 13h.01" />
    </>
  ),
  ruler: (
    <>
      <path d="M3 16.5 16.5 3 21 7.5 7.5 21z" />
      <path d="m7 12.5 2 2M10.5 9l2 2M14 5.5l2 2" />
    </>
  ),
  pencil: (
    <>
      <path d="M4 20h4L20 8l-4-4L4 16z" />
      <path d="m14 6 4 4" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16M9 7V4h6v3" />
      <path d="M6 7v13a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
};

export function Icon({
  name,
  size = 20,
  className = '',
  title,
}: {
  name: IconName;
  size?: number;
  className?: string;
  /** Only pass a title when the icon carries meaning no adjacent text supplies. */
  title?: string;
}) {
  const glyph = PATHS[name] ?? PATHS['help-circle'];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      {glyph}
    </svg>
  );
}

/**
 * The product mark: a sun elevation trace over a horizon rule.
 *
 * It is a plot, not a picture — the curve is the path of the sun across a day, which is
 * the quantity this whole platform is built on. That is the §38 brief in one glyph:
 * data as identity, rather than a decorative sunburst.
 */
export function Mark({ size = 20, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
    >
      <path
        d="M1 15 Q 10 2, 19 15"
        fill="none"
        stroke="rgb(var(--c-solar))"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <line x1="1" y1="15.5" x2="19" y2="15.5" stroke="var(--c-line-bright)" strokeWidth="1" />
      <circle cx="10" cy="5.6" r="2" fill="rgb(var(--c-solar))" />
    </svg>
  );
}
