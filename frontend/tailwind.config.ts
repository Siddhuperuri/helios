import type { Config } from 'tailwindcss';

/**
 * Design tokens for Helios.
 *
 * Art direction (§38): a scientific instrument that a non-specialist can read. The
 * references are meteorological data products, laboratory equipment panels, and Swiss
 * editorial typography — not the rounded-card-and-gradient idiom, and emphatically not the
 * green-leaf-and-stock-photo sustainability template.
 *
 * Four rules the palette enforces:
 *
 * 1. Amber is the model. Every predicted, modelled or simulated quantity is amber; every
 *    measured quantity is steel. A reader can tell observation from inference by colour
 *    alone, before reading a legend. This is why the accent is not the conventional
 *    blue-violet: that hue carries no meaning here, and amber reads as energy.
 * 2. Structure comes from hairlines, not boxes. Panels are separated by 1px rules at low
 *    opacity rather than by borders, shadows and radii on every element.
 * 3. Numbers are monospaced. In an analysis tool figures are the content, and tabular
 *    figures let columns align and be compared down a page.
 * 4. Both themes are first-class. Colours resolve through CSS custom properties defined in
 *    globals.css, so a single class works in either. Light is not an afterthought here:
 *    a farmer standing in a field reads a phone in direct sunlight, and §32 asks for that
 *    case specifically.
 *
 * Colours are declared as space-separated RGB channels so Tailwind's alpha modifiers
 * (`bg-base/95`) keep working across both themes.
 */
const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: 'rgb(var(--c-base) / <alpha-value>)',
        surface: {
          1: 'rgb(var(--c-surface-1) / <alpha-value>)',
          2: 'rgb(var(--c-surface-2) / <alpha-value>)',
          3: 'rgb(var(--c-surface-3) / <alpha-value>)',
          4: 'rgb(var(--c-surface-4) / <alpha-value>)',
        },
        line: {
          DEFAULT: 'var(--c-line)',
          strong: 'var(--c-line-strong)',
          bright: 'var(--c-line-bright)',
        },
        ink: {
          // Every tone clears WCAG AA (4.5:1) against its own ground, in both themes,
          // because all four are used for real text at small sizes — metric hints and
          // chart footnotes carry methodological caveats and are not decoration. There is
          // deliberately no sub-AA tone: hierarchy is carried by size and weight as well
          // as colour, so nothing depends on colour alone (§31).
          1: 'rgb(var(--c-ink-1) / <alpha-value>)',
          2: 'rgb(var(--c-ink-2) / <alpha-value>)',
          3: 'rgb(var(--c-ink-3) / <alpha-value>)',
          4: 'rgb(var(--c-ink-4) / <alpha-value>)',
        },
        // Semantic data colours
        solar: {
          DEFAULT: 'rgb(var(--c-solar) / <alpha-value>)', // model / predicted / energy
          bright: 'rgb(var(--c-solar-bright) / <alpha-value>)',
          dim: 'rgb(var(--c-solar-dim) / <alpha-value>)',
        },
        steel: {
          DEFAULT: 'rgb(var(--c-steel) / <alpha-value>)', // measured / observed
          bright: 'rgb(var(--c-steel-bright) / <alpha-value>)',
          dim: 'rgb(var(--c-steel-dim) / <alpha-value>)',
        },
        cyan: {
          DEFAULT: 'rgb(var(--c-cyan) / <alpha-value>)', // secondary series
          dim: 'rgb(var(--c-cyan-dim) / <alpha-value>)',
        },
        positive: 'rgb(var(--c-positive) / <alpha-value>)',
        warning: 'rgb(var(--c-warning) / <alpha-value>)',
        critical: 'rgb(var(--c-critical) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['var(--font-plex-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-plex-mono)', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // A deliberately tight scale. Scientific interfaces are dense; a sprawling
        // type scale produces the airy marketing look this is avoiding. The consumer
        // surface steps up from `base` rather than introducing a second scale.
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
        xs: ['0.75rem', { lineHeight: '1.1rem' }],
        sm: ['0.8125rem', { lineHeight: '1.25rem' }],
        base: ['0.875rem', { lineHeight: '1.4rem' }],
        lg: ['1rem', { lineHeight: '1.5rem' }],
        xl: ['1.25rem', { lineHeight: '1.7rem', letterSpacing: '-0.01em' }],
        '2xl': ['1.625rem', { lineHeight: '2rem', letterSpacing: '-0.02em' }],
        '3xl': ['2.25rem', { lineHeight: '2.5rem', letterSpacing: '-0.025em' }],
        '4xl': ['3rem', { lineHeight: '3.1rem', letterSpacing: '-0.03em' }],
        '5xl': ['3.75rem', { lineHeight: '3.85rem', letterSpacing: '-0.035em' }],
      },
      borderRadius: {
        none: '0',
        sm: '2px',
        DEFAULT: '3px',
        md: '4px',
        lg: '6px',
      },
      spacing: {
        rail: '13.5rem',
        // Minimum comfortable touch target (§31, §32). Named rather than repeated as a
        // magic number, so it cannot quietly shrink.
        touch: '2.75rem',
      },
      transitionDuration: {
        fast: '120ms',
        DEFAULT: '180ms',
      },
      keyframes: {
        'fade-rise': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        sweep: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        draw: {
          '0%': { strokeDashoffset: '1' },
          '100%': { strokeDashoffset: '0' },
        },
        'stage-in': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-rise': 'fade-rise 220ms cubic-bezier(0.22, 1, 0.36, 1) both',
        sweep: 'sweep 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        'stage-in': 'stage-in 260ms cubic-bezier(0.22, 1, 0.36, 1) both',
      },
    },
  },
  plugins: [],
};

export default config;
