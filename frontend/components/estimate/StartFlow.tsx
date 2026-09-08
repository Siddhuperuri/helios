'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { Icon, type IconName } from '@/components/site/Icon';
import { loadDraft, saveDraft } from '@/lib/draft';
import { estimateApi, type GoalDto, type InterviewCatalogue } from '@/lib/estimate';
import { translate } from '@/lib/i18n';

/**
 * The three questions that shape everything after them, on one page.
 *
 * What are you powering, what are you trying to do, and how much detail do you want to
 * give. They are together rather than on separate screens because each only makes sense in
 * the light of the one before, and because three taps with a scroll between them is a
 * smaller ask than three page loads. Each section appears only once the previous is
 * answered, so the screen never shows eleven options at once.
 *
 * The middle question is the load-bearing one. Somebody who already owns an array is
 * describing a system that exists — their panel count is a measurement, and capacity
 * follows from it. Somebody planning one is asking what they need — capacity follows from
 * their demand and space, and the panel count is the answer handed back. Asking "how many
 * panels?" of the second group up front would be asking them to solve the problem they
 * came here with.
 *
 * None of the three is technical, which is the point of putting them first (§6): a person
 * who has never heard of a kilowatt can answer all three, and what they answer decides
 * every question that follows.
 *
 * The options come from the API rather than being hardcoded here. That is what lets the
 * same catalogue drive a future voice front end (§34) and a translated interface (§33) —
 * including the spoken synonyms, which are carried through even though nothing consumes
 * them yet.
 */

const FALLBACK_TYPES = [
  { key: 'home', title: 'Home', description: 'Reduce electricity bills and power my home.', icon: 'home' },
  { key: 'farm', title: 'Farm / Agriculture', description: 'Power pumps, irrigation, farm buildings and agricultural equipment.', icon: 'sprout' },
  { key: 'shop', title: 'Shop / Small Business', description: 'Power a shop, office, clinic or small commercial space.', icon: 'store' },
  { key: 'commercial', title: 'Commercial / Industrial', description: 'Power a larger facility, factory, warehouse or infrastructure.', icon: 'factory' },
  { key: 'institution', title: 'School / Institution', description: 'Power a school, college, hospital or public facility.', icon: 'school' },
  { key: 'exploring', title: 'Just Exploring', description: 'I want to understand my solar potential.', icon: 'compass' },
];

const FALLBACK_GOALS: GoalDto[] = [
  {
    key: 'existing',
    title: 'I already have solar panels',
    description: 'Find out what the system you already own should be producing.',
    icon: 'sun',
    synonyms: [],
  },
  {
    key: 'install',
    title: 'I want to install solar',
    description: 'Work out the right system size and how many panels that is.',
    icon: 'layers',
    synonyms: [],
  },
  {
    key: 'compare',
    title: "I'm comparing options",
    description: 'Put several system sizes side by side before deciding.',
    icon: 'sliders',
    synonyms: [],
  },
];

const FALLBACK_MODES = [
  {
    key: 'quick',
    title: 'Quick Estimate',
    description: 'Get a useful solar estimate with only a few simple questions.',
    duration: 'About 1–2 minutes',
    suited_to: 'Homeowners, farmers, and anyone new to solar.',
    icon: 'zap',
  },
  {
    key: 'detailed',
    title: 'Detailed Analysis',
    description: 'Provide technical information for a more precise engineering estimate.',
    duration: 'About 5–10 minutes',
    suited_to: 'Engineers, consultants, EPC companies and commercial projects.',
    icon: 'sliders',
  },
];

