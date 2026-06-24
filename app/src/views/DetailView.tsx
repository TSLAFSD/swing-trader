import { useState } from "react";
import { Sheet } from "../components/Sheet";
import { RiskTrack } from "../components/RiskTrack";
import { Delta, GradeChip, Pill, StatBox } from "../components/ui";
import { fmtPrice, unit } from "../lib/format";
import { changeFromRec, entryStatus } from "../lib/signals";
import type { Quote, SignalCard } from "../types";

export function DetailView({
  card,
  quote,
  pinned,
  onClose,
  onTogglePin,
  onHide,
}: {
  card: SignalCard | null;
  quote?: Quote;
  pinned: boolean;
  onClose: () => void;
  onTogglePin: () => void;
  onHide: () => void;
}) {
  return (
    <Sheet open={!!card} onClose={onClose} full title={card?.ticker}>
      {card && (
        <Body card={card} quote={quote} pinned={pinned} onTogglePin={onTogglePin} onHide={onHide} />
      )}
    </Sheet>
  );
}

function Body({
  card,
  quote,
  pinned,
  onTogglePin,
  onHide,
}: {
  card: SignalCard;
  quote?: Quote;
  pinned: boolean;
  onTogglePin: () => void;
  onHide: () => void;
}) {
  const [showReport, setShowReport] = useState(false);
  const [iframeErr, setIframeErr] = useState(false);
  const current = quote && !quote.error ? quote.price : undefined;
  const chg = changeFromRec(card, current);
  const status = entryStatus(card, current);

  return (
    <div className="px-5 pb-8">
      <div className="flex items-center gap-3">
        <GradeChip grade={card.grade} size={36} />
        <div className="min-w-0">
          <div className="text-[15px]" style={{ color: "var(--color-dim)" }}>
            {card.name}
          </div>
          <div className="flex items-center gap-2">
            <span className="tnum text-[15px]">현재가</span>
            <span className="tnum text-[22px] font-bold">
              {current != null ? fmtPrice(current, card.market) : "시세 대기"}
              <span className="text-[13px] ml-0.5" style={{ color: "var(--color-faint)" }}>
                {current != null ? unit(card.market) : ""}
              </span>
            </span>
            <Delta v={chg} className="text-[16px] font-bold" />
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Pill tone={status.tone}>{status.label}</Pill>
        {card.wyckoff_badge && <Pill tone="accent">{card.wyckoff_badge}</Pill>}
        {card.tags.map((t, i) => (
          <Pill key={i} tone="dim">
            {t}
          </Pill>
        ))}
      </div>

      <RiskTrack card={card} current={current} />

      <div className="grid grid-cols-2 gap-2 mt-4">
        <StatBox label="추천가 (추천일 종가)">{fmtPrice(card.price, card.market)}</StatBox>
        <StatBox label="강도 / 등급">
          {card.strength ?? "—"} / {card.grade ?? "—"}
        </StatBox>
        <StatBox label="진입 상단">{fmtPrice(card.entry_zone_top, card.market)}</StatBox>
        <StatBox label="전략">{card.strategy_name}</StatBox>
        <StatBox label="목표가">{fmtPrice(card.take_profit, card.market)}</StatBox>
        <StatBox label="손절가">{fmtPrice(card.stop_loss, card.market)}</StatBox>
      </div>

      {card.reason && (
        <div className="surface rounded-[14px] p-3.5 mt-4">
          <div className="text-[11px] mb-1" style={{ color: "var(--color-faint)" }}>
            추천 근거
          </div>
          <div className="text-[14px] leading-relaxed">{card.reason}</div>
        </div>
      )}

      {card.contrarian.length > 0 && (
        <div className="surface rounded-[14px] p-3.5 mt-3">
          <div className="text-[11px] mb-1.5" style={{ color: "var(--color-faint)" }}>
            반대 신호 ({card.contrarian.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {card.contrarian.map((c, i) => (
              <Pill key={i} tone="warn">
                {c}
              </Pill>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-2 mt-4">
        <button
          onClick={onTogglePin}
          className="flex-1 h-11 rounded-[12px] text-[14px] font-semibold surface surface-press"
          style={{ color: pinned ? "var(--color-accent)" : "var(--color-text)" }}
        >
          {pinned ? "고정 해제" : "고정"}
        </button>
        <button
          onClick={onHide}
          className="flex-1 h-11 rounded-[12px] text-[14px] font-semibold surface surface-press"
          style={{ color: "var(--color-down)" }}
        >
          숨기기
        </button>
      </div>

      {/* Full analysis report — the same HTML the Telegram alert linked to. */}
      {card.report_url && (
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[13px] font-semibold">전체 분석 리포트</div>
            <a
              href={card.report_url}
              target="_blank"
              rel="noreferrer"
              className="text-[13px] font-semibold"
              style={{ color: "var(--color-accent)" }}
            >
              새 탭으로 열기 ↗
            </a>
          </div>
          {!showReport ? (
            <button
              onClick={() => setShowReport(true)}
              className="w-full h-12 rounded-[12px] surface surface-press text-[14px] font-semibold"
              style={{ color: "var(--color-accent)" }}
            >
              📄 리포트 불러오기 (차트 · Wyckoff · 펀더멘털)
            </button>
          ) : iframeErr ? (
            <div className="surface rounded-[14px] p-4 text-[13px]" style={{ color: "var(--color-dim)" }}>
              앱 안에서 리포트를 열 수 없습니다. 위의 “새 탭으로 열기”를 이용해 주세요.
            </div>
          ) : (
            <iframe
              title="analysis report"
              src={card.report_url}
              onError={() => setIframeErr(true)}
              className="w-full rounded-[14px]"
              style={{ height: 540, border: "1px solid var(--color-line)", background: "var(--color-bg)" }}
            />
          )}
        </div>
      )}
    </div>
  );
}
