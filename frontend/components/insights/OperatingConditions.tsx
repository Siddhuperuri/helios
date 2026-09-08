'use client';

import { Panel, Tag, severityTone } from '@/components/ui';
import type { OperatingCondition } from '@/lib/api';
import { num } from '@/lib/format';

/**
 * The operating notes, rendered the same way wherever they appear.
 *
 * Extracted from the forecast workspace so the prediction page shows the identical cards
 * rather than a second implementation that drifts from it. The backend already computes
 * these notes once, in `models.forecast.operating_conditions`; there is no reason for the
 * front end to describe them twice.
 *
 * The rule the layout enforces: **the threshold is always visible**. The reference
 * application printed "Safe Operation" with no stated criteria and returned the same
 * verdict for a 28 °C site and an 8 °C one. Here every card names the quantity, its value,
 * and the threshold it was judged against, so a reader can disagree with the threshold
 * instead of having to trust the label.
 */
export function OperatingConditionCards({ notes }: { notes: OperatingCondition[] }) {
  if (!notes.length) return null;

  return (
    <div className="space-y-3">
      {notes.map((c) => (
        <Panel key={c.key}>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
            <h3 className="text-sm text-ink-1">{c.title}</h3>
            <div className="flex items-center gap-2">
              <span className="num text-sm text-ink-1">
                {num(c.value, 2)} <span className="text-ink-4">{c.unit}</span>
              </span>
              <Tag tone={severityTone(c.severity)}>{c.severity}</Tag>
            </div>
          </div>
          <p className="text-xs leading-relaxed text-ink-2">{c.message}</p>
          <p className="mt-2 border-t border-line pt-2 font-mono text-2xs text-ink-4">
            Threshold: {c.threshold}
          </p>
        </Panel>
      ))}
    </div>
  );
}
