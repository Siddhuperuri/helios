'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { AreaField } from '@/components/estimate/AreaField';
import { EquipmentBuilder } from '@/components/estimate/EquipmentBuilder';
import { LoadingStages } from '@/components/estimate/LoadingStages';
import { LocationStep } from '@/components/estimate/LocationStep';
import {
  BooleanField,
  ChoiceField,
  MultiChoiceField,
  NumberField,
  QuestionShell,
  validateNumber,
} from '@/components/estimate/fields';
import { Icon } from '@/components/site/Icon';
import {
  canSubmit,
  clearDraft,
  hasLocation,
  draftToRequest,
  loadDraft,
  saveDraft,
  type Draft,
} from '@/lib/draft';
import {
  EstimateError,
  estimateApi,
  type InterviewCatalogue,
  type InterviewQuestion,
  type InterviewStep,
} from '@/lib/estimate';
import { translate } from '@/lib/i18n';

/**
 * The interview (§8).
 *
 * The step sequence is not written here. It is fetched from `/api/meta/interview` for the
 * chosen user type and mode, and this component renders whatever it is given. That is what
 * makes progressive disclosure real rather than a series of hardcoded branches: a farmer
 * and a factory manager get different questions because the server describes different
 * flows, not because this file contains an `if`.
 *
 * Three behaviours worth naming:
 *
 * **Conditional questions** honour each question's `depends_on`, so the bill amount only
 * appears once "I know my bill" is chosen, and the battery questions only once storage is
 * wanted. Nothing is shown greyed-out or disabled — it is absent until it is relevant.
 *
 * **Every answer is written to the draft immediately**, so a reload, a dropped connection
 * or an accidental back-navigation costs nothing.
 *
 * **Only location is ever required.** Any other step can be completed empty. That is the
 * §12 promise made structural: the button says Continue, not Complete.
 */

interface FieldError {
  questionId: string;
  message: string;
}

