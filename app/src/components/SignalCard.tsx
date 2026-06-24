import { fmtPrice } from "../lib/format";
import { changeFromRec, distToStop, distToTarget, entryStatus } from "../lib/signals";
import type { Quote, SignalCard as Card } from "../types";
import { RiskTrack } from "./RiskTrack";
import { Delta, GradeChip, Pill } from "./ui";

export function SignalCardView({
  card,
  quote,
  pinned,
  onOpen,
}: {
  card: Card;
  quote?: Quote;
  pinned?: boolean;
  onOpen: () => void;
}) {
  const current = quote && !quote.error ? quote.price : undefined;
  const chg = changeFromRec(card, current);
  const status = entryStatus(card, current);
  const dT = distToTarget(card, current);
  const dS = distToStop(card, current);

  return (
    <div className="surface surface-press rise relative p-3.5" onClick={onOpen} role="button">
      {pinned && (
        <span
          className="absolute top-3 right-3 text-[11px]"
          style={{ color: "var(--color-accent)" }}
        >
          ● 고정
        </span>
      )}
      <div className="flex items-start gap-3">
        <GradeChip grade={card.grade} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="tnum text-[17px] font-bold tracking-tight">{card.ticker}</span>
            <span className="truncate text-[13px]" style={{ color: "var(--color-dim)" }}>
              {card.name}
            </span>
          </div>
          <div className="mt-0.5 text-[12px]" style={{ color: "var(--color-faint)" }}>
            {card.strategy_name} · {card.signal_date ? relDays(card.signal_date) : "—"}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <Pill tone={status.tone}>{status.label}</Pill>
        <div className="text-right">
          <Delta v={chg} className="text-[16px] font-bold" />
          <div className="text-[10px]" style={{ color: "var(--color-faint)" }}>
            추천일 종가 대비
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-end justify-between">
        <PriceCol label="추천가" value={fmtPrice(card.price, card.market)} dim />
        <div className="px-2 self-center" style={{ color: "var(--color-faint)" }}>
          →
        </div>
        <PriceCol
          label="현재가"
          value={current != null ? fmtPrice(current, card.market) : "시세 대기"}
        />
      </div>

      <RiskTrack card={card} current={current} />

      <div className="mt-2 flex justify-between text-[11.5px] tnum">
        <span style={{ color: "var(--color-faint)" }}>
          목표 <span style={{ color: dT == null ? "var(--color-faint)" : "var(--color-up)" }}>{fmtSigned(dT)}</span>
        </span>
        <span style={{ color: "var(--color-faint)" }}>
          손절 <span style={{ color: dS == null ? "var(--color-faint)" : "var(--color-down)" }}>{fmtSigned(dS)}</span>
        </span>
      </div>
    </div>
  );
}

function PriceCol({ label, value, dim }: { label: string; value: string; dim?: boolean }) {
  return (
    <div>
      <div className="text-[10px]" style={{ color: "var(--color-faint)" }}>
        {label}
      </div>
      <div
        className="tnum text-[18px] font-semibold leading-tight"
        style={{ color: dim ? "var(--color-dim)" : "var(--color-text)" }}
      >
        {value}
      </div>
    </div>
  );
}

function fmtSigned(v: number | null): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function relDays(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const n = Math.round((today.getTime() - d.getTime()) / 86_400_000);
  if (n <= 0) return "오늘";
  if (n === 1) return "어제";
  if (n < 7) return `${n}일 전`;
  return iso.slice(5).replace("-", "/");
}
