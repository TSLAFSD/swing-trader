/**
 * swing-trader Telegram command webhook + scheduler (Cloudflare Worker, free tier).
 *
 * Command flow: Telegram -> this Worker -> immediate ack reply (cold-start UX
 * rule: the Actions runner takes 15s-1min to boot, silence feels broken) ->
 * repository_dispatch -> commands.yml executes and replies with results.
 *
 * Schedule flow: Cloudflare cron trigger -> this Worker (scheduled handler) ->
 * repository_dispatch -> the matching scan/weekly workflow. This replaces
 * GitHub-native `schedule:` triggers, which lagged multiple hours on the free
 * tier; the API-dispatch path runs promptly. On dispatch failure the owner is
 * alerted on Telegram (the operational safety net for missed runs).
 *
 * Secrets (wrangler secret put ...):
 *   TELEGRAM_BOT_TOKEN  - same bot token as GitHub Secrets
 *   ALLOWED_CHAT_ID     - owner's chat id; everything else is ignored
 *   GITHUB_PAT          - fine-grained PAT, repo TSLAFSD/swing-trader,
 *                         permission: Contents Read&Write (for dispatches)
 */

const REPO = "TSLAFSD/swing-trader";

const COMMANDS = {
  "/add": { args: [2, 3], ack: (a) => `⏳ '${a[0]}' 추가 요청 접수 — 약 1분 소요` },
  "/remove": { args: [1, 2], ack: (a) => `⏳ '${a[0]}' 제거 요청 접수 — 약 1분 소요` },
  "/positions": { args: [0, 0], ack: () => "⏳ 보유 현황 조회 중 — 약 1분 소요" },
  "/scan": { args: [1, 1], ack: (a) => `⏳ ${a[0] === "kr" ? "한국" : "미국"} 스캔 시작 — 약 20~40분 소요` },
  "/analyze": { args: [1, 1], ack: (a) => `⏳ '${a[0]}' 분석 요청 접수 — 약 1~2분 소요` },
  "/feedback": { args: [0, 0], ack: () => "⏳ 페이퍼 트레이딩 분석 중 — 약 1~2분 소요" },
};

const HELP = [
  "📖 사용 가능한 명령:",
  "/add AAPL 230.5 10 — 보유 종목 추가 (티커 가격 수량)",
  "/remove AAPL [청산가] — 보유 종목 제거 (청산가 생략 시 최근 종가로 추정 기록)",
  "/positions — 보유 현황",
  "/scan kr 또는 /scan us — 수동 스캔",
  "/analyze AAPL 또는 /analyze 005930 — 종목 딥 분석",
  "/feedback — 가상 포트폴리오 분석 (무엇이 통했나)",
  "/help — 이 도움말",
].join("\n");

async function sendTelegram(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
  });
}

async function githubDispatch(env, eventType, clientPayload) {
  const resp = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "swing-trader-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ event_type: eventType, client_payload: clientPayload }),
  });
  return resp.status === 204;
}

// Telegram command -> commands.yml (listens on the [telegram-command] type).
async function dispatch(env, command, args) {
  return githubDispatch(env, "telegram-command", { command, args });
}

// ---------------------------------------------------------------------------
// Quote proxy (GET /quote?symbols=AAPL,005930.KS) for the PWA.
//
// Keyless: proxies Yahoo's public /v8 chart endpoint (a User-Agent header is
// MANDATORY — Yahoo returns 429 without one). No API key ever touches the
// client. Read-only market data only; the trading commands above are unaffected.
// The PWA's primary metric is feed-recommendation-price vs current price, so the
// client only needs `price` here; prevClose/changePct are best-effort extras.
// ---------------------------------------------------------------------------
const QUOTE_TTL = 45; // seconds — short cache to spare Yahoo + the free quota
const YF_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36";

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*", // public read-only quotes
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

async function fetchYahooChart(symbol) {
  const url =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
    `?range=1d&interval=1d`;
  let resp;
  try {
    resp = await fetch(url, {
      headers: { "User-Agent": YF_UA, Accept: "application/json" },
      cf: { cacheTtl: QUOTE_TTL, cacheEverything: true },
    });
  } catch (e) {
    return { error: "fetch_failed" };
  }
  if (!resp.ok) return { error: `yahoo_${resp.status}` };
  let data;
  try {
    data = await resp.json();
  } catch {
    return { error: "parse_failed" };
  }
  const m = data?.chart?.result?.[0]?.meta;
  if (!m || m.regularMarketPrice == null) return { error: "no_data" };
  const price = m.regularMarketPrice;
  const prev = m.chartPreviousClose ?? m.previousClose ?? null;
  const changePct = prev ? ((price - prev) / prev) * 100 : null;
  let marketOpen = null;
  const reg = m.currentTradingPeriod?.regular;
  if (reg && reg.start != null && reg.end != null) {
    const now = Math.floor(Date.now() / 1000);
    marketOpen = now >= reg.start && now <= reg.end;
  }
  return {
    price,
    prevClose: prev,
    changePct,
    currency: m.currency ?? null,
    name: m.shortName ?? m.longName ?? null,
    instrumentType: m.instrumentType ?? null,
    marketTime: m.regularMarketTime ?? null,
    marketOpen,
  };
}

