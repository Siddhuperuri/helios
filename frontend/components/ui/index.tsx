'use client';

import { ReactNode, useId, useState } from 'react';

import { num } from '@/lib/format';

/* ------------------------------------------------------------- section */

export function Section({
  label,
  title,
  description,
  children,
  actions,
  id,
}: {
  label: string;
  title?: string;
  description?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className="scroll-mt-20">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <p className="eyebrow mb-2">{label}</p>
          {title ? (
            <h2 className="text-xl font-medium tracking-tight text-ink-1">{title}</h2>
          ) : null}
          {description ? (
            <div className="mt-1.5 max-w-3xl text-sm leading-relaxed text-ink-2">
              {description}
            </div>
          ) : null}
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/* --------------------------------------------------------------- panel */

export function Panel({
  children,
  className = '',
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div className={`panel ${padded ? 'p-4 sm:p-5' : ''} ${className}`}>{children}</div>
  );
}

/* -------------------------------------------------------------- metric */

/**
 * A single headline figure.
 *
 * `hint` exists so no number appears without its interpretation attached. A bare
 * "0.916" tells a reader nothing about whether that is good.
 */
export function Metric({
  label,
  value,
  unit,
  hint,
  tone = 'neutral',
  size = 'md',
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: ReactNode;
  tone?: 'neutral' | 'positive' | 'warning' | 'critical' | 'accent';
  size?: 'sm' | 'md' | 'lg';
}) {
  const toneClass = {
    neutral: 'text-ink-1',
    positive: 'text-positive',
    warning: 'text-warning',
    critical: 'text-critical',
    accent: 'text-solar',
  }[tone];

  const sizeClass = {
    sm: 'text-lg',
    md: 'text-2xl',
    lg: 'text-3xl',
  }[size];

  return (
    <div className="min-w-0">
      <dt className="mb-1.5 font-mono text-2xs uppercase tracking-[0.12em] text-ink-3">
        {label}
      </dt>
      <dd>
        <span className={`num font-medium tabular-nums ${sizeClass} ${toneClass}`}>
          {value}
        </span>
        {unit ? <span className="ml-1.5 text-xs text-ink-3">{unit}</span> : null}
        {hint ? <p className="mt-1.5 text-2xs leading-relaxed text-ink-4">{hint}</p> : null}
      </dd>
    </div>
  );
}

export function MetricGrid({
  children,
  cols = 4,
}: {
  children: ReactNode;
  cols?: 2 | 3 | 4 | 5;
}) {
  const colClass = {
    2: 'sm:grid-cols-2',
    3: 'sm:grid-cols-2 lg:grid-cols-3',
    4: 'sm:grid-cols-2 lg:grid-cols-4',
    5: 'sm:grid-cols-3 lg:grid-cols-5',
  }[cols];
  return <dl className={`grid grid-cols-2 gap-x-6 gap-y-6 ${colClass}`}>{children}</dl>;
}

/* ----------------------------------------------------------------- tag */

export function Tag({
  children,
  tone = 'neutral',
  title,
}: {
  children: ReactNode;
  tone?: 'neutral' | 'positive' | 'warning' | 'critical' | 'accent' | 'info';
  title?: string;
}) {
  const toneClass = {
    neutral: 'border-line-strong text-ink-3',
    positive: 'border-positive/40 text-positive',
    warning: 'border-warning/45 text-warning',
    critical: 'border-critical/45 text-critical',
    accent: 'border-solar/45 text-solar',
    info: 'border-cyan/40 text-cyan',
  }[tone];
  return (
    <span className={`tag ${toneClass}`} title={title}>
      {children}
    </span>
  );
}

export function severityTone(
  severity: string,
): 'positive' | 'warning' | 'critical' | 'neutral' {
  if (severity === 'pass' || severity === 'protected' || severity === 'low') return 'positive';
  if (severity === 'warn' || severity === 'mitigated' || severity === 'medium') return 'warning';
  if (severity === 'fail' || severity === 'at_risk' || severity === 'high') return 'critical';
  return 'neutral';
}

/* ------------------------------------------------------------- callout */

export function Callout({
  tone = 'info',
  title,
  children,
  compact = false,
}: {
  tone?: 'info' | 'warning' | 'critical' | 'positive' | 'simulation';
  title?: string;
  children: ReactNode;
  compact?: boolean;
}) {
  const config = {
    info: { border: 'border-l-cyan', label: 'text-cyan' },
    warning: { border: 'border-l-warning', label: 'text-warning' },
    critical: { border: 'border-l-critical', label: 'text-critical' },
    positive: { border: 'border-l-positive', label: 'text-positive' },
    simulation: { border: 'border-l-solar', label: 'text-solar' },
  }[tone];

  return (
    <div
      className={`border-y border-r border-line border-l-2 ${config.border} bg-surface-1
        ${compact ? 'px-3 py-2' : 'px-4 py-3'}`}
      role={tone === 'critical' ? 'alert' : undefined}
    >
      {title ? (
        <p
          className={`mb-1 font-mono text-2xs uppercase tracking-[0.12em] ${config.label}`}
        >
          {title}
        </p>
      ) : null}
      <div className="text-xs leading-relaxed text-ink-2">{children}</div>
    </div>
  );
}

/* ---------------------------------------------------------- info popup */

/** An inline definition, revealed on demand. Keeps dense views readable. */
export function Info({ children, label = 'What is this?' }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="ml-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full
          border border-line-strong text-[9px] leading-none text-ink-3 transition-colors
          hover:border-solar hover:text-solar"
      >
        <span aria-hidden="true">i</span>
        <span className="sr-only">{label}</span>
      </button>
      {open ? (
        <span
          id={id}
          role="tooltip"
          className="absolute left-0 top-6 z-30 block w-64 border border-line-strong
            bg-surface-2 p-3 text-2xs leading-relaxed text-ink-2 shadow-xl"
        >
          {children}
        </span>
      ) : null}
    </span>
  );
}

/* --------------------------------------------------------------- table */

export function DataTable({
  columns,
  rows,
  caption,
  dense = false,
}: {
  columns: { key: string; label: string; numeric?: boolean; width?: string }[];
  rows: Record<string, ReactNode>[];
  caption?: string;
  dense?: boolean;
}) {
  if (!rows.length) {
    return <EmptyState message="No rows to display." />;
  }
  return (
    <div className="scroll-x">
      <table className="data-table">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={c.numeric ? 'numeric' : ''}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={`${c.numeric ? 'numeric' : ''} ${dense ? 'py-1.5' : ''}`}>
                  {row[c.key] ?? '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------------------------------------------------- states */

export function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 border border-dashed
      border-line px-6 py-10 text-center">
      <p className="max-w-sm text-xs leading-relaxed text-ink-3">{message}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title = 'Could not complete this step',
  message,
  detail,
  remedy,
  onRetry,
}: {
  title?: string;
  message: string;
  detail?: string;
  remedy?: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="border-y border-r border-line border-l-2 border-l-critical bg-surface-1 p-4">
      <p className="mb-1.5 font-mono text-2xs uppercase tracking-[0.12em] text-critical">
        {title}
      </p>
      <p className="text-sm leading-relaxed text-ink-1">{message}</p>
      {remedy ? <p className="mt-2 text-xs leading-relaxed text-ink-2">{remedy}</p> : null}
      {detail ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-2xs text-ink-4 hover:text-ink-2">
            Technical detail
          </summary>
          <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-words text-2xs text-ink-4">
            {detail}
          </pre>
        </details>
      ) : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 border border-line-strong px-3 py-1.5 text-xs text-ink-1
            transition-colors hover:border-solar hover:text-solar"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Skeleton({
  lines = 3,
  className = '',
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="relative h-3 overflow-hidden bg-surface-2">
          <div className="absolute inset-0 animate-sweep bg-gradient-to-r from-transparent
            via-white/[0.045] to-transparent" />
        </div>
      ))}
    </div>
  );
}

