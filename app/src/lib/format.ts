import type { Market } from "../types";

export function fmtPrice(v: number | null | undefined, market: Market): string {
  if (v == null || !isFinite(v)) return "—";
  if (market === "kr") return Math.round(v).toLocaleString("ko-KR");
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function unit(market: Market): string {
  return market === "kr" ? "원" : "$";
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !isFinite(v)) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${v.toFixed(digits)}%`;
}

export function fmtSignedNum(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

export function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((today.getTime() - d.getTime()) / 86_400_000);
}

export function fmtDateRel(iso: string | null | undefined): string {
  const n = daysSince(iso);
  if (n == null) return "—";
  if (n <= 0) return "오늘";
  if (n === 1) return "어제";
  if (n < 7) return `${n}일 전`;
  return iso!.slice(5).replace("-", "/"); // MM/DD
}