// Resolve a client symbol to a Yahoo symbol. Bare 6-digit codes are Korean:
// try KOSPI (.KS) then KOSDAQ (.KQ), preferring an actual EQUITY match (a
// KOSDAQ code can otherwise hit a stale .KS fund). Already-suffixed / US symbols
// pass through. Result is keyed by the ORIGINAL input the client sent.
async function yahooQuote(inputSymbol) {
  const candidates = /^\d{6}$/.test(inputSymbol)
    ? [`${inputSymbol}.KS`, `${inputSymbol}.KQ`]
    : [inputSymbol];
  let fallback = null;
  for (const sym of candidates) {
    const r = await fetchYahooChart(sym);
    if (r.error) continue;
    const out = { symbol: inputSymbol, yahooSymbol: sym, ...r };
    if (candidates.length === 1 || r.instrumentType === "EQUITY") return out;
    fallback = fallback ?? out; // non-equity match — keep only if nothing better
  }
  return fallback ?? { symbol: inputSymbol, error: "no_data" };
}

async function handleQuote(request) {
  const url = new URL(request.url);
  const symbols = (url.searchParams.get("symbols") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 60); // cap batch size
  const headers = {
    ...corsHeaders(),
    "Content-Type": "application/json",
    "Cache-Control": `public, max-age=${QUOTE_TTL}`,
  };
  if (symbols.length === 0) {
    return new Response(JSON.stringify({ error: "no symbols" }), { status: 400, headers });
  }
  const results = await Promise.all([...new Set(symbols)].map(yahooQuote));
  const quotes = {};
  for (const r of results) quotes[r.symbol] = r;
  return new Response(
    JSON.stringify({ quotes, generated: new Date().toISOString() }),
    { headers }
  );
}

// Cloudflare cron expression -> the workflow it should wake. Each scan/weekly
// workflow listens on its own repository_dispatch type (so only the right one
// fires). Keep these crons identical to wrangler.toml [triggers].
const CRON_EVENTS = {
  "37 3 * * 1-5": "cron-kr-midday",
  "47 6 * * 1-5": "cron-kr-close",
  "7 22 * * 1-5": "cron-us-close",
  "37 7 * * 1-5": "cron-us-premarket",
  "7 19 * * 6": "cron-weekly",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // PWA quote proxy (keyless Yahoo passthrough) + CORS preflight.
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }
    if (request.method === "GET" && url.pathname === "/quote") {
      return handleQuote(request);
    }
    // Everything below is the Telegram webhook (POST to /).
    if (request.method !== "POST") return new Response("ok");
    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("ok");
    }
    const msg = update.message;
    const chatId = msg?.chat?.id;
    const text = (msg?.text || "").trim();
    // Silently ignore anything that is not the owner (anti-abuse).
    if (!chatId || String(chatId) !== String(env.ALLOWED_CHAT_ID) || !text.startsWith("/")) {
      return new Response("ok");
    }
    const [cmd, ...args] = text.split(/\s+/);
    if (cmd === "/help" || cmd === "/start") {
      await sendTelegram(env, chatId, HELP);
      return new Response("ok");
    }
    const spec = COMMANDS[cmd];
    if (!spec) {
      await sendTelegram(env, chatId, `❓ 알 수 없는 명령: ${cmd}\n${HELP}`);
      return new Response("ok");
    }
    if (args.length < spec.args[0] || args.length > spec.args[1]) {
      await sendTelegram(env, chatId, `⚠️ 인자 개수가 맞지 않습니다.\n${HELP}`);
      return new Response("ok");
    }
    if (cmd === "/scan" && !["kr", "us"].includes(args[0]?.toLowerCase())) {
      await sendTelegram(env, chatId, "⚠️ /scan kr 또는 /scan us 로 입력해주세요.");
      return new Response("ok");
    }
    // IMMEDIATE ack BEFORE the runner boots, then dispatch.
    await sendTelegram(env, chatId, spec.ack(args));
    const ok = await dispatch(env, cmd, args);
    if (!ok) {
      await sendTelegram(env, chatId, "🚨 GitHub 호출 실패 — Worker의 GITHUB_PAT 설정을 확인하세요.");
    }
    return new Response("ok");
  },

  async scheduled(controller, env, ctx) {
    const eventType = CRON_EVENTS[controller.cron];
    if (!eventType) return; // unmapped cron — ignore rather than guess
    const ok = await githubDispatch(env, eventType, {
      trigger: "cloudflare-cron",
      cron: controller.cron,
    });
    if (!ok && env.ALLOWED_CHAT_ID) {
      ctx.waitUntil(
        sendTelegram(
          env,
          env.ALLOWED_CHAT_ID,
          `🚨 스케줄 트리거 실패 (${eventType}) — Worker가 GitHub Actions를 깨우지 못했습니다. GITHUB_PAT를 확인하세요.`
        )
      );
    }
  },
};
