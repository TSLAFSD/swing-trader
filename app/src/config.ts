// Endpoints. Override at build time with VITE_FEED_URL / VITE_QUOTE_URL.
// Defaults target the live swing-trader infra (repo TSLAFSD/swing-trader).
export const FEED_URL =
  import.meta.env.VITE_FEED_URL ??
  "https://raw.githubusercontent.com/TSLAFSD/swing-trader/data/app/feed.json";

export const QUOTE_URL =
  import.meta.env.VITE_QUOTE_URL ??
  "https://swing-trader-bot.heeminsh.workers.dev/quote";

export const PAGES_BASE =
  import.meta.env.VITE_PAGES_BASE ?? "https://tslafsd.github.io/swing-trader";
export const PAPER_URL = `${PAGES_BASE}/paper.html`;

// How long a recommendation stays in the "활성" (active) section.
export const ACTIVE_DAYS = 14;

// Foreground quote poll interval while a market is open (ms).
export const POLL_MS = 60_000;
