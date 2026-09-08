import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LocationStep } from '@/components/estimate/LocationStep';
import {
  BooleanField,
  ChoiceField,
  QuestionShell,
  validateNumber,
} from '@/components/estimate/fields';
import { LoadingStages } from '@/components/estimate/LoadingStages';
import type { InterviewQuestion } from '@/lib/estimate';

/**
 * Component behaviour that the specification names explicitly.
 *
 * These are not snapshot tests. Each one pins a promise the product makes: that a rejected
 * value tells you what to type instead (§46), that every technical question can be declined
 * and says what declining costs (§12), that a denied location permission offers a way
 * forward rather than a dead end (§10), and that a stage is never shown as finished before
 * it has finished (§40).
 */

function question(overrides: Partial<InterviewQuestion> = {}): InterviewQuestion {
  return {
    id: 'q',
    field: 'value',
    kind: 'number',
    prompt: 'How big is your system?',
    spoken_prompt: 'How big is your system?',
    help_text: '',
    options: [],
    unit: 'kW',
    min_value: 0.5,
    max_value: 1000,
    required: false,
    unknown_label: null,
    unknown_effect: null,
    depends_on: null,
    group: 'system',
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// --------------------------------------------------------------------------------------
// Validation (§46)
// --------------------------------------------------------------------------------------

describe('number validation', () => {
  it('corrects a negative value instead of saying "invalid"', () => {
    const { error } = validateNumber(question(), '-5');
    expect(error).toBeTruthy();
    expect(error).not.toMatch(/invalid/i);
    expect(error).toContain('cannot be negative');
    expect(error).toContain('kW'); // names the unit, so the reader knows what to type
  });

  it('says what the minimum is rather than only that the value is wrong', () => {
    const { error } = validateNumber(question(), '0.1');
    expect(error).toContain('0.5');
    expect(error).toContain('kW');
  });

  it('treats zero as its own case, because zero is what people actually type', () => {
    const { error } = validateNumber(question(), '0');
    expect(error).toContain('cannot be zero');
  });

  it('rejects a value above what can be modelled, with the ceiling stated', () => {
    const { error } = validateNumber(question(), '99999');
    expect(error).toContain('1000');
  });

  it('rejects text without crashing', () => {
    const { value, error } = validateNumber(question(), 'abc');
    expect(value).toBeNull();
    expect(error).toContain('Enter a number');
  });

  it('accepts an empty optional field but not an empty required one', () => {
    expect(validateNumber(question({ required: false }), '').error).toBeNull();
    expect(validateNumber(question({ required: true }), '').error).toBeTruthy();
  });

  it('accepts a value inside the bounds', () => {
    const { value, error } = validateNumber(question(), '6.5');
    expect(value).toBe(6.5);
    expect(error).toBeNull();
  });
});

// --------------------------------------------------------------------------------------
// The escape route (§12)
// --------------------------------------------------------------------------------------

describe('every technical question can be declined', () => {
  const skippable = question({
    unknown_label: 'Use the best angle for my location',
    unknown_effect: 'We will test a range of angles against your own weather.',
  });

  it('offers the escape and explains the consequence on request', () => {
    render(
      <QuestionShell question={skippable} skipped={false} onSkip={() => {}}>
        <input aria-label="tilt" />
      </QuestionShell>,
    );

    expect(screen.getByText('Use the best angle for my location')).toBeTruthy();

    // The consequence is available but not shouted; it appears when asked for.
    expect(screen.queryByText(/test a range of angles/)).toBeNull();
    fireEvent.click(screen.getByText('What happens if I skip this?'));
    expect(screen.getByText(/test a range of angles/)).toBeTruthy();
  });

  it('states what will be assumed once the question is skipped', () => {
    render(
      <QuestionShell question={skippable} skipped onSkip={() => {}}>
        <input aria-label="tilt" />
      </QuestionShell>,
    );
    expect(screen.getByText(/test a range of angles/)).toBeTruthy();
    // Skipping is reversible — a dead end would be worse than the question.
    expect(screen.getByText('Answer it after all')).toBeTruthy();
  });

  it('hides the input while skipped, so the state is unambiguous', () => {
    render(
      <QuestionShell question={skippable} skipped onSkip={() => {}}>
        <input aria-label="tilt" />
      </QuestionShell>,
    );
    expect(screen.queryByLabelText('tilt')).toBeNull();
  });

  it('surfaces an error with an alert role so it is announced', () => {
    render(
      <QuestionShell
        question={skippable}
        skipped={false}
        onSkip={() => {}}
        error="This cannot be negative. Enter a value above 0 kW."
      >
        <input aria-label="tilt" />
      </QuestionShell>,
    );
    expect(screen.getByRole('alert').textContent).toContain('cannot be negative');
  });
});

// --------------------------------------------------------------------------------------
// Choice fields (§31)
// --------------------------------------------------------------------------------------

describe('choice fields', () => {
  const choice = question({
    kind: 'single_choice',
    options: [
      { value: 'bill', label: 'I know my bill', description: '', icon: null, synonyms: [] },
      { value: 'units', label: 'I know my units', description: '', icon: null, synonyms: [] },
    ],
  });

  it('marks selection with aria-pressed rather than colour alone', () => {
    render(<ChoiceField question={choice} value="units" onChange={() => {}} />);
    const selected = screen.getByRole('button', { pressed: true });
    expect(selected.textContent).toContain('I know my units');
  });

  it('reports the chosen value', () => {
    const onChange = vi.fn();
    render(<ChoiceField question={choice} value={null} onChange={onChange} />);
    fireEvent.click(screen.getByText('I know my bill'));
    expect(onChange).toHaveBeenCalledWith('bill');
  });

  it('exposes boolean state to assistive technology', () => {
    render(<BooleanField value onChange={() => {}} />);
    expect(screen.getByRole('button', { pressed: true }).textContent).toContain('Yes');
  });
});

// --------------------------------------------------------------------------------------
// Location failure (§10)
// --------------------------------------------------------------------------------------

describe('location permission failure', () => {
  it('offers search and map instead of trapping the user', async () => {
    // Permission denied is error code 1.
    vi.stubGlobal('navigator', {
      ...navigator,
      geolocation: {
        getCurrentPosition: (_ok: unknown, fail: (e: { code: number }) => void) =>
          fail({ code: 1 }),
      },
    });

    render(<LocationStep value={undefined} onChange={() => {}} />);
    fireEvent.click(screen.getByText('Use my location'));

    await waitFor(() => {
      expect(screen.getByText(/could not access your location/i)).toBeTruthy();
    });
    // Both alternatives are offered right there, not buried.
    expect(screen.getAllByText('Search for a place').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Pick on the map').length).toBeGreaterThan(0);
  });

  it('explains a timeout differently from a refusal', async () => {
    vi.stubGlobal('navigator', {
      ...navigator,
      geolocation: {
        getCurrentPosition: (_ok: unknown, fail: (e: { code: number }) => void) =>
          fail({ code: 3 }),
      },
    });

    render(<LocationStep value={undefined} onChange={() => {}} />);
    fireEvent.click(screen.getByText('Use my location'));

    await waitFor(() => {
      expect(screen.getByText(/took too long/i)).toBeTruthy();
    });
  });

  it('copes with a browser that has no geolocation at all', async () => {
    vi.stubGlobal('navigator', { ...navigator, geolocation: undefined });

    render(<LocationStep value={undefined} onChange={() => {}} />);
    fireEvent.click(screen.getByText('Use my location'));

    await waitFor(() => {
      expect(screen.getByText(/cannot share your location/i)).toBeTruthy();
    });
  });

  it('shows a chosen location by name, not as coordinates', () => {
    render(
      <LocationStep
        value={{
          latitude: 16.5074,
          longitude: 80.6466,
          label: 'Vijayawada, Andhra Pradesh, India',
          elevation_m: 47,
        }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText('Vijayawada, Andhra Pradesh, India')).toBeTruthy();
    // Coordinates are present as confirmation, but they are not the answer.
    expect(screen.getByText(/16\.5074, 80\.6466/)).toBeTruthy();
  });
});

// --------------------------------------------------------------------------------------
// Loading (§40)
// --------------------------------------------------------------------------------------

describe('staged loading', () => {
  it('never says "Loading" and names the stages instead', () => {
    render(<LoadingStages />);
    expect(screen.queryByText(/^loading/i)).toBeNull();
    expect(screen.getByText('Fetching solar resource data')).toBeTruthy();
    expect(screen.getByText('Calculating expected generation')).toBeTruthy();
  });

  it('does not mark the final stage done until the work actually is', () => {
    const { rerender } = render(<LoadingStages />);
    const finalStage = screen.getByText('Preparing your solar report').closest('li')!;
    expect(finalStage.textContent).toContain('waiting');

    rerender(<LoadingStages done />);
    expect(
      screen.getByText('Preparing your solar report').closest('li')!.textContent,
    ).toContain('done');
  });

  it('conveys status as text, not only as colour', () => {
    render(<LoadingStages />);
    // Screen-reader text accompanies every stage.
    expect(screen.getByText('Finding your location').closest('li')!.textContent).toMatch(
      /done|in progress|waiting/,
    );
  });
});