export function EstimateWizard() {
  const router = useRouter();
  const t = (key: string) => translate('en', key);

  const [draft, setDraft] = useState<Draft>({});
  const [catalogue, setCatalogue] = useState<InterviewCatalogue | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [responseReceived, setResponseReceived] = useState(false);
  const [failure, setFailure] = useState<EstimateError | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ------------------------------------------------------------------ bootstrap
  useEffect(() => {
    const stored = loadDraft();
    setDraft(stored);
    if (!stored.user_type) {
      // Arriving here directly, without having said what they are powering. Send them to
      // the question that decides everything else rather than guessing on their behalf.
      router.replace('/start');
    }
  }, [router]);

  useEffect(() => {
    let cancelled = false;
    estimateApi
      .interview()
      .then((data) => {
        if (!cancelled) setCatalogue(data);
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(
            'We could not load the questions from the server. Check your connection and try again.',
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const steps: InterviewStep[] = useMemo(() => {
    if (!catalogue || !draft.user_type) return [];
    // The flow depends on all three answers from /start: who they are, how much detail
    // they want, and — the one that reshapes the interview — what they came to do.
    return (
      catalogue.flows[draft.user_type]?.[draft.mode ?? 'quick']?.[draft.goal ?? 'install'] ?? []
    );
  }, [catalogue, draft.user_type, draft.mode, draft.goal]);

  const update = useCallback((patch: Partial<Draft>) => {
    setDraft((current) => {
      const next = { ...current, ...patch };
      saveDraft(next);
      return next;
    });
  }, []);

  const toggleSkip = useCallback(
    (questionId: string, skipped: boolean) => {
      setDraft((current) => {
        const list = new Set(current.skipped ?? []);
        if (skipped) list.add(questionId);
        else list.delete(questionId);
        const next = { ...current, skipped: [...list] };
        saveDraft(next);
        return next;
      });
      setErrors((current) => current.filter((e) => e.questionId !== questionId));
    },
    [],
  );

  /** Whether a question's `depends_on` is satisfied by the current answers. */
  const isVisible = useCallback(
    (question: InterviewQuestion) => {
      if (!question.depends_on) return true;
      return Object.entries(question.depends_on).every(([field, expected]) => {
        const actual = (draft as Record<string, unknown>)[field];
        return actual === expected;
      });
    },
    [draft],
  );

  // ------------------------------------------------------------------- submission
  async function submit() {
    if (!canSubmit(draft)) {
      setErrors([
        {
          questionId: 'location',
          message:
            'We need to know where the panels will be before we can work anything out. Search for your place, use your location, or point to it on the map.',
        },
      ]);
      setStepIndex(0);
      return;
    }

    setSubmitting(true);
    setFailure(null);
    setResponseReceived(false);

    try {
      const result = await estimateApi.create(draftToRequest(draft));
      setResponseReceived(true);
      if (result.estimate_id) {
        clearDraft();
        // A brief hold so the final stage visibly ticks rather than the screen jumping.
        setTimeout(() => router.push(`/result/${result.estimate_id}`), 450);
      } else {
        setFailure(
          new EstimateError('The estimate ran but could not be saved.', 500, {
            remedy: 'Try again — your answers are still here.',
          }),
        );
        setSubmitting(false);
      }
    } catch (error) {
      setFailure(
        error instanceof EstimateError
          ? error
          : new EstimateError('Something unexpected went wrong.', 500, {
              remedy: 'Try again. Your answers are saved.',
            }),
      );
      setSubmitting(false);
    }
  }

  // ------------------------------------------------------------------ navigation
  function next() {
    const step = steps[stepIndex];
    if (!step) return;

    const found: FieldError[] = [];
    for (const question of step.questions) {
      if (!isVisible(question) || (draft.skipped ?? []).includes(question.id)) continue;
      if (question.kind === 'location' && !hasLocation(draft)) {
        found.push({
          questionId: question.id,
          message:
            'Choose a location to continue — search for it, use your current location, or point to it on the map.',
        });
      }
      if ((question.kind === 'number' || question.kind === 'currency') && question.required) {
        const value = (draft as Record<string, unknown>)[question.field];
        if (value === undefined || value === null || value === '') {
          found.push({
            questionId: question.id,
            message:
              question.field === 'panel_count'
                ? 'Tell us how many panels you have — it is what your whole estimate is built on.'
                : `${question.prompt.replace(/\?$/, '')} is needed to continue.`,
          });
        }
      }
    }

    setErrors(found);
    if (found.length > 0) {
      document.getElementById(`question-${found[0]!.questionId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
      return;
    }

    if (stepIndex >= steps.length - 1) {
      void submit();
    } else {
      setStepIndex((i) => i + 1);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  function back() {
    if (stepIndex === 0) {
      router.push('/start');
      return;
    }
    setStepIndex((i) => i - 1);
    setErrors([]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------------- render
  if (submitting) {
    return (
      <>
        <LoadingStages done={responseReceived} />
        {failure ? <FailurePanel error={failure} onRetry={() => void submit()} /> : null}
      </>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-xl px-5 py-16 sm:px-8">
        <p className="eyebrow mb-5">Connection</p>
        <h1 className="text-xl font-medium text-ink-1">{loadError}</h1>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="tap mt-6 inline-flex items-center gap-2 border border-line-strong px-5 py-2.5
            text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
        >
          {t('errors.retry')}
        </button>
      </div>
    );
  }

  if (!catalogue || steps.length === 0) {
    return (
      <div className="mx-auto max-w-xl px-5 py-16 sm:px-8" role="status">
        <div className="h-4 w-32 animate-pulse bg-surface-3" />
        <div className="mt-6 h-8 w-3/4 animate-pulse bg-surface-3" />
        <div className="mt-3 h-4 w-1/2 animate-pulse bg-surface-2" />
      </div>
    );
  }

  const step = steps[stepIndex]!;
  const isLast = stepIndex === steps.length - 1;
  const errorFor = (id: string) => errors.find((e) => e.questionId === id)?.message ?? null;

  return (
    <div className="mx-auto max-w-3xl px-5 py-10 sm:px-8 lg:py-14">
      {/* --------------------------------------------------------------- progress */}
      <div className="mb-8">
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <p className="font-mono text-2xs uppercase tracking-[0.14em] text-ink-3">
            {t('wizard.step')} {stepIndex + 1} {t('wizard.of')} {steps.length}
          </p>
          {/* The step's own name is the heading immediately below; repeating it here just
              made the page say the same words twice in a row. What is useful at this size
              is what is still to come. */}
          {stepIndex < steps.length - 1 ? (
            <p className="text-2xs text-ink-4">Next: {steps[stepIndex + 1]!.title}</p>
          ) : (
            <p className="text-2xs text-ink-4">Last step</p>
          )}
        </div>
        {/* A real progress bar: it reflects steps completed, and it never overstates. */}
        <div
          className="flex gap-1"
          role="progressbar"
          aria-valuenow={stepIndex + 1}
          aria-valuemin={1}
          aria-valuemax={steps.length}
          aria-label="Interview progress"
        >
          {steps.map((s, index) => (
            <span
              key={s.id}
              className={`h-1 flex-1 transition-colors ${
                index < stepIndex
                  ? 'bg-solar'
                  : index === stepIndex
                    ? 'bg-solar/50'
                    : 'bg-surface-3'
              }`}
            />
          ))}
        </div>
      </div>

      <h1 className="text-2xl font-medium tracking-tight text-ink-1">{step.title}</h1>
      {step.subtitle ? (
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">{step.subtitle}</p>
      ) : null}

      {/* -------------------------------------------------------------- questions */}
      <div className="mt-8">
        {step.questions.filter(isVisible).map((question) => (
          <div key={question.id} id={`question-${question.id}`}>
            {renderQuestion(question)}
          </div>
        ))}
      </div>

      {/* ------------------------------------------------------------- navigation */}
      <div className="mt-10 flex flex-wrap items-center gap-3 border-t border-line pt-6">
        <button
          type="button"
          onClick={back}
          className="tap inline-flex items-center gap-2 border border-line px-5 py-3 text-sm
            text-ink-2 transition-colors hover:border-line-bright hover:text-ink-1"
        >
          <Icon name="arrow-left" size={16} />
          {t('wizard.back')}
        </button>

        <button
          type="button"
          onClick={next}
          className="tap inline-flex items-center gap-2 border border-solar bg-solar px-6 py-3
            text-sm font-medium text-base transition-opacity hover:opacity-90"
        >
          {isLast ? t('wizard.calculate') : t('wizard.next')}
          <Icon name="arrow-right" size={16} />
        </button>

        {!isLast ? (
          <p className="ml-auto text-2xs text-ink-4">
            Anything you are unsure about can be skipped.
          </p>
        ) : null}
      </div>

      {failure ? <FailurePanel error={failure} onRetry={() => void submit()} /> : null}
    </div>
  );

  // ------------------------------------------------------------------------------
  function renderQuestion(question: InterviewQuestion) {
    const skipped = (draft.skipped ?? []).includes(question.id);
    const error = errorFor(question.id);
    const shell = (children: React.ReactNode) => (
      <QuestionShell
        question={question}
        skipped={skipped}
        onSkip={(value) => toggleSkip(question.id, value)}
        error={error}
      >
        {children}
      </QuestionShell>
    );

    // Location has its own component: three input methods, a failure path, and a map.
    if (question.kind === 'location') {
      return shell(
        <LocationStep
          value={draft.location}
          onChange={(location) => {
            update({ location });
            setErrors((current) => current.filter((e) => e.questionId !== question.id));
          }}
        />,
      );
    }

    if (question.kind === 'area') {
      return shell(
        <AreaField
          value={draft.area}
          onChange={(area) => update({ area })}
          center={
            draft.location?.latitude != null && draft.location?.longitude != null
              ? { lat: draft.location.latitude, lon: draft.location.longitude }
              : null
          }
        />,
      );
    }

    if (question.kind === 'equipment_list' || question.kind === 'pump_list') {
      // Both lists are rendered by one builder, so the running total covers everything.
      // The pump list question renders it; the equipment question then renders nothing.
      if (question.kind === 'equipment_list' && draft.user_type === 'farm') return null;
      return shell(
        <EquipmentBuilder
          appliances={catalogue!.appliances}
          userType={draft.user_type ?? 'home'}
          equipment={draft.equipment ?? []}
          pumps={draft.pumps ?? []}
          onEquipmentChange={(equipment) => update({ equipment })}
          onPumpsChange={(pumps) => update({ pumps })}
          showPumps={draft.user_type === 'farm'}
        />,
      );
    }

    if (question.kind === 'multi_choice') {
      const selected = ((draft as Record<string, unknown>)[question.field] as string[]) ?? [];
      return shell(
        <MultiChoiceField
          question={question}
          value={selected}
          onChange={(next) => update({ [question.field]: next } as Partial<Draft>)}
        />,
      );
    }

    if (question.kind === 'single_choice') {
      // Wattage options are numbers presented as choices, so they round-trip through the
      // draft as numbers rather than as the strings the option values carry.
      const numeric =
        question.field === 'panel_watts' || question.field === 'offset_target_pct';
      const current = (draft as Record<string, unknown>)[question.field];
      return shell(
        <ChoiceField
          question={question}
          value={current === undefined || current === null ? null : String(current)}
          onChange={(value) =>
            update({ [question.field]: numeric ? Number(value) : value } as Partial<Draft>)
          }
          columns={question.options.length > 4 ? 3 : 2}
        />,
      );
    }

    if (question.kind === 'boolean') {
      return shell(
        <BooleanField
          value={(draft as Record<string, unknown>)[question.field] as boolean | undefined}
          onChange={(value) => update({ [question.field]: value } as Partial<Draft>)}
        />,
      );
    }

    if (question.kind === 'text') {
      return shell(
        <input
          type="text"
          value={((draft as Record<string, unknown>)[question.field] as string) ?? ''}
          onChange={(event) => update({ [question.field]: event.target.value } as Partial<Draft>)}
          maxLength={120}
          aria-label={question.prompt}
          placeholder="e.g. Waaree 550W Bifacial"
          className="w-full max-w-md border border-line-strong bg-surface-1 px-3 py-3 text-base
            text-ink-1 placeholder:text-ink-4 focus:border-solar focus:outline-none"
        />,
      );
    }

    if (question.kind === 'number' || question.kind === 'currency') {
      return shell(
        <NumberField
          question={question}
          value={(draft as Record<string, unknown>)[question.field] as number | null}
          prefix={question.kind === 'currency' ? '₹' : undefined}
          error={error}
          onChange={(value) => {
            update({ [question.field]: value } as Partial<Draft>);
            if (value !== null) {
              setErrors((current) => current.filter((e) => e.questionId !== question.id));
            }
          }}
        />,
      );
    }

    return null;
  }
}

/**
 * A failure the user can act on (§30).
 *
 * Three things every time: what happened, what it means for their answers, and what to do
 * next. The reassurance that nothing was lost is the important one — it is what stops
 * somebody abandoning four minutes of work because a request timed out.
 */
function FailurePanel({ error, onRetry }: { error: EstimateError; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mt-8 animate-fade-rise border border-critical/40 bg-critical/5 p-5"
    >
      <div className="flex items-start gap-3">
        <Icon name="alert" size={20} className="mt-0.5 text-critical" />
        <div className="flex-1">
          <p className="text-base font-medium text-ink-1">{error.message}</p>
          {error.remedy ? (
            <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{error.remedy}</p>
          ) : null}

          {error.fieldErrors && error.fieldErrors.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {error.fieldErrors.map((fieldError, index) => (
                <li key={index} className="text-sm text-ink-2">
                  <span className="text-ink-3">{fieldError.field}:</span> {fieldError.message}
                </li>
              ))}
            </ul>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onRetry}
              className="tap inline-flex items-center gap-2 border border-line-strong px-4 py-2.5
                text-sm text-ink-1 transition-colors hover:border-solar hover:text-solar"
            >
              Try again
            </button>
          </div>

          {error.detail ? (
            <details className="mt-4">
              <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-1">
                Technical detail
              </summary>
              <p className="num mt-2 whitespace-pre-wrap break-words text-2xs text-ink-3">
                {error.detail}
              </p>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}
