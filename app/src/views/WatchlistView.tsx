import { useMemo, useState } from "react";
import { SignalCardView } from "../components/SignalCard";
import { Delta } from "../components/ui";
import { fmtPrice } from "../lib/format";
import { cardKey, cardSymbol, isActive, quoteSymbol } from "../lib/signals";
import type { UserTicker } from "../lib/storage";
import type { Market, Quote, QuoteMap, SignalCard } from "../types";

export function WatchlistView({
  market,
  signals,
  userTickers,
  quotes,
  pinned,
  hidden,
  onOpen,
  onOpenUser,
}: {
  market: Market;
  signals: SignalCard[];
  userTickers: UserTicker[];
  quotes: QuoteMap;
  pinned: Set<string>;
  hidden: Set<string>;
  onOpen: (c: SignalCard) => void;
  onOpenUser: (u: UserTicker) => void;
}) {
  const [showPast, setShowPast] = useState(false);
  const [showHidden, setShowHidden] = useState(false);

  const q = (c: SignalCard) => quotes[cardSymbol(c)];

  const { active, past, hiddenCount } = useMemo(() => {
    const mine = signals.filter((s) => s.market === market);
    const visible = mine.filter((s) => showHidden || !hidden.has(cardKey(s)));
    const hiddenCount = mine.filter((s) => hidden.has(cardKey(s))).length;

    const score = (s: SignalCard) => {
      const pin = pinned.has(cardKey(s)) ? 1 : 0;
      return [pin, s.signal_date ?? "", s.strength ?? 0] as const;
    };
    const cmp = (a: SignalCard, b: SignalCard) => {
      const [pa, da, sa] = score(a);
      const [pb, db, sb] = score(b);
      if (pa !== pb) return pb - pa;
      if (da !== db) return da < db ? 1 : -1;
      return sb - sa;
    };
    const active = visible.filter((s) => isActive(s, q(s)?.price)).sort(cmp);
    const past = visible.filter((s) => !isActive(s, q(s)?.price)).sort(cmp);
    return { active, past, hiddenCount };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signals, market, quotes, pinned, hidden, showHidden]);

  const myTickers = userTickers.filter((u) => u.market === market);
  const empty = active.length === 0 && past.length === 0 && myTickers.length === 0;

  return (
    <div className="px-4 pt-2 pb-28 flex flex-col gap-2.5">
      {myTickers.length > 0 && (
        <>
          <SectionLabel>내 종목</SectionLabel>
          {myTickers.map((u) => (
            <UserCard
              key={u.ticker}
              u={u}
              quote={quotes[quoteSymbol(u.ticker)]}
              onOpen={() => onOpenUser(u)}
            />
          ))}
        </>
      )}

      {active.length > 0 && <SectionLabel>추천 · 활성 {active.length}</SectionLabel>}
      {active.map((s) => (
        <SignalCardView
          key={cardKey(s)}
          card={s}
          quote={q(s)}
          pinned={pinned.has(cardKey(s))}
          onOpen={() => onOpen(s)}
        />
      ))}

      {past.length > 0 && (
        <button
          onClick={() => setShowPast((v) => !v)}
          className="mt-2 mb-1 text-[13px] font-semibold text-left"
          style={{ color: "var(--color-dim)" }}
        >
          지난 추천 {past.length} {showPast ? "▲" : "▼"}
        </button>
      )}
      {showPast &&
        past.map((s) => (
          <div key={cardKey(s)} style={{ opacity: 0.62 }}>
            <SignalCardView
              card={s}
              quote={q(s)}
              pinned={pinned.has(cardKey(s))}
              onOpen={() => onOpen(s)}
            />
          </div>
        ))}

      {hiddenCount > 0 && (
        <button
          onClick={() => setShowHidden((v) => !v)}
          className="mt-3 text-[12px] self-center"
          style={{ color: "var(--color-faint)" }}
        >
          {showHidden ? "숨긴 추천 가리기" : `숨긴 추천 ${hiddenCount}개 보기`}
        </button>
      )}

      {empty && (
        <div className="mt-24 text-center" style={{ color: "var(--color-faint)" }}>
          <div className="text-[40px] mb-2">📭</div>
          <div className="text-[14px]">
            {market.toUpperCase()} 추천이 아직 없어요.
            <br />
            아래로 당겨 새로고침하거나 종목을 추가해 보세요.
          </div>
        </div>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="mt-2 mb-0.5 px-1 text-[11px] font-bold tracking-wider uppercase"
      style={{ color: "var(--color-faint)" }}
    >
      {children}
    </div>
  );
}

function UserCard({ u, quote, onOpen }: { u: UserTicker; quote?: Quote; onOpen: () => void }) {
  const current = quote && !quote.error ? quote.price : undefined;
  const sinceAdd =
    current != null && u.price_at_add ? (current / u.price_at_add - 1) * 100 : null;
  const dayChg = quote && !quote.error ? quote.changePct ?? null : null;
  return (
    <button onClick={onOpen} className="surface rise surface-press p-3.5 flex items-center justify-between text-left w-full">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="tnum text-[16px] font-bold">{u.ticker}</span>
          <span className="text-[10px]" style={{ color: "var(--color-faint)" }}>
            {u.market.toUpperCase()}
          </span>
          {quote?.name && (
            <span className="text-[12px] truncate" style={{ color: "var(--color-dim)" }}>
              {quote.name}
            </span>
          )}
        </div>
        <div className="text-[11px] tnum mt-0.5" style={{ color: "var(--color-faint)" }}>
          {u.added_date} · {u.price_at_add != null ? fmtPrice(u.price_at_add, u.market) : "—"} →{" "}
          {current != null ? fmtPrice(current, u.market) : "시세 대기"}
        </div>
      </div>
      <div className="flex flex-col items-end gap-0.5 shrink-0 pl-2">
        <Delta v={sinceAdd} className="text-[16px] font-bold" />
        {dayChg != null && (
          <span className="text-[10px] flex items-center gap-1" style={{ color: "var(--color-faint)" }}>
            당일 <Delta v={dayChg} className="text-[11px]" />
          </span>
        )}
      </div>
    </button>
  );
}
