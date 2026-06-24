import { FEED_URL, QUOTE_URL } from "./config";
import type { Feed, QuoteMap } from "./types";

export async function fetchFeed(): Promise<Feed> {
  try {
    // Cache-bust so pull-to-refresh beats the raw GitHub CDN edge cache.
    const res = await fetch(`${FEED_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`feed ${res.status}`);
    return res.json();
  } catch (e) {
    // Before the first live scan publishes feed.json, fall back to the bundled
    // sample in dev so the UI renders populated. Production surfaces the error.
    if (import.meta.env.DEV) {
      const r = await fetch("/sample-feed.json");
      if (r.ok) return r.json();
    }
    throw e;
  }
}

export async function fetchQuotes(symbols: string[]): Promise<QuoteMap> {
  const uniq = [...new Set(symbols.filter(Boolean))];
  if (uniq.length === 0) return {};
  const url = `${QUOTE_URL}?symbols=${encodeURIComponent(uniq.join(","))}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`quote ${res.status}`);
  const data = (await res.json()) as { quotes: QuoteMap };
  return data.quotes ?? {};
}
