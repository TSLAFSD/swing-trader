import type { ReactNode } from "react";
import { fmtPct } from "../lib/format";
import { gradeColor } from "../lib/signals";

export function GradeChip({ grade, size = 28 }: { grade: string | null; size?: number }) {
  const c = gradeColor(grade);
  return (
    <span
      className="chip inline-flex items-center justify-center rounded-[10px]"
      style={{
        color: c,
        background: `color-mix(in srgb, ${c} 14%, transparent)`,
        border: `1px solid color-mix(in srgb, ${c} 38%, transparent)`,
        width: size,
        height: size,
        fontSize: size * 0.46,
      }}
    >
      {grade ?? "–"}
    </span>
  );
}

export function Delta({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  const color =
    v == null || !isFinite(v)
      ? "var(--color-dim)"
      : v >= 0
        ? "var(--color-up)"
        : "var(--color-down)";
  return (
    <span className={`tnum ${className}`} style={{ color }}>
      {fmtPct(v)}
    </span>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
}) {
  return (
    <div
      className="grid p-1 rounded-[14px]"
      style={{
        gridTemplateColumns: `repeat(${options.length}, 1fr)`,
        background: "var(--color-bg2)",
        border: "1px solid var(--color-line)",
      }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className="h-9 rounded-[10px] text-[14px] font-semibold transition-colors"
            style={{
              background: active ? "var(--color-card2)" : "transparent",
              color: active ? "var(--color-text)" : "var(--color-dim)",
              boxShadow: active ? "0 1px 0 rgba(0,0,0,0.4), inset 0 0 0 1px var(--color-line2)" : "none",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Pill({ children, tone = "dim" }: { children: ReactNode; tone?: string }) {
  const map: Record<string, string> = {
    up: "var(--color-up)",
    down: "var(--color-down)",
    warn: "var(--color-warn)",
    dim: "var(--color-dim)",
    accent: "var(--color-accent)",
  };
  const c = map[tone] ?? map.dim;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 h-[22px] text-[11px] font-semibold whitespace-nowrap"
      style={{
        color: c,
        background: `color-mix(in srgb, ${c} 13%, transparent)`,
        border: `1px solid color-mix(in srgb, ${c} 30%, transparent)`,
      }}
    >
      {children}
    </span>
  );
}

export function StatBox({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="surface px-3 py-2.5 rounded-[14px]">
      <div className="text-[11px]" style={{ color: "var(--color-faint)" }}>
        {label}
      </div>
      <div className="mt-0.5 text-[15px] font-semibold tnum">{children}</div>
    </div>
  );
}

export function CardSkeleton() {
  return <div className="surface skeleton h-[132px] rounded-[18px]" />;
}
