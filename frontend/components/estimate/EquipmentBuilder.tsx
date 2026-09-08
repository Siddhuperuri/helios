'use client';

import { useMemo, useState } from 'react';

import { Icon } from '@/components/site/Icon';
import type { EquipmentDraft, PumpDraft } from '@/lib/draft';
import type { ApplianceDto } from '@/lib/estimate';

/**
 * Working out consumption from what the user can actually see (§11).
 *
 * This is the "I don't know" branch of the electricity question, and it carries the most
 * weight of any input in the product: for a user who cannot read a bill, this is what sets
 * demand, which sets system size, which sets every figure that follows.
 *
 * So it is built to be answerable rather than complete. Items are added from a short list
 * with sensible hours already filled in, because a person who is unsure what they use is
 * not helped by an empty grid of twenty rows. The running total is visible as they go, so
 * the estimate is something they watch being built rather than a number that appears at
 * the end.
 *
 * The arithmetic shown here is intentionally the simple part — watts times hours times
 * days. Duty cycles for cycling loads like refrigeration are applied by the backend, which
 * is why a fridge left at 24 hours does not produce an absurd total. The interface says so
 * rather than letting the user think it has been forgotten.
 */

interface Props {
  appliances: ApplianceDto[];
  userType: string;
  equipment: EquipmentDraft[];
  pumps: PumpDraft[];
  onEquipmentChange: (items: EquipmentDraft[]) => void;
  onPumpsChange: (items: PumpDraft[]) => void;
  /** Farm users get the pump builder; everyone else does not need it. */
  showPumps: boolean;
}

