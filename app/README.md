# Swing Trader — iPhone PWA

읽기 전용 watchlist 뷰어. 추천 종목의 **추천일·추천가 vs 현재가**를 비교하고, 직접 종목을
추가하고, 가상 포트폴리오·시스템 상태를 본다. 매매 명령은 다루지 않는다(기존 Telegram 유지).

데이터 흐름:

```
파이프라인 스캔 → data/app/feed.json (data 브랜치, raw.githubusercontent.com)
시세         → Cloudflare Worker /quote (키 불필요 Yahoo 프록시)
PWA (Cloudflare Pages) ── 위 둘을 읽어 렌더; localStorage = 내 종목/숨김/고정
```

## 개발

```bash
npm install
npm run gen-icons      # icon-src.svg → public/icons/*.png (최초 1회 / 아이콘 변경 시)
npm run dev            # http://localhost:5173
```

라이브 `feed.json`이 아직 없으면(첫 실 스캔 전) dev에서는 `public/sample-feed.json`으로
자동 폴백해 UI가 채워진 상태로 보인다.

## 엔드포인트 오버라이드

`.env.local`로 빌드 타임 주입(기본값은 라이브 인프라):

```
VITE_FEED_URL=https://raw.githubusercontent.com/TSLAFSD/swing-trader/data/app/feed.json
VITE_QUOTE_URL=https://swing-trader-bot.heeminsh.workers.dev/quote
VITE_PAGES_BASE=https://tslafsd.github.io/swing-trader
```

## 빌드 / 배포

```bash
npm run build          # tsc 타입체크 + vite 빌드 → dist/
npm run preview        # dist/ 로컬 미리보기
```

배포는 Cloudflare Pages. CI(`.github/workflows/pwa-deploy.yml`)가 main push 시 `app/`를
빌드해 `wrangler pages deploy dist`로 올린다. 필요한 GitHub Secrets:

- `CLOUDFLARE_API_TOKEN` — Pages 편집 권한 토큰
- `CLOUDFLARE_ACCOUNT_ID`

최초 1회 Pages 프로젝트 생성: `npx wrangler pages project create swing-trader-pwa`.

## 아이폰 설치

Safari로 배포 URL 접속 → 공유 → **홈 화면에 추가**. standalone(전체화면)으로 실행되며,
오프라인이면 마지막으로 받은 데이터를 보여준다.

## 시세 프록시 (worker)

`../worker/worker.js`의 `GET /quote?symbols=AAPL,005930` 라우트. 6자리 숫자는 한국 종목으로
보고 `.KS`(코스피)→`.KQ`(코스닥) 순으로 시도한다. 배포: `cd ../worker && npx wrangler deploy`.
