/**
 * The live forecast panel.
 *
 * Two of these matter more than the rest. The panel must render nothing when the fetch
 * fails — it sits on the result page, which is the thing the user actually came for, and a
 * secondary feature must never make that page look broken. And it must not invent a range:
 * the absence of an uncertainty band here is the whole reason the backend's note exists, so
 * a test that let a band appear would let the feature start lying.
 */

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LiveForecastPanel } from '@/components/result/LiveForecastPanel';

const RESPONSE = {
  method: 'physics_pass_through',
  issued_at: '2026-08-23T12:00:00+00:00',
  horizon_hours: 168,
  daily: [
    { date: '2026-08-23', energy_kwh: 8.4, hours: 11 },
    { date: '2026-08-24', energy_kwh: 21.7, hours: 24 },
    { date: '2026-08-25', energy_kwh: 19.2, hours: 24 },
  ],
  total_kwh: 49.3,
  daily_average_kwh: 20.45,
  note: 'Physics applied to a live weather forecast — a single expected value, not a range.',
  provenance: {
    source: 'Open-Meteo operational forecast',
    kind: 'forecast',
    model_chain: 'Erbs → HDKR → Faiman → PVWatts v5',
    retrieved_at: '2026-08-23T12:00:00+00:00',
    system_dc_capacity_kwp: 5.0,
  },
};

function mockFetch(body: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok,
      status: ok ? 200 : 502,
      json: async () => body,
    }),
  );
}

describe('LiveForecastPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the daily figures once the forecast arrives', async () => {
    mockFetch(RESPONSE);
    render(<LiveForecastPanel estimateId="abc123" />);

    // Each figure appears twice by design: once on the bar, once in the screen-reader
    // table beneath it. getAllByText is the honest query here.
    await waitFor(() => expect(screen.getAllByText('21.7').length).toBeGreaterThan(0));
    expect(screen.getAllByText('19.2').length).toBeGreaterThan(0);
    expect(screen.getAllByText('8.4').length).toBeGreaterThan(0);
  });

  it("shows the backend's note verbatim rather than a paraphrase", async () => {
    // The note is what explains why there is no range. Rewriting it in the interface
    // would drop the only sentence that makes the single figure honest.
    mockFetch(RESPONSE);
    render(<LiveForecastPanel estimateId="abc123" />);

    await waitFor(() => expect(screen.getByText(RESPONSE.note)).toBeTruthy());
  });

  it('labels a partial day instead of leaving a short bar unexplained', async () => {
    mockFetch(RESPONSE);
    render(<LiveForecastPanel estimateId="abc123" />);

    await waitFor(() => expect(screen.getByText(/paler bar is a partial day/i)).toBeTruthy());
  });

  it('renders nothing at all when the forecast cannot be fetched', async () => {
    // Progressive enhancement: the estimate above this panel is the primary content.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    const { container } = render(<LiveForecastPanel estimateId="abc123" />);

    await waitFor(() => expect(container.innerHTML).toBe(''));
  });

  it('renders nothing when the server answers with an error status', async () => {
    mockFetch({ message: 'upstream unavailable' }, false);
    const { container } = render(<LiveForecastPanel estimateId="abc123" />);

    await waitFor(() => expect(container.innerHTML).toBe(''));
  });

  it('renders nothing when the forecast comes back empty', async () => {
    mockFetch({ ...RESPONSE, daily: [], total_kwh: 0 });
    const { container } = render(<LiveForecastPanel estimateId="abc123" />);

    await waitFor(() => expect(container.innerHTML).toBe(''));
  });

  it('does not display an uncertainty range', async () => {
    // The annual estimate's range is measured; this has none, and inventing one that
    // looked like it would be the single most misleading thing this panel could do.
    mockFetch(RESPONSE);
    const { container } = render(<LiveForecastPanel estimateId="abc123" />);

    await waitFor(() => expect(screen.getAllByText('21.7').length).toBeGreaterThan(0));
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/\b\d+(\.\d+)?\s*[–—-]\s*\d+(\.\d+)?\s*kWh/);
    expect(text.toLowerCase()).not.toContain('confidence');
  });

  it('requests the estimate it was given', async () => {
    mockFetch(RESPONSE);
    render(<LiveForecastPanel estimateId="xyz789" />);

    await waitFor(() => expect(screen.getAllByText('21.7').length).toBeGreaterThan(0));
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
    expect(String(url)).toContain('/api/estimate/xyz789/live-forecast');
  });
});
