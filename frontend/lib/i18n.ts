/**
 * Localisation scaffold (§33).
 *
 * The requirement is architectural rather than immediate: ship English, but do not build
 * something that has to be torn apart to add Telugu. Two decisions make that true.
 *
 * **Interface strings live here, keyed, not inline in components.** A component asks for
 * `t('landing.headline')`. Adding a language means adding one dictionary, not auditing
 * every file for quoted text.
 *
 * **Content strings come from the API already localised.** The interview questions, the
 * appliance names, the assumption labels and the plain-language explanations are all
 * served by the backend (see `app/estimate/personas.py`). That is deliberate: those
 * strings are generated alongside the numbers they describe, and a translation layer that
 * only covered the chrome while the actual answer stayed in English would be worse than
 * none.
 *
 * Numbers and currency are formatted through `Intl` with the active locale rather than
 * hand-assembled, because digit grouping differs — Indian locales group as 1,53,500 where
 * en-US gives 153,500, and a rupee figure grouped the American way looks wrong to the
 * person reading it.
 */

export type Locale = 'en' | 'te' | 'hi' | 'ta' | 'kn' | 'ml' | 'mr' | 'bn';

export const LOCALES: { code: Locale; name: string; english: string; ready: boolean }[] = [
  { code: 'en', name: 'English', english: 'English', ready: true },
  { code: 'te', name: 'తెలుగు', english: 'Telugu', ready: false },
  { code: 'hi', name: 'हिन्दी', english: 'Hindi', ready: false },
  { code: 'ta', name: 'தமிழ்', english: 'Tamil', ready: false },
  { code: 'kn', name: 'ಕನ್ನಡ', english: 'Kannada', ready: false },
  { code: 'ml', name: 'മലയാളം', english: 'Malayalam', ready: false },
  { code: 'mr', name: 'मराठी', english: 'Marathi', ready: false },
  { code: 'bn', name: 'বাংলা', english: 'Bengali', ready: false },
];

/** Locale used for number and currency formatting, per UI locale. */
const NUMBER_LOCALES: Record<Locale, string> = {
  en: 'en-IN',
  te: 'te-IN',
  hi: 'hi-IN',
  ta: 'ta-IN',
  kn: 'kn-IN',
  ml: 'ml-IN',
  mr: 'mr-IN',
  bn: 'bn-IN',
};

const en = {
  brand: 'Helios',
  nav: {
    home: 'Home',
    calculator: 'Solar Calculator',
    howItWorks: 'How It Works',
    projects: 'My Analyses',
    resources: 'Resources',
    about: 'About',
    console: 'Analysis Console',
    menu: 'Menu',
    close: 'Close',
  },
  landing: {
    eyebrow: 'Solar energy intelligence',
    headline: 'Know how much solar your location can produce.',
    subhead:
      'Get a personalised solar-energy estimate using your location, weather, solar resources, system characteristics and energy usage.',
    primaryCta: 'Calculate My Solar Potential',
    secondaryCta: 'Explore How It Works',
    promise: 'Tell us what you have. We will figure out the solar.',
    noSignup: 'No account needed. Takes about two minutes.',
  },
  start: {
    title: 'What are you planning to power?',
    subtitle: 'This decides what we ask you next — nothing more.',
    modeTitle: 'How much detail do you want to give?',
    modeSubtitle: 'You can change this later, and you can skip any question.',
    back: 'Back',
  },
  wizard: {
    step: 'Step',
    of: 'of',
    next: 'Continue',
    back: 'Back',
    skip: 'Skip this',
    calculate: 'Calculate my solar potential',
    dontKnow: 'I do not know',
    dontKnowEffect: 'What happens if I skip this?',
    required: 'Needed to continue',
    optional: 'Optional',
  },
  location: {
    title: 'Where will the solar panels be?',
    useMyLocation: 'Use my location',
    useMyLocationHint: 'Fastest, if you are at the site.',
    search: 'Search for a place',
    searchHint: 'Village, town, city, district or postal code.',
    pickOnMap: 'Pick on the map',
    pickOnMapHint: 'Drop a pin exactly where the panels will go.',
    found: 'Location found',
    locating: 'Finding your location…',
    permissionDenied: 'We could not access your location.',
    permissionDeniedHelp:
      'No problem — search for your place instead, or point to it on the map.',
    searchFailed: 'That search did not return anything.',
    searchFailedHelp: 'Try a larger nearby town, or add the state or country.',
    elevation: 'Elevation',
    coordinates: 'Coordinates',
    change: 'Change location',
  },
  loading: {
    title: 'Working out your solar potential',
    subtitle: 'This usually takes a few seconds.',
    stages: {
      location: 'Finding your location',
      weather: 'Fetching solar resource data',
      analysing: 'Analysing weather patterns',
      performance: 'Estimating system performance',
      generation: 'Calculating expected generation',
      report: 'Preparing your solar report',
    },
    slow:
      'This location is new to us, so we are downloading several years of weather history. It is quicker next time.',
  },
  result: {
    title: 'Your Solar Potential',
    recommendedSystem: 'Recommended system',
    annualGeneration: 'Expected annual generation',
    expectedRange: 'Expected range',
    confidence: 'Confidence',
    dailyAverage: 'Average daily generation',
    monthlyAverage: 'Expected monthly average',
    offset: 'Estimated electricity offset',
    co2: 'Estimated CO₂ reduction',
    savings: 'Estimated savings',
    payback: 'Payback period',
    whatThisMeans: 'What does this mean?',
    whatAffects: 'What could affect this result?',
    tabs: {
      generation: 'Generation',
      savings: 'Savings',
      system: 'System Size',
      weather: 'Weather',
      assumptions: 'Assumptions',
      scenarios: 'Scenarios',
      report: 'Report',
    },
    save: 'Save this analysis',
    share: 'Copy share link',
    shared: 'Link copied',
    download: 'Download report',
    startOver: 'Start a new estimate',
  },
  projects: {
    title: 'My Solar Projects',
    empty: 'You have no saved analyses yet.',
    emptyCta: 'Run your first estimate',
    lastUpdated: 'Last updated',
    rename: 'Rename',
    delete: 'Delete',
    confirmDelete: 'Delete this analysis? This cannot be undone.',
  },
  errors: {
    generic: 'Something went wrong at our end.',
    offline: 'You appear to be offline.',
    offlineHelp: 'Check your connection and try again — nothing you entered has been lost.',
    retry: 'Try again',
    weatherUnavailable: 'The weather service is not responding.',
    weatherUnavailableHelp:
      'This is usually temporary. Your answers are saved, so you can retry in a moment.',
  },
  units: {
    kwh: 'kWh',
    mwh: 'MWh',
    kw: 'kW',
    kwp: 'kWp',
    perYear: '/year',
    perMonth: '/month',
    perDay: '/day',
    tonnes: 'tonnes',
    years: 'years',
    sqm: 'm²',
    sqft: 'sq ft',
  },
  confidence: {
    high: 'High',
    medium: 'Medium',
    low: 'Low',
  },
} as const;

