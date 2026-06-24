import { useMemo, useState } from "react";
import { PullToRefresh } from "./components/PullToRefresh";
import { Segmented, CardSkeleton } from "./components/ui";
import { TabBar, type Tab } from "./components/TabBar";
import { DetailView } from "./views/DetailView";
import { AddTickerSheet } from "./views/AddTicker";
import { WatchlistView } from "./views/WatchlistView";
import { PortfolioView } from "./views/PortfolioView";
import { SystemView } from "./views/SystemView";
import { useFeed, useQuotes } from "./hooks";
import { cardKey, cardSymbol, quoteSymbol } from "./lib/signals";
import {
  getHidden,
  getPinned,
  getUserTickers,
  toggleHidden as tHide,
  togglePinned as tPin,
  type UserTicker,
} from "./lib/storage";
import type { Market, SignalCard } from "./types";

export default function App() {
  const [tab, setTab] = useState<Tab>("watch");
  const [market, setMarket] = useState<Market>("us");
  const [detail, setDetail] = useState<SignalCard | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [userTickers, setUserTickers] = useState<UserTicker[]>(getUserTickers());
  const [pinned, setPinned] = useState<string[]>(getPinned());
  const [hidden, setHidden] = useState<string[]>(getHidden());

  const feedQ = useFeed();
  const feed = feedQ.data;
  const signals = feed?.signals ?? [];

  const symbols = useMemo(
    () => [
      ...signals.map((s) => cardSymbol(s)),
      ...userTickers.map((u) => quoteSymbol(u.ticker)),
    ],
    [signals, userTickers]
  );
  const quotesQ = useQuotes(symbols);
  const quotes = quotesQ.data ?? {};

  const pinnedSet = useMemo(() => new Set(pinned), [pinned]);
  const hiddenSet = useMemo(() => new Set(hidden), [hidden]);
  const marketOpen = Object.values(quotes).some((q) => q.marketOpen);
  const lastUpdated = quotesQ.dataUpdatedAt
    ? new Date(quotesQ.dataUpdatedAt).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : null;

  const refresh = () => Promise.all([feedQ.refetch(), quotesQ.refetch()]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header
        className="pt-safe shrink-0 px-4"
        style={{
          background: "color-mix(in srgb, var(--color-bg) 80%, transparent)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
          borderBottom: "1px solid var(--color-line)",
        }}
      >
        <div className="flex items-center justify-between h-12">
          <div className="flex items-center gap-2">
            <span className="text-[19px] font-extrabold tracking-tight">Swing</span>
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: marketOpen ? "var(--color-up)" : "var(--color-faint)" }}
              title={marketOpen ? "장중" : "장마감"}
            />
            {lastUpdated && (
              <span className="text-[11px] tnum" style={{ color: "var(--color-faint)" }}>
                {lastUpdated} {feedQ.isFetching || quotesQ.isFetching ? "·갱신중" : ""}
              </span>
            )}
          </div>
          {tab === "watch" && (
            <button
              onClick={() => setAddOpen(true)}
              className="w-9 h-9 rounded-full surface surface-press flex items-center justify-center text-[20px] leading-none"
              style={{ color: "var(--color-accent)" }}
              aria-label="종목 추가"
            >
              +
            </button>
          )}
        </div>
        {tab === "watch" && (
          <div className="pb-2.5">
            <Segmented
              value={market}
              onChange={setMarket}
              options={[
                { value: "us", label: "🇺🇸 US" },
                { value: "kr", label: "🇰🇷 KR" },
              ]}
            />
          </div>
        )}
      </header>

      {/* Content */}
      {tab === "watch" ? (
        <PullToRefresh onRefresh={refresh}>
          {feedQ.isLoading ? (
            <div className="px-4 pt-3 flex flex-col gap-2.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <CardSkeleton key={i} />
              ))}
            </div>
          ) : feedQ.isError ? (
            <ErrorState onRetry={refresh} />
          ) : (
            <WatchlistView
              market={market}
              signals={signals}
              userTickers={userTickers}
              quotes={quotes}
              pinned={pinnedSet}
              hidden={hiddenSet}
              onOpen={setDetail}
            />
          )}
        </PullToRefresh>
      ) : (
        <div className="scroll-y flex-1 min-h-0">
          {tab === "paper" && <PortfolioView paper={feed?.paper ?? {}} />}
          {tab === "system" &&
            (feed?.system ? (
              <SystemView system={feed.system} />
            ) : (
              <div className="p-8 text-center text-[14px]" style={{ color: "var(--color-faint)" }}>
                불러오는 중…
              </div>
            ))}
        </div>
      )}

      <TabBar tab={tab} onChange={setTab} />

      <DetailView
        card={detail}
        quote={detail ? quotes[cardSymbol(detail)] : undefined}
        pinned={detail ? pinnedSet.has(cardKey(detail)) : false}
        onClose={() => setDetail(null)}
        onTogglePin={() => detail && setPinned(tPin(cardKey(detail)))}
        onHide={() => {
          if (detail) {
            setHidden(tHide(cardKey(detail)));
            setDetail(null);
          }
        }}
      />

      <AddTickerSheet
        open={addOpen}
        onClose={() => setAddOpen(false)}
        tickers={userTickers}
        onChange={setUserTickers}
      />
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mt-24 text-center" style={{ color: "var(--color-faint)" }}>
      <div className="text-[40px] mb-2">⚠️</div>
      <div className="text-[14px] mb-4">피드를 불러오지 못했어요.</div>
      <button
        onClick={onRetry}
        className="px-5 h-10 rounded-[12px] surface surface-press text-[14px] font-semibold"
        style={{ color: "var(--color-accent)" }}
      >
        다시 시도
      </button>
    </div>
  );
}
