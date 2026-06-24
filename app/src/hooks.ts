import { useQuery } from "@tanstack/react-query";
import { fetchFeed, fetchQuotes } from "./api";
import { POLL_MS } from "./config";
import type { Feed, QuoteMap } from "./types";

export function useFeed() {
  return useQuery<Feed>({
    queryKey: ["feed"],
    queryFn: fetchFeed,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}

export function useQuotes(symbols: string[]) {
  const key = [...new Set(symbols)].sort();
  return useQuery<QuoteMap>({
    queryKey: ["quotes", key],
    queryFn: () => fetchQuotes(key),
    enabled: key.length > 0,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    // Poll only while at least one market is open (battery + quota friendly).
    refetchInterval: (q) => {
      const data = q.state.data as QuoteMap | undefined;
      if (!data) return false;
      const open = Object.values(data).some((v) => v.marketOpen);
      return open ? POLL_MS : false;
    },
    refetchIntervalInBackground: false,
  });
}