export function LoadingPanel({ message }: { message: string }) {
  return (
    <div className="panel p-5" role="status" aria-live="polite">
      <p className="mb-3 flex items-center gap-2 text-xs text-ink-2">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-solar opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-solar" />
        </span>
        {message}
      </p>
      <Skeleton lines={4} />
    </div>
  );
}

/* -------------------------------------------------------------- inputs */

export function Field({
  label,
  hint,
  children,
  htmlFor,
  error,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
  error?: string;
}) {
  return (
    <div className="min-w-0">
      <label
        htmlFor={htmlFor}
        className="mb-1.5 block font-mono text-2xs uppercase tracking-[0.1em] text-ink-3"
      >
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-2xs text-critical">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-2xs leading-relaxed text-ink-4">{hint}</p>
      ) : null}
    </div>
  );
}

const inputClass =
  'w-full border border-line-strong bg-surface-2 px-2.5 py-2 text-sm text-ink-1 ' +
  'transition-colors placeholder:text-ink-4 hover:border-line-bright focus:border-solar ' +
  'focus:outline-none disabled:cursor-not-allowed disabled:opacity-50';

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputClass} ${props.className ?? ''}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={`${inputClass} appearance-none ${props.className ?? ''}`}>
      {props.children}
    </select>
  );
}