export function StartFlow() {
  const router = useRouter();
  const t = (key: string) => translate('en', key);

  const [catalogue, setCatalogue] = useState<InterviewCatalogue | null>(null);
  const [userType, setUserType] = useState<string | null>(null);
  const [goal, setGoal] = useState<string | null>(null);
  const [reachable, setReachable] = useState(true);

  // Restore a previous choice so the back button from the interview does not feel like a
  // reset.
  useEffect(() => {
    const draft = loadDraft();
    if (draft.user_type) setUserType(draft.user_type);
    if (draft.goal) setGoal(draft.goal);
  }, []);

  useEffect(() => {
    let cancelled = false;
    estimateApi
      .interview()
      .then((data) => {
        if (!cancelled) setCatalogue(data);
      })
      .catch(() => {
        // The interview catalogue failing is not fatal here: these six options are stable
        // and known, so the user can still choose and move on. The wizard itself will
        // surface the connection problem properly if it persists.
        if (!cancelled) setReachable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const userTypes = catalogue?.user_types ?? FALLBACK_TYPES;
  const goals = catalogue?.goals ?? FALLBACK_GOALS;
  const modes = catalogue?.modes ?? FALLBACK_MODES;

  function reveal(id: string) {
    // Bring the next question into view without yanking the page from under someone who
    // is already scrolling towards it themselves.
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function chooseType(key: string) {
    setUserType(key);
    saveDraft({ ...loadDraft(), user_type: key });
    reveal('goal-choice');
  }

  function chooseGoal(key: string) {
    setGoal(key);
    saveDraft({ ...loadDraft(), goal: key as 'existing' | 'install' | 'compare' });
    reveal('mode-choice');
  }

  function chooseMode(mode: string) {
    saveDraft({
      ...loadDraft(),
      user_type: userType ?? 'exploring',
      goal: (goal ?? 'install') as 'existing' | 'install' | 'compare',
      mode: mode as 'quick' | 'detailed',
    });
    router.push('/estimate');
  }

  return (
    <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 lg:py-16">
      {/* ------------------------------------------------------------ user type */}
      <section aria-labelledby="user-type-heading">
        <p className="eyebrow mb-6">Step 1 of 3</p>
        <h1
          id="user-type-heading"
          className="max-w-2xl text-2xl font-medium leading-tight tracking-tight text-ink-1 sm:text-3xl"
        >
          {t('start.title')}
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-2">{t('start.subtitle')}</p>

        {!reachable ? (
          <p className="mt-4 border border-warning/40 bg-warning/5 px-4 py-3 text-xs text-ink-2">
            We could not reach the server just now, so these options are the built-in ones.
            Carry on — we will try again when you continue.
          </p>
        ) : null}

        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {userTypes.map((option) => {
            const selected = userType === option.key;
            return (
              <li key={option.key}>
                <button
                  type="button"
                  onClick={() => chooseType(option.key)}
                  aria-pressed={selected}
                  className="choice-card h-full flex-col"
                >
                  <span className="flex w-full items-start gap-3">
                    <Icon
                      name={(option.icon as IconName) ?? 'help-circle'}
                      size={24}
                      className={selected ? 'text-solar' : 'text-steel'}
                    />
                    <span className="flex-1">
                      <span className="block text-base font-medium text-ink-1">
                        {option.title}
                      </span>
                      <span className="mt-1 block text-xs leading-relaxed text-ink-2">
                        {option.description}
                      </span>
                    </span>
                    {/* The check is not decoration: selection must not be carried by
                        colour alone (§31). */}
                    {selected ? (
                      <Icon name="check" size={18} className="text-solar" title="Selected" />
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {/* ----------------------------------------------------------------- goal */}
      {userType ? (
        <section
          id="goal-choice"
          aria-labelledby="goal-heading"
          className="mt-14 animate-fade-rise border-t border-line pt-10 lg:mt-16"
        >
          <p className="eyebrow mb-6">Step 2 of 3</p>
          <h2
            id="goal-heading"
            className="max-w-2xl text-xl font-medium leading-tight tracking-tight text-ink-1 sm:text-2xl"
          >
            What are you trying to do?
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-2">
            If you already have panels we will work out what they produce. If you are
            planning, we will work out how many you need.
          </p>

          <ul className="mt-8 grid gap-3 sm:grid-cols-3">
            {goals.map((option) => {
              const selected = goal === option.key;
              return (
                <li key={option.key}>
                  <button
                    type="button"
                    onClick={() => chooseGoal(option.key)}
                    aria-pressed={selected}
                    className="choice-card h-full flex-col"
                  >
                    <span className="flex w-full items-start gap-3">
                      <Icon
                        name={(option.icon as IconName) ?? 'help-circle'}
                        size={22}
                        className={selected ? 'text-solar' : 'text-steel'}
                      />
                      <span className="flex-1">
                        <span className="block text-base font-medium text-ink-1">
                          {option.title}
                        </span>
                        <span className="mt-1 block text-xs leading-relaxed text-ink-2">
                          {option.description}
                        </span>
                      </span>
                      {selected ? (
                        <Icon name="check" size={18} className="text-solar" title="Selected" />
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {/* ----------------------------------------------------------------- mode */}
      {userType && goal ? (
        <section
          id="mode-choice"
          aria-labelledby="mode-heading"
          className="mt-14 animate-fade-rise border-t border-line pt-10 lg:mt-16"
        >
          <p className="eyebrow mb-6">Step 3 of 3</p>
          <h2
            id="mode-heading"
            className="max-w-2xl text-xl font-medium leading-tight tracking-tight text-ink-1 sm:text-2xl"
          >
            {t('start.modeTitle')}
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-2">
            {t('start.modeSubtitle')}
          </p>

          <ul className="mt-8 grid gap-3 sm:grid-cols-2">
            {modes.map((mode) => (
              <li key={mode.key}>
                <button
                  type="button"
                  onClick={() => chooseMode(mode.key)}
                  className="choice-card h-full flex-col"
                >
                  <span className="flex w-full items-start gap-3">
                    <Icon
                      name={(mode.icon as IconName) ?? 'zap'}
                      size={24}
                      className="text-steel"
                    />
                    <span className="flex-1">
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="text-base font-medium text-ink-1">{mode.title}</span>
                        <span className="num shrink-0 text-2xs text-ink-4">
                          {mode.duration}
                        </span>
                      </span>
                      <span className="mt-1.5 block text-xs leading-relaxed text-ink-2">
                        {mode.description}
                      </span>
                      <span className="mt-2 block text-2xs text-ink-3">{mode.suited_to}</span>
                    </span>
                    <Icon name="arrow-right" size={18} className="mt-0.5 text-ink-4" />
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <p className="mt-6 text-xs leading-relaxed text-ink-3">
            Not sure? Take the quick one. Every question has a way to skip it, and you can
            add detail afterwards without starting again.
          </p>
        </section>
      ) : null}
    </div>
  );
}
