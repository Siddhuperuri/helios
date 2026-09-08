'use client';

import { useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/site/Icon';

/**
 * The wait, made legible (§40).
 *
 * "Loading…" tells somebody nothing except that they should keep waiting. Naming the
 * stages does three useful things at once: it says the work is real and specific, it sets
 * an expectation of length, and when something goes wrong it says *where*.
 *
 * The honesty problem this component has to solve: the backend produces one response, not
 * a stream, so the client cannot know exactly which stage is running. Faking precise
 * progress would be a lie — and a familiar one, since a progress bar that jumps to 90 %
 * and sits there is how most software lies about this.
 *
 * What it does instead is advance stages on a schedule drawn from measured timings of the
 * real pipeline, and then hold at the last stage rather than completing. Nothing is ever
 * shown as finished unless it has finished: the final tick appears only when the response
 * actually lands. If the work outruns the schedule the last stage simply keeps running,
 * which is true, rather than showing 100 % while still waiting.
 */

export interface Stage {
  key: string;
  label: string;
  /** Seconds this stage typically takes, from measured pipeline timings. */
  seconds: number;
}

/**
 * Durations come from instrumenting the pipeline: location resolution is fast, the weather
 * fetch dominates a first visit to a location and is near-instant when cached, and the
 * orientation search and yield calculation are about a second between them.
 */
export const DEFAULT_STAGES: Stage[] = [
  { key: 'location', label: 'Finding your location', seconds: 1.5 },
  { key: 'weather', label: 'Fetching solar resource data', seconds: 8 },
  { key: 'analysing', label: 'Analysing weather patterns', seconds: 3 },
  { key: 'performance', label: 'Estimating system performance', seconds: 2.5 },
  { key: 'generation', label: 'Calculating expected generation', seconds: 2 },
  { key: 'report', label: 'Preparing your solar report', seconds: 2 },
];

export function LoadingStages({
  stages = DEFAULT_STAGES,
  done = false,
  title = 'Working out your solar potential',
  subtitle = 'This usually takes a few seconds.',
}: {
  stages?: Stage[];
  /** Set when the response has actually arrived. Only then does the last stage tick. */
  done?: boolean;
  title?: string;
  subtitle?: string;
}) {
  const [active, setActive] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(Date.now());

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    let cumulative = 0;
    stages.forEach((stage, index) => {
      if (index === 0) return;
      cumulative += stages[index - 1]!.seconds;
      timers.push(
        setTimeout(() => {
          // Never advance past the last stage on the timer alone — that one is held until
          // the response lands.
          setActive((current) => Math.max(current, Math.min(index, stages.length - 1)));
        }, cumulative * 1000),
      );
    });

    const tick = setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAt.current) / 1000));
    }, 1000);

    return () => {
      timers.forEach(clearTimeout);
      clearInterval(tick);
    };
  }, [stages]);

  // A first visit to a location downloads years of weather. Saying so once the wait gets
  // long turns an unexplained delay into an understood one.
  const slow = elapsed > 12 && !done;

  return (
    <div className="mx-auto max-w-xl px-5 py-16 sm:px-8">
      <p className="eyebrow mb-6">Working</p>
      <h1 className="text-2xl font-medium tracking-tight text-ink-1">{title}</h1>
      <p className="mt-2 text-sm text-ink-2">{subtitle}</p>

      <ol className="mt-8 space-y-1" aria-live="polite" aria-atomic="false">
        {stages.map((stage, index) => {
          const complete = done ? true : index < active;
          const running = !done && index === active;
          const pending = !done && index > active;

          return (
            <li
              key={stage.key}
              className={`flex items-center gap-3 py-2.5 transition-opacity ${
                pending ? 'opacity-40' : 'opacity-100'
              }`}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                {complete ? (
                  <Icon name="check" size={16} className="text-positive" />
                ) : running ? (
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-solar opacity-70" />
                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-solar" />
                  </span>
                ) : (
                  <span className="h-1.5 w-1.5 rounded-full bg-ink-4" aria-hidden="true" />
                )}
              </span>
              <span
                className={`text-sm ${
                  complete ? 'text-ink-2' : running ? 'text-ink-1' : 'text-ink-3'
                }`}
              >
                {stage.label}
                {/* The status word is text, not a colour, so it survives being read aloud
                    and does not depend on colour vision (§31). */}
                <span className="sr-only">
                  {complete ? ' — done' : running ? ' — in progress' : ' — waiting'}
                </span>
              </span>
            </li>
          );
        })}
      </ol>

      {slow ? (
        <p className="mt-6 animate-fade-rise border border-line bg-surface-1 px-4 py-3 text-xs
          leading-relaxed text-ink-2">
          This location is new to us, so we are downloading several years of hourly weather
          history for it. It is much quicker the next time anyone looks at this area.
        </p>
      ) : null}
    </div>
  );
}