export function Button({
  variant = 'secondary',
  size = 'md',
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md';
}) {
  const variantClass = {
    primary:
      'border-solar bg-solar text-base font-medium hover:bg-solar-bright hover:border-solar-bright',
    secondary: 'border-line-strong text-ink-1 hover:border-solar hover:text-solar',
    ghost: 'border-transparent text-ink-2 hover:text-ink-1 hover:bg-surface-2',
  }[variant];
  const sizeClass = size === 'sm' ? 'px-2.5 py-1 text-2xs' : 'px-3.5 py-2 text-xs';
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 border transition-colors
        disabled:cursor-not-allowed disabled:opacity-45 ${variantClass} ${sizeClass}
        ${props.className ?? ''}`}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------- score display */

/** Data-quality score with its own scale drawn beneath it. */
export function ScoreBar({
  score,
  grade,
  counts,
}: {
  score: number;
  grade: string;
  counts?: { pass: number; warn: number; fail: number };
}) {
  const tone =
    score >= 95 ? 'text-positive' : score >= 85 ? 'text-ink-1' : score >= 70 ? 'text-warning' : 'text-critical';
  const barColor =
    score >= 95 ? '#46A56A' : score >= 85 ? '#8FA8BF' : score >= 70 ? '#D99A2B' : '#D9534F';

  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className={`num text-3xl font-medium ${tone}`}>{num(score, 1)}</span>
        <span className="text-xs text-ink-3">%</span>
        <span className="ml-auto text-xs text-ink-2">{grade}</span>
      </div>
      <div className="mt-2 h-1 w-full bg-surface-3">
        <div
          className="h-full transition-[width] duration-700 ease-out"
          style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: barColor }}
        />
      </div>
      {counts ? (
        <p className="mt-2 font-mono text-2xs text-ink-4">
          {counts.pass} passed · {counts.warn} warnings · {counts.fail} failures
        </p>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- misc */

export function KeyValue({
  items,
  columns = 2,
}: {
  items: { label: string; value: ReactNode; mono?: boolean }[];
  columns?: 1 | 2 | 3;
}) {
  const colClass = { 1: '', 2: 'sm:grid-cols-2', 3: 'sm:grid-cols-2 lg:grid-cols-3' }[columns];
  return (
    <dl className={`grid grid-cols-1 gap-x-8 gap-y-3 ${colClass}`}>
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline justify-between gap-4 border-b border-line pb-2">
          <dt className="text-xs text-ink-3">{item.label}</dt>
          <dd className={`text-right text-xs text-ink-1 ${item.mono !== false ? 'num' : ''}`}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function StatusDot({ tone }: { tone: 'positive' | 'warning' | 'critical' | 'neutral' }) {
  const color = {
    positive: 'bg-positive',
    warning: 'bg-warning',
    critical: 'bg-critical',
    neutral: 'bg-ink-4',
  }[tone];
  return <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${color}`} aria-hidden="true" />;
}