export type Dictionary = typeof en;

/**
 * Dictionaries for other languages are absent rather than machine-filled. A partially
 * translated interface that silently falls back mid-sentence reads as broken; showing
 * English until a language is genuinely complete is the more respectful failure.
 */
const DICTIONARIES: Partial<Record<Locale, Dictionary>> = { en };

export function dictionary(locale: Locale = 'en'): Dictionary {
  return DICTIONARIES[locale] ?? en;
}

/** Dot-path lookup, so components read `t('result.tabs.savings')`. */
export function translate(locale: Locale, path: string): string {
  const parts = path.split('.');
  let node: unknown = dictionary(locale);
  for (const part of parts) {
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) {
      node = (node as Record<string, unknown>)[part];
    } else {
      // A missing key is a bug, not a user-facing state. Surfacing the key makes it
      // obvious in development rather than rendering an empty element.
      return path;
    }
  }
  return typeof node === 'string' ? node : path;
}

export function numberLocale(locale: Locale = 'en'): string {
  return NUMBER_LOCALES[locale] ?? 'en-IN';
}

/** Format a currency amount with the symbol placement the currency actually uses. */
export function formatCurrency(
  value: number | null | undefined,
  currency: { code: string; symbol: string; symbol_position?: string },
  locale: Locale = 'en',
  maximumFractionDigits = 0,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const formatted = value.toLocaleString(numberLocale(locale), {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  });
  return currency.symbol_position === 'suffix'
    ? `${formatted} ${currency.symbol}`
    : `${currency.symbol}${formatted}`;
}

/**
 * Energy, at a scale a person can hold in their head. 18,420 kWh is harder to read than
 * 18.4 MWh, and both are the same number.
 */
export function formatEnergy(
  kwh: number | null | undefined,
  locale: Locale = 'en',
  opts: { forceUnit?: 'kWh' | 'MWh' } = {},
): { value: string; unit: string } {
  if (kwh === null || kwh === undefined || !Number.isFinite(kwh)) {
    return { value: '—', unit: 'kWh' };
  }
  const useMwh =
    opts.forceUnit === 'MWh' || (opts.forceUnit !== 'kWh' && Math.abs(kwh) >= 10_000);
  const value = useMwh ? kwh / 1000 : kwh;
  return {
    value: value.toLocaleString(numberLocale(locale), {
      maximumFractionDigits: useMwh ? 1 : 0,
    }),
    unit: useMwh ? 'MWh' : 'kWh',
  };
}
