/**
 * swing-trader Telegram command webhook (Cloudflare Worker, free tier).
 *
 * Flow: Telegram -> this Worker -> immediate ack reply (cold-start UX rule:
 * the Actions runner takes 15s-1min to boot, silence feels broken) ->
 * repository_dispatch -> commands.yml executes and replies with results.
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
};

const HELP = [
  "📖 사용 가능한 명령:",
  "/add AAPL 230.5 10 — 보유 종목 추가 (티커 가격 수량)",
  "/remove AAPL [청산가] — 보유 종목 제거 (청산가 생략 시 최근 종가로 추정 기록)",
  "/positions — 보유 현황",
  "/scan kr 또는 /scan us — 수동 스캔",
  "/analyze AAPL 또는 /analyze 005930 — 종목 딥 분석",
  "/help — 이 도움말",
].join("\n");

async function sendTelegram(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
  });
}

async function dispatch(env, command, args) {
  const resp = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "swing-trader-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({
      event_type: "telegram-command",
      client_payload: { command, args },
    }),
  });
  return resp.status === 204;
}

export default {
  async fetch(request, env) {
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
};
