import { PAPER_URL } from "../config";
import { StatBox } from "../components/ui";
import { fmtPct } from "../lib/format";
import type { EquityPoint, PaperBlock } from "../types";

export function PortfolioView({ paper }: { paper: PaperBlock }) {
  const s = paper.summary;
  const curve = paper.equity_curve ?? [];

  if (!s || s.n_closed + s.n_open === 0) {
    return (
      <div className="px-4 pt-2 pb-28">
        <Header />
        <div className="mt-24 text-center" style={{ color: "var(--color-faint)" }}>
          <div className="text-[40px] mb-2">🧪</div>
          <div className="text-[14px]">아직 가상 매매 기록이 없어요.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 pt-2 pb-28 flex flex-col gap-3">
      <Header />

      <div className="surface rounded-[18px] p-4">
        <div className="text-[12px]" style={{ color: "var(--color-faint)" }}>
          누적 수익률
        </div>
        <div
          className="tnum text-[34px] font-bold leading-none mt-1"
          style={{ color: (s.total_return_pct ?? 0) >= 0 ? "var(--color-up)" : "var(--color-down)" }}
        >
          {fmtPct(s.total_return_pct)}
        </div>
        <Sparkline curve={curve} start={s.start_equity} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <StatBox label="평가금">{Math.round(s.current_equity).toLocaleString()}</StatBox>
        <StatBox label="승률">{s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : "—"}</StatBox>
        <StatBox label="손익비 (PF)">{fmtPF(s.profit_factor)}</StatBox>
        <StatBox label="MDD">{fmtPct(s.max_drawdown_pct)}</StatBox>
        <StatBox label="청산 / 보유">
          {s.n_closed} / {s.n_open}
        </StatBox>
        <StatBox label="평균 보유">{s.avg_holding != null ? `${s.avg_holding.toFixed(1)}일` : "—"}</StatBox>
      </div>

      {(paper.by_grade?.length ?? 0) > 0 && (
        <div className="surface rounded-[16px] p-4">
          <div className="text-[12px] mb-2" style={{ color: "var(--color-faint)" }}>
            등급별 성과
          </div>
          {paper.by_grade!.map((b) => (
            <Row key={b.key} left={`등급 ${b.key}`} mid={`${b.n}건 · 승률 ${(b.win_rate * 100).toFixed(0)}%`} right={fmtPct(b.avg_return)} pos={b.avg_return >= 0} />
          ))}
        </div>
      )}

      {(paper.recent_closed?.length ?? 0) > 0 && (
        <div className="surface rounded-[16px] p-4">
          <div className="text-[12px] mb-2" style={{ color: "var(--color-faint)" }}>
            최근 청산
          </div>
          {paper.recent_closed!.slice(0, 12).map((t, i) => {
            const ret = num(t.return_pct);
            return (
              <Row
                key={i}
                left={String(t.ticker ?? "")}
                mid={`${t.exit_date ?? ""} · ${t.holding_days ?? "?"}일`}
                right={fmtPct(ret)}
                pos={(ret ?? 0) >= 0}
              />
            );
          })}
        </div>
      )}

      <a
        href={PAPER_URL}
        target="_blank"
        rel="noreferrer"
        className="surface surface-press rounded-[14px] h-12 flex items-center justify-center text-[14px] font-semibold mt-1"
        style={{ color: "var(--color-accent)" }}
      >
        전체 대시보드 열기 ↗
      </a>
    </div>
  );
}

function Header() {
  return (
    <div className="px-1 mb-1">
      <h2 className="text-[22px] font-extrabold tracking-tight">가상 포트폴리오</h2>
      <p className="text-[12px]" style={{ color: "var(--color-faint)" }}>
        A등급 시그널 가상 매매 · 미래 수익을 보장하지 않습니다.
      </p>
    </div>
  );
}

function Row({ left, mid, right, pos }: { left: string; mid: string; right: string; pos: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5" style={{ borderTop: "1px solid var(--color-line)" }}>
      <div className="min-w-0">
        <span className="tnum text-[14px] font-semibold">{left}</span>
        <span className="ml-2 text-[11px]" style={{ color: "var(--color-faint)" }}>
          {mid}
        </span>
      </div>
      <span className="tnum text-[14px] font-semibold" style={{ color: pos ? "var(--color-up)" : "var(--color-down)" }}>
        {right}
      </span>
    </div>
  );
}

function Sparkline({ curve, start }: { curve: EquityPoint[]; start: number }) {
  const pts = [{ date: "", equity: start, drawdown_pct: 0 }, ...curve];
  if (pts.length < 2) return null;
  const vals = pts.map((p) => p.equity);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const W = 300;
  const H = 56;
  const d = pts
    .map((p, i) => {
      const x = (i / (pts.length - 1)) * W;
      const y = H - ((p.equity - min) / span) * H;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = vals[vals.length - 1] >= start;
  const color = up ? "var(--color-up)" : "var(--color-down)";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full mt-3" style={{ height: 56 }} preserveAspectRatio="none">
      <path d={`${d} L${W},${H} L0,${H} Z`} fill={color} opacity={0.12} />
      <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
    </svg>
  );
}

function num(x: unknown): number | null {
  const n = typeof x === "number" ? x : parseFloat(String(x));
  return isFinite(n) ? n : null;
}
function fmtPF(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(2);
}