export function EquipmentBuilder({
  appliances,
  userType,
  equipment,
  pumps,
  onEquipmentChange,
  onPumpsChange,
  showPumps,
}: Props) {
  const available = useMemo(
    () => appliances.filter((a) => a.user_types.includes(userType)),
    [appliances, userType],
  );

  const byCategory = useMemo(() => {
    const groups = new Map<string, ApplianceDto[]>();
    for (const appliance of available) {
      const list = groups.get(appliance.category) ?? [];
      list.push(appliance);
      groups.set(appliance.category, list);
    }
    return [...groups.entries()];
  }, [available]);

  const [picker, setPicker] = useState(false);

  const specFor = (key: string) => available.find((a) => a.key === key);

  function addAppliance(appliance: ApplianceDto) {
    if (equipment.some((e) => e.key === appliance.key)) return;
    onEquipmentChange([
      ...equipment,
      {
        key: appliance.key,
        count: 1,
        hours_per_day: appliance.default_hours_per_day,
        days_per_month: appliance.default_days_per_month,
      },
    ]);
    setPicker(false);
  }

  function update(index: number, patch: Partial<EquipmentDraft>) {
    onEquipmentChange(equipment.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  // A rough running total. The backend applies duty cycles and is the authority; this is
  // here so the user can see their answers adding up, and it is labelled approximate.
  const monthlyEstimate =
    equipment.reduce((sum, item) => {
      const spec = specFor(item.key);
      if (!spec) return sum;
      const hours = item.hours_per_day ?? spec.default_hours_per_day;
      const days = item.days_per_month ?? spec.default_days_per_month;
      return sum + (spec.typical_watts * item.count * hours * days) / 1000;
    }, 0) +
    pumps.reduce(
      (sum, pump) =>
        sum +
        ((pump.horsepower * 745.7) / 0.75 / 1000) *
          pump.count *
          pump.hours_per_day *
          pump.days_per_month,
      0,
    );

  return (
    <div>
      {/* ------------------------------------------------------------------ pumps */}
      {showPumps ? (
        <div className="mb-6">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h4 className="text-sm font-medium text-ink-1">Water pumps</h4>
            <button
              type="button"
              onClick={() =>
                onPumpsChange([
                  ...pumps,
                  { horsepower: 5, count: 1, hours_per_day: 6, days_per_month: 25 },
                ])
              }
              className="tap inline-flex items-center gap-1.5 border border-line px-3 py-2 text-xs
                text-ink-1 transition-colors hover:border-solar hover:text-solar"
            >
              <Icon name="droplet" size={14} />
              Add a pump
            </button>
          </div>

          {pumps.length === 0 ? (
            <p className="text-sm text-ink-3">
              No pumps added. If you run a borewell or irrigation pump, add it — it is
              usually the largest thing on a farm connection by a wide margin.
            </p>
          ) : (
            <ul className="space-y-2">
              {pumps.map((pump, index) => (
                <li key={index} className="border border-line bg-surface-1 p-3">
                  <div className="grid gap-3 sm:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
                    <NumberCell
                      label="Size"
                      unit="HP"
                      value={pump.horsepower}
                      min={0.5}
                      step={0.5}
                      onChange={(v) =>
                        onPumpsChange(
                          pumps.map((p, i) => (i === index ? { ...p, horsepower: v } : p)),
                        )
                      }
                    />
                    <NumberCell
                      label="How many"
                      value={pump.count}
                      min={1}
                      onChange={(v) =>
                        onPumpsChange(pumps.map((p, i) => (i === index ? { ...p, count: v } : p)))
                      }
                    />
                    <NumberCell
                      label="Hours a day"
                      value={pump.hours_per_day}
                      min={0}
                      max={24}
                      onChange={(v) =>
                        onPumpsChange(
                          pumps.map((p, i) => (i === index ? { ...p, hours_per_day: v } : p)),
                        )
                      }
                    />
                    <NumberCell
                      label="Days a month"
                      value={pump.days_per_month}
                      min={0}
                      max={31}
                      onChange={(v) =>
                        onPumpsChange(
                          pumps.map((p, i) => (i === index ? { ...p, days_per_month: v } : p)),
                        )
                      }
                    />
                    <button
                      type="button"
                      onClick={() => onPumpsChange(pumps.filter((_, i) => i !== index))}
                      aria-label={`Remove pump ${index + 1}`}
                      className="tap self-end border border-line px-2 text-ink-3 transition-colors
                        hover:border-critical hover:text-critical"
                    >
                      <Icon name="trash" size={16} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {/* -------------------------------------------------------------- appliances */}
      <div className="mb-3 flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium text-ink-1">
          {showPumps ? 'Other equipment' : 'What you run'}
        </h4>
        <button
          type="button"
          onClick={() => setPicker((v) => !v)}
          aria-expanded={picker}
          className="tap inline-flex items-center gap-1.5 border border-line px-3 py-2 text-xs
            text-ink-1 transition-colors hover:border-solar hover:text-solar"
        >
          <Icon name="list" size={14} />
          Add equipment
        </button>
      </div>

      {picker ? (
        <div className="mb-4 max-h-72 overflow-y-auto border border-line-strong bg-surface-1 p-3">
          {byCategory.map(([category, items]) => (
            <div key={category} className="mb-4 last:mb-0">
              <p className="mb-2 font-mono text-2xs uppercase tracking-[0.12em] text-ink-4">
                {category}
              </p>
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {items.map((appliance) => {
                  const added = equipment.some((e) => e.key === appliance.key);
                  return (
                    <li key={appliance.key}>
                      <button
                        type="button"
                        onClick={() => addAppliance(appliance)}
                        disabled={added}
                        className={`flex w-full items-center justify-between gap-2 border px-3 py-2
                          text-left text-sm transition-colors ${
                            added
                              ? 'cursor-not-allowed border-line text-ink-4'
                              : 'border-line text-ink-1 hover:border-solar hover:text-solar'
                          }`}
                      >
                        <span className="truncate">{appliance.label}</span>
                        <span className="num shrink-0 text-2xs text-ink-4">
                          {added ? 'added' : `${appliance.typical_watts} W`}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      {equipment.length === 0 ? (
        <p className="text-sm text-ink-3">
          Nothing added yet. Start with the big things — air conditioning, refrigeration,
          water heating — and add lights and fans after.
        </p>
      ) : (
        <ul className="space-y-2">
          {equipment.map((item, index) => {
            const spec = specFor(item.key);
            if (!spec) return null;
            return (
              <li key={item.key} className="border border-line bg-surface-1 p-3">
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium text-ink-1">{spec.label}</span>
                  <span className="num text-2xs text-ink-4">{spec.typical_watts} W each</span>
                </div>
                {spec.hint ? (
                  <p className="mb-2 text-xs text-ink-3">{spec.hint}</p>
                ) : null}
                <div className="grid gap-3 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto]">
                  <NumberCell
                    label="How many"
                    value={item.count}
                    min={1}
                    onChange={(v) => update(index, { count: v })}
                  />
                  <NumberCell
                    label="Hours a day"
                    value={item.hours_per_day ?? spec.default_hours_per_day}
                    min={0}
                    max={24}
                    onChange={(v) => update(index, { hours_per_day: v })}
                  />
                  <NumberCell
                    label="Days a month"
                    value={item.days_per_month ?? spec.default_days_per_month}
                    min={0}
                    max={31}
                    onChange={(v) => update(index, { days_per_month: v })}
                  />
                  <button
                    type="button"
                    onClick={() => onEquipmentChange(equipment.filter((_, i) => i !== index))}
                    aria-label={`Remove ${spec.label}`}
                    className="tap self-end border border-line px-2 text-ink-3 transition-colors
                      hover:border-critical hover:text-critical"
                  >
                    <Icon name="trash" size={16} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {monthlyEstimate > 0 ? (
        <div className="mt-4 border border-line bg-surface-2 px-4 py-3">
          <p className="text-sm text-ink-1">
            That comes to roughly{' '}
            <span className="num font-medium text-solar">
              {Math.round(monthlyEstimate).toLocaleString()} units
            </span>{' '}
            a month.
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-3">
            A rough running total. The final figure accounts for equipment that switches
            itself on and off — a fridge left at 24 hours is not counted as running flat out
            for 24 hours.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function NumberCell({
  label,
  value,
  unit,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-2xs uppercase tracking-[0.08em] text-ink-4">
        {label}
        {unit ? ` (${unit})` : ''}
      </span>
      <input
        type="number"
        inputMode="decimal"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) onChange(next);
        }}
        className="num w-full border border-line-strong bg-surface-1 px-2.5 py-2 text-sm
          text-ink-1 focus:border-solar focus:outline-none"
      />
    </label>
  );
}
