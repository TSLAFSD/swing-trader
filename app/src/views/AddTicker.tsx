import { useState } from "react";
import { Sheet } from "../components/Sheet";
import { Pill } from "../components/ui";
import { fetchQuotes } from "../api";
import { fmtPrice } from "../lib/format";
import { inferMarket } from "../lib/signals";
import { addUserTicker, removeUserTicker, type UserTicker } from "../lib/storage";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AddTickerSheet({
  open,
  onClose,
  tickers,
  onChange,
}: {
  open: boolean;
  onClose: () => void;
  tickers: UserTicker[];
  onChange: (list: UserTicker[]) => void;
}) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = val.trim().toUpperCase();
  const market = t ? inferMarket(t) : "us";

  async function add() {
    if (!t) return;
    setBusy(true);
    setErr("");
    let price: number | null = null;
    try {
      const q = await fetchQuotes([t]);
      price = q[t]?.price ?? null;
      if (price == null) setErr("시세를 찾지 못했어요. 티커를 확인해 주세요. (그래도 추가됩니다)");
    } catch {
      setErr("시세 조회 실패 — 그래도 추가합니다.");
    }
    onChange(addUserTicker({ ticker: t, market, added_date: today(), price_at_add: price }));
    setVal("");
    setBusy(false);
  }

  return (
    <Sheet open={open} onClose={onClose} title="내 종목 추가">
      <div className="px-5 pb-8">
        <div className="flex gap-2">
          <input
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="티커 입력 (예: NVDA, 005930)"
            autoCapitalize="characters"
            autoCorrect="off"
            className="flex-1 h-12 rounded-[12px] px-4 tnum text-[16px] outline-none"
            style={{
              background: "var(--color-bg)",
              border: "1px solid var(--color-line)",
              color: "var(--color-text)",
            }}
          />
          <button
            onClick={add}
            disabled={!t || busy}
            className="px-5 h-12 rounded-[12px] font-semibold text-[15px]"
            style={{
              background: t ? "var(--color-accent)" : "var(--color-card)",
              color: t ? "#04101f" : "var(--color-faint)",
              opacity: busy ? 0.6 : 1,
            }}
          >
            추가
          </button>
        </div>
        <div className="mt-2 flex items-center gap-2 text-[12px]" style={{ color: "var(--color-faint)" }}>
          {t && <Pill tone={market === "kr" ? "warn" : "accent"}>{market.toUpperCase()}</Pill>}
          <span>{t ? "6자리 숫자는 한국 종목으로 인식합니다." : "추천 외에 직접 관심 종목을 추가할 수 있어요."}</span>
        </div>
        {err && (
          <div className="mt-2 text-[12px]" style={{ color: "var(--color-warn)" }}>
            {err}
          </div>
        )}

        {tickers.length > 0 && (
          <div className="mt-6">
            <div className="text-[12px] mb-2" style={{ color: "var(--color-faint)" }}>
              추가한 종목
            </div>
            <div className="flex flex-col gap-2">
              {tickers.map((u) => (
                <div key={u.ticker} className="surface rounded-[12px] px-3.5 py-2.5 flex items-center justify-between">
                  <div>
                    <span className="tnum text-[15px] font-bold">{u.ticker}</span>
                    <span className="ml-2 text-[11px]" style={{ color: "var(--color-faint)" }}>
                      {u.added_date} 추가 · {u.price_at_add != null ? fmtPrice(u.price_at_add, u.market) : "—"}
                    </span>
                  </div>
                  <button
                    onClick={() => onChange(removeUserTicker(u.ticker))}
                    className="text-[13px] font-semibold"
                    style={{ color: "var(--color-down)" }}
                  >
                    삭제
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Sheet>
  );
}
