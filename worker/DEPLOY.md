# Cloudflare Worker 배포 가이드 (텔레그램 명령 기능)

> 이 단계는 **선택사항**입니다. 배포하지 않아도 모든 알림(스캔 결과, 매도 알림, 오류 경보)은 정상 작동합니다.
> Worker는 `/add`, `/positions`, `/analyze` 같은 **명령을 보내는 기능**만 담당합니다.
> 소요 시간: 약 15분. 비용: 무료 (Cloudflare 무료 플랜 하루 10만 요청).

## 0. 준비물

- 텔레그램 봇 토큰 (이미 보유)
- 본인 Chat ID (이미 보유)
- GitHub 계정 비밀번호 (PAT 발급용)

## 1. GitHub PAT(개인 액세스 토큰) 발급 — 5분

Worker가 GitHub에 "명령 실행해줘"라고 신호를 보낼 때 쓰는 열쇠입니다.

1. https://github.com/settings/personal-access-tokens/new 접속
2. **Token name**: `swing-trader-worker`
3. **Expiration**: 1년 (만료되면 같은 방법으로 재발급)
4. **Repository access**: "Only select repositories" → `TSLAFSD/swing-trader` 선택
5. **Permissions** → **Repository permissions** → **Contents** → `Read and write` 선택
6. **Generate token** 클릭 → 나오는 `github_pat_...` 문자열을 복사해 메모장에 임시 보관

## 2. Cloudflare 가입 + wrangler 설치 — 5분

1. https://dash.cloudflare.com/sign-up 에서 무료 가입 (이메일 인증까지)
2. 맥 터미널에서:
```bash
npm install -g wrangler
```
(npm이 없다고 나오면 먼저 `brew install node` 실행)

3. Cloudflare 로그인 (브라우저가 자동으로 열립니다):
```bash
wrangler login
```

## 3. Worker 배포 — 3분

터미널에서:
```bash
cd ~/swing-trader/worker
wrangler deploy
```

성공하면 마지막 줄에 Worker 주소가 나옵니다 — **이 주소를 복사해두세요**:
```
https://swing-trader-bot.<본인계정>.workers.dev
```

## 4. Secrets 등록 — 3분

아래 3개를 순서대로 실행합니다. 각각 값 입력 프롬프트가 뜹니다:

```bash
wrangler secret put TELEGRAM_BOT_TOKEN
```
→ 봇 토큰 붙여넣기 (BotFather가 준 `123456:AAE...`)

```bash
wrangler secret put ALLOWED_CHAT_ID
```
→ 본인 Chat ID 숫자 붙여넣기

```bash
wrangler secret put GITHUB_PAT
```
→ 1단계에서 발급한 `github_pat_...` 붙여넣기

## 5. 텔레그램 웹훅 연결 — 1분

아래 명령에서 **두 곳**을 본인 값으로 바꿔 실행합니다:
- `<봇토큰>` → BotFather 토큰
- `<Worker주소>` → 3단계에서 복사한 주소

```bash
curl "https://api.telegram.org/bot<봇토큰>/setWebhook?url=<Worker주소>"
```

`{"ok":true,"result":true,...}` 가 나오면 성공입니다.

## 6. 테스트

텔레그램에서 봇에게 보내보세요:
1. `/help` → 즉시 도움말이 와야 합니다 (Worker가 직접 응답)
2. `/positions` → "⏳ 보유 현황 조회 중" 즉시 수신 → 약 1분 후 보유 현황 도착
3. `/analyze AAPL` → "⏳ 분석 요청 접수" → 1~2분 후 리포트 링크 도착

## 문제 해결

| 증상 | 원인/해결 |
|---|---|
| /help에 무반응 | 5단계 웹훅 URL 오타 — setWebhook 다시 실행 |
| "GitHub 호출 실패" 메시지 | GITHUB_PAT 재확인 — 1단계 권한(Contents R&W)과 저장소 선택 확인 |
| ⏳ 접수 후 결과가 안 옴 | GitHub → Actions 탭에서 `commands` 워크플로 로그 확인 |
| 다른 사람이 봇에게 명령 | 자동 무시됩니다 (ALLOWED_CHAT_ID만 허용) |
