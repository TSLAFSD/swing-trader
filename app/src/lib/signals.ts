import { ACTIVE_DAYS } from "../config";
import type { Market, SignalCard } from "../types";
import { daysSince } from "./format";

export function cardKey(c: SignalCard): string {
  return `${c.signal_date}|${c.ticker}|${c.strategy_id}`;
}

/** Quote symbol for a raw ticker (worker resolves bare KR codes .KS→.KQ). */
export function quoteSymbol(ticker: string): string {
  return ticker.trim().toUpperCase();
}

/** Exact quote symbol for a feed card — prefers the pipeline-provided
 * yahoo_symbol (KR carries .KS/.KQ), falling back to the bare ticker. */
export function cardSymbol(c: { ticker: string; yahoo_symbol?: string | null }): string {
  return (c.yahoo_symbol ?? c.ticker).trim().toUpperCase();
}

export function inferMarket(ticker: string): Market {
  return /^\d{6}$/.test(ticker.trim()) ? "kr" : "us";
}

export type EntryState = "below_stop" | "near_stop" | "above_zone" | "in_zone" | "unknown";

export interface StatusBadge {
  state: EntryState;
  label: string;
  tone: "up" | "down" | "warn" | "dim";
}

export function entryStatus(c: SignalCard, current: number | null | undefined): StatusBadge {
  if (current == null || !isFinite(current)) {
    return { state: "unknown", label: "시세 대기", tone: "dim" };
  }
  const { stop_loss: stop, entry_zone_top: top } = c;
  if (stop != null && current <= stop) {
    return { state: "below_stop", label: "손절 이탈", tone: "down" };
  }
  if (stop != null && current <= stop * 1.02) {
    return { state: "near_stop", label: "손절 근접", tone: "warn" };
  }
  if (top != null && current > top) {
    return { state: "above_zone", label: "추격 금지", tone: "warn" };
  }
  return { state: "in_zone", label: "진입 구간", tone: "up" };
}

/** % move from the recommendation-day close to the current price. */
export function changeFromRec(c: SignalCard, current: number | null | undefined): number | null {
  if (current == null || c.price == null || c.price === 0) return null;
  return (current / c.price - 1) * 100;
}

export function distToTarget(c: SignalCard, current: number | null | undefined): number | null {
  if (current == null || c.take_profit == null || current === 0) return null;
  return (c.take_profit / current - 1) * 100;
}

export function distToStop(c: SignalCard, current: number | null | undefined): number | null {
  if (current == null || c.stop_loss == null || current === 0) return null;
  return (c.stop_loss / current - 1) * 100;
}

/**
 * Position of `current` on the stop→target track as a 0..1 fraction, plus the
 * shaded entry-zone band [price, entry_zone_top] on the same scale. Powers the
 * signature risk-track bar. Falls back gracefully when stop/target are missing.
 */
export function riskTrack(c: SignalCard, current: number | null | undefined) {
  const lo = c.stop_loss ?? c.price;
  const hi = c.take_profit ?? (c.entry_zone_top ?? c.price);
  if (lo == null || hi == null || hi <= lo) return null;
  const clamp = (x: number) => Math.max(0, Math.min(1, (x - lo) / (hi - lo)));
  const zoneA = c.price != null ? clamp(c.price) : null;
  const zoneB = c.entry_zone_top != null ? clamp(c.entry_zone_top) : null;
  return {
    current: current != null ? clamp(current) : null,
    rec: c.price != null ? clamp(c.price) : null,
    zoneFrom: zoneA != null && zoneB != null ? Math.min(zoneA, zoneB) : null,
    zoneTo: zoneA != null && zoneB != null ? Math.max(zoneA, zoneB) : null,
    hasStop: c.stop_loss != null,
    hasTarget: c.take_profit != null,
  };
}

export function isActive(c: SignalCard, current: number | null | undefined): boolean {
  const age = daysSince(c.signal_date);
  if (age != null && age > ACTIVE_DAYS) return false;
  const st = entryStatus(c, current).state;
  if (st === "below_stop") return false; // stopped out → 지난 추천
  return true;
}

export function gradeColor(grade: string | null): string {
  if (grade === "A") return "var(--color-gradeA)";
  if (grade === "B") return "var(--color-gradeB)";
  if (grade === "C") return "var(--color-gradeC)";
  return "var(--color-dim)";
}
