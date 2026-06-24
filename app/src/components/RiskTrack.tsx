import { riskTrack } from "../lib/signals";
import type { SignalCard } from "../types";

/**
 * Signature glanceable bar: stop (left) → target (right), with the entry zone
 * shaded and two markers — hollow = recommended price, filled = current price.
 * One look tells you where price sits in the trade's risk/reward band.
 */
export function RiskTrack({ card, current }: { card: SignalCard; current: number | null | undefined }) {
  const t = riskTrack(card, current);
  if (!t) return null;
  const left = (x: number) => `${(x * 100).toFixed(2)}%`;

  return (
    <div className="mt-3.5 select-none">
      <div
        className="relative h-[7px] rounded-full"
        style={{
          background:
            "linear-gradient(90deg, color-mix(in srgb, var(--color-down) 45%, var(--color-line)), var(--color-line) 38%, var(--color-line) 62%, color-mix(in srgb, var(--color-up) 45%, var(--color-line)))",
        }}
      >
        {t.zoneFrom != null && t.zoneTo != null && (
          <div
            className="absolute top-0 bottom-0 rounded-full"
            style={{
              left: left(t.zoneFrom),
              width: `${Math.max(0, (t.zoneTo - t.zoneFrom) * 100)}%`,
              background: "var(--color-accent)",
              opacity: 0.28,
            }}
          />
        )}
        {t.rec != null && (
          <span
            className="absolute -translate-x-1/2 -translate-y-1/2 top-1/2 w-[11px] h-[11px] rounded-full"
            style={{
              left: left(t.rec),
              background: "var(--color-bg)",
              border: "2px solid var(--color-dim)",
            }}
          />
        )}
        {t.current != null && (
          <span
            className="absolute -translate-x-1/2 -translate-y-1/2 top-1/2 w-[13px] h-[13px] rounded-full"
            style={{
              left: left(t.current),
              background: "var(--color-text)",
              boxShadow: "0 0 0 3px var(--color-bg), 0 0 10px rgba(232,237,244,0.35)",
            }}
          />
        )}
      </div>
      <div className="flex justify-between mt-1.5 text-[10px]" style={{ color: "var(--color-faint)" }}>
        <span>{t.hasStop ? "손절" : ""}</span>
        <span>진입대</span>
        <span>{t.hasTarget ? "목표" : ""}</span>
      </div>
    </div>
  );
}
