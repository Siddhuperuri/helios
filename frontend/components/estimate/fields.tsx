'use client';

import { useId, useState } from 'react';

import { Icon, type IconName } from '@/components/site/Icon';
import type { InterviewQuestion } from '@/lib/estimate';

/**
 * Form primitives for the interview.
 *
 * Two ideas run through all of them.
 *
 * **Every technical question can be declined (§12).** `QuestionShell` renders the escape
 * route from the question's own `unknown_label` and `unknown_effect`, which come from the
 * backend alongside the question. Declining is not a dead end and not a penalty: the copy
 * states plainly what the platform will assume instead, and the uncertainty band widens to
 * match. A skip that silently changed the answer without saying so would be worse than
 * forcing the question.
 *
 * **Validation corrects rather than scolds (§46).** "Invalid input" tells somebody they
 * are wrong; "System size cannot be negative — enter a value above 0 kW" tells them what
 * to do. Messages are built from the field's own bounds and unit so they stay true when
 * the bounds change.
 */

interface ShellProps {
  question: InterviewQuestion;
  children: React.ReactNode;
  skipped: boolean;
  onSkip: (skipped: boolean) => void;
  error?: string | null;
}

export function QuestionShell({ question, children, skipped, onSkip, error }: ShellProps) {
  const [showEffect, setShowEffect] = useState(false);
  const effectId = useId();

  return (
    <div className="border-t border-line py-6 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-base font-medium text-ink-1">{question.prompt}</h3>
        {!question.required ? (
          <span className="font-mono text-2xs uppercase tracking-[0.1em] text-ink-4">
            Optional
          </span>
        ) : null}
      </div>

      {question.help_text ? (
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-2">
          {question.help_text}
        </p>
      ) : null}

      {skipped ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 border border-line bg-surface-2 px-4 py-3">
          <Icon name="info" size={16} className="text-steel" />
          <p className="flex-1 text-sm text-ink-2">
            {question.unknown_effect ?? 'We will use a sensible default and say so in your results.'}
          </p>
          <button
            type="button"
            onClick={() => onSkip(false)}
            className="border border-line px-2.5 py-1.5 text-xs text-ink-1 transition-colors
              hover:border-solar hover:text-solar"
          >
            Answer it after all
          </button>
        </div>
      ) : (
        <>
          <div className="mt-4">{children}</div>

          {error ? (
            <p
              role="alert"
              className="mt-2 flex items-start gap-2 text-sm text-critical"
            >
              <Icon name="alert" size={16} className="mt-0.5" />
              <span>{error}</span>
            </p>
          ) : null}

          {question.unknown_label ? (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <button
                type="button"
                onClick={() => onSkip(true)}
                className="text-sm text-ink-2 underline decoration-line-bright underline-offset-4
                  transition-colors hover:text-solar hover:decoration-solar"
              >
                {question.unknown_label}
              </button>
              {question.unknown_effect ? (
                <>
                  <button
                    type="button"
                    onClick={() => setShowEffect((v) => !v)}
                    aria-expanded={showEffect}
                    aria-controls={effectId}
                    className="text-xs text-ink-3 transition-colors hover:text-ink-1"
                  >
                    What happens if I skip this?
                  </button>
                  {showEffect ? (
                    <p
                      id={effectId}
                      className="w-full border-l-2 border-line-strong pl-3 text-xs leading-relaxed
                        text-ink-2"
                    >
                      {question.unknown_effect}
                    </p>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Choice
// --------------------------------------------------------------------------------------

export function ChoiceField({
  question,
  value,
  onChange,
  columns = 2,
}: {
  question: InterviewQuestion;
  value: string | null;
  onChange: (value: string) => void;
  columns?: 1 | 2 | 3;
}) {
  const gridClass =
    columns === 3
      ? 'sm:grid-cols-3'
      : columns === 2
        ? 'sm:grid-cols-2'
        : '';

  return (
    <ul className={`grid gap-2.5 ${gridClass}`}>
      {question.options.map((option) => {
        const selected = value === option.value;
        return (
          <li key={option.value}>
            <button
              type="button"
              onClick={() => onChange(option.value)}
              aria-pressed={selected}
              className="choice-card h-full"
            >
              {option.icon ? (
                <Icon
                  name={option.icon as IconName}
                  size={20}
                  className={selected ? 'text-solar' : 'text-steel'}
                />
              ) : null}
              <span className="flex-1">
                <span className="block text-sm font-medium text-ink-1">{option.label}</span>
                {option.description ? (
                  <span className="mt-0.5 block text-xs leading-relaxed text-ink-2">
                    {option.description}
                  </span>
                ) : null}
              </span>
              {selected ? (
                <Icon name="check" size={16} className="text-solar" title="Selected" />
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Several answers at once — "what are you powering?" on a farm is rarely one thing.
 *
 * Rendered as toggles rather than checkboxes so the target is the whole card, which is
 * what a thumb hits. `aria-pressed` carries the state, and the check mark carries it
 * visually, so selection never depends on colour alone (§31).
 */
export function MultiChoiceField({
  question,
  value,
  onChange,
}: {
  question: InterviewQuestion;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  function toggle(option: string) {
    onChange(
      value.includes(option) ? value.filter((v) => v !== option) : [...value, option],
    );
  }

  return (
    <>
      <ul className="grid gap-2.5 sm:grid-cols-2">
        {question.options.map((option) => {
          const selected = value.includes(option.value);
          return (
            <li key={option.value}>
              <button
                type="button"
                onClick={() => toggle(option.value)}
                aria-pressed={selected}
                className="choice-card h-full"
              >
                {option.icon ? (
                  <Icon
                    name={option.icon as IconName}
                    size={20}
                    className={selected ? 'text-solar' : 'text-steel'}
                  />
                ) : null}
                <span className="flex-1">
                  <span className="block text-sm font-medium text-ink-1">{option.label}</span>
                  {option.description ? (
                    <span className="mt-0.5 block text-xs leading-relaxed text-ink-2">
                      {option.description}
                    </span>
                  ) : null}
                </span>
                {selected ? (
                  <Icon name="check" size={16} className="text-solar" title="Selected" />
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
      {value.length > 0 ? (
        <p className="mt-2.5 text-xs text-ink-3">
          {value.length} selected. Tap again to remove.
        </p>
      ) : null}
    </>
  );
}

// --------------------------------------------------------------------------------------
// Numbers
// --------------------------------------------------------------------------------------

/**
 * Build a correction, not a complaint (§46).
 *
 * Returns null when the value is acceptable. The message names the field in the words the
 * question used, states the bound, and gives the unit, so the reader knows exactly what to
 * type next.
 */
export function validateNumber(
  question: InterviewQuestion,
  raw: string,
): { value: number | null; error: string | null } {
  const trimmed = raw.trim();
  if (trimmed === '') {
    return {
      value: null,
      error: question.required ? `${question.prompt.replace(/\?$/, '')} is needed to continue.` : null,
    };
  }

  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { value: null, error: `Enter a number${question.unit ? ` in ${question.unit}` : ''}.` };
  }

  const unit = question.unit ? ` ${question.unit}` : '';

  if (value < 0) {
    return {
      value: null,
      error: `This cannot be negative. Enter a value above 0${unit}.`,
    };
  }
  if (question.min_value !== null && value < question.min_value) {
    return {
      value: null,
      error:
        value === 0
          ? `This cannot be zero. Enter a value of at least ${question.min_value}${unit}.`
          : `That is below the smallest value we can use. Enter at least ${question.min_value}${unit}.`,
    };
  }
  if (question.max_value !== null && value > question.max_value) {
    return {
      value: null,
      error: `That is larger than we can model. Enter at most ${question.max_value}${unit}.`,
    };
  }
  return { value, error: null };
}

export function NumberField({
  question,
  value,
  onChange,
  prefix,
  error,
}: {
  question: InterviewQuestion;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  prefix?: string;
  error?: string | null;
}) {
  const id = useId();
  const [text, setText] = useState(value != null ? String(value) : '');

  return (
    <div className="max-w-sm">
      <div className="flex items-stretch">
        {prefix ? (
          <span
            className="num flex items-center border border-r-0 border-line-strong bg-surface-2
              px-3 text-base text-ink-2"
            aria-hidden="true"
          >
            {prefix}
          </span>
        ) : null}
        <input
          id={id}
          type="number"
          inputMode="decimal"
          value={text}
          min={question.min_value ?? undefined}
          max={question.max_value ?? undefined}
          aria-invalid={error ? true : undefined}
          aria-label={question.prompt}
          onChange={(event) => {
            setText(event.target.value);
            const parsed = validateNumber(question, event.target.value);
            onChange(parsed.value);
          }}
          className="num w-full border border-line-strong bg-surface-1 px-3 py-3 text-base
            text-ink-1 placeholder:text-ink-4 focus:border-solar focus:outline-none"
        />
        {question.unit ? (
          <span
            className="flex items-center border border-l-0 border-line-strong bg-surface-2 px-3
              text-sm text-ink-2"
          >
            {question.unit}
          </span>
        ) : null}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------------------
// Boolean
// --------------------------------------------------------------------------------------

export function BooleanField({
  value,
  onChange,
  yesLabel = 'Yes',
  noLabel = 'No',
}: {
  value: boolean | null | undefined;
  onChange: (value: boolean) => void;
  yesLabel?: string;
  noLabel?: string;
}) {
  return (
    <div className="flex gap-2.5">
      {[
        { label: yesLabel, val: true },
        { label: noLabel, val: false },
      ].map((option) => (
        <button
          key={String(option.val)}
          type="button"
          onClick={() => onChange(option.val)}
          aria-pressed={value === option.val}
          className="choice-card w-auto min-w-[7rem] items-center justify-center"
        >
          {value === option.val ? (
            <Icon name="check" size={16} className="text-solar" title="Selected" />
          ) : null}
          <span className="text-sm font-medium text-ink-1">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
