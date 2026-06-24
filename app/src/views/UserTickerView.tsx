import { Sheet } from "../components/Sheet";
import { Delta, StatBox } from "../components/ui";
import { fmtDateRel, fmtPrice, unit } from "../lib/format";
import { externalLinks } from "../lib/signals";
import type { UserTicker } from "../lib/storage";
import type { Quote } from "../types";

/**
 * Lightweight detail for a user-added watchlist ticker. Unlike a recommendation,
 * there is no pipeline analysis/report — just the live quote (current price, day
 * change, P&L since added) plus external chart links. Read-only by design.
 */
export function UserTickerView({
  u,
  quote,
  onClose,
  onRemove,
}: {
  u: UserTicker | null;
  quote?: Quote;
  onClose: () => void;
  onRemove: () => void;
}) {
  return (
    <Sheet open={!!u} onClose={onClose} title={u?.ticker}>
      {u && <Body u={u} quote={quote} onRemove={onRemove} />}
    </Sheet>
  );
}

function Body({ u, quote, onRemove }: { u: UserTicker; quote?: Quote; onRemove: () => void }) {
  const current = quote && !quote.error ? quote.price : undefined;
  const dayChg = quote && !quote.error ? quote.changePct ?? null : null;
  const sinceAdd =
    current != null && u.price_at_add ? (current / u.price_at_add - 1) * 100 : null;
  const links = externalLinks(u.ticker, u.market, quote?.yahooSymbol);

  return (
    <div className="px-5 pb-8">
      <div className="flex items-baseline gap-2">
        {quote?.name && (
          <span className="text-[15px] truncate" style={{ color: "var(--color-dim)" }}>
            {quote.name}
          </span>
        )}
        <span className="text-[11px]" style={{ color: "var(--color-faint)" }}>
          {u.market.toUpperCase()}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        <span className="tnum text-[30px] font-extrabold">
          {current != null ? fmtPrice(current, u.market) : "시세 대기"}
        </span>
        <span className="text-[14px]" style={{ color: "var(--color-faint)" }}>
          {current != null ? unit(u.market) : ""}
        </span>
        <Delta v={dayChg} className="text-[17px] font-bold" />
        <span className="text-[11px]" style={{ color: "var(--color-faint)" }}>
          당일
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-4">
        <StatBox label="추가일">{fmtDateRel(u.added_date)}</StatBox>
        <StatBox label="추가가격">
          {u.price_at_add != null ? fmtPrice(u.price_at_add, u.market) : "—"}
        </StatBox>
        <StatBox label="현재가">{current != null ? fmtPrice(current, u.market) : "—"}</StatBox>
        <StatBox label="추가가 대비">
          <Delta v={sinceAdd} />
        </StatBox>
      </div>

      <div className="text-[12px] mt-5 mb-2" style={{ color: "var(--color-faint)" }}>
        차트 · 상세 (외부)
      </div>
      <div className="flex flex-col gap-2">
        <a
          href={links.tradingview}
          target="_blank"
          rel="noreferrer"
          className="w-full h-12 rounded-[12px] surface surface-press flex items-center justify-center text-[14px] font-semibold"
          style={{ color: "var(--color-accent)" }}
        >
          📈 TradingView 차트 ↗
        </a>
        <a
          href={links.yahoo}
          target="_blank"
          rel="noreferrer"
          className="w-full h-12 rounded-[12px] surface surface-press flex items-center justify-center text-[14px] font-semibold"
          style={{ color: "var(--color-text)" }}
        >
          Yahoo Finance ↗
        </a>
      </div>

      <button
        onClick={onRemove}
        className="w-full h-11 rounded-[12px] surface surface-press text-[14px] font-semibold mt-5"
        style={{ color: "var(--color-down)" }}
      >
        내 종목에서 삭제
      </button>
    </div>
  );
}
