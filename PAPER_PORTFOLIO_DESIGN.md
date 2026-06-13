# 가상 포트폴리오(페이퍼 트레이딩) — 결과물 포맷 설계

> 목적: 시스템이 추천한 종목을 **가상으로 매매**해서, in-sample 백테스트가 아닌
> **진짜 out-of-sample 성적표**를 쌓는다. 동시에 "어떤 근거로 사고팔았는지"를
> 기계가 다시 읽을 수 있는 형태로 남겨, 나중에 백테스팅·Claude 분석·전략 개선에
> 바로 활용한다.
>
> 이 문서는 **구현 전 데이터 포맷**을 확정하기 위한 설계서다. 코드 작성은 단계별
> 승인(STOP-after-phase) 후 진행한다. (P-A 착수 승인됨 2026-06-14)

---

## 0. 설계 원칙 (왜 이 포맷이 "나중에 효율적"인가)

1. **불변 이벤트를 기록하고, 나머지는 파생한다.** 청산 거래는 append-only로
   남기고, 자산곡선·통계·일지는 전부 파생물(재생성 가능)로 둔다. → 단일 진실
   원천, 분기 충돌·clobber 위험 제거.
2. **결정 시점의 피처를 그 자리에서 박제한다.** 실현 결과(`return_pct`)와 진입
   시점 지표(`Signal.indicators`)를 한 행에 묶으면 = **라벨링된 학습 데이터 1건**.
   나중에 재구성하면 look-ahead(미래 참조) 편향이 끼므로, 지금 저장하지 않으면
   영영 못 쓴다. ← 가장 중요한 재사용 결정.
3. **기존 스키마의 상위집합(superset)으로 만든다.** 종가/청산 컬럼을
   `risk/trade_ledger.py`와 같게 맞추면, 이미 있는 주간 실현손익 분석
   (`discipline_summary_kr`)·서킷브레이커 코드를 **거의 그대로 재사용**한다.
4. **Exit parity 준수.** 가상 청산은 라이브 모니터(`positions.evaluate_position`
   → `exit_engine.check_exit`)를 **그대로 재사용**한다. 별도 청산 로직 금지
   (CLAUDE.md 불변식).
5. **데이터 분기 관례 준수.** 정본은 Parquet/JSON으로 `data/` 아래에 두어 `data`
   분기 publish/restore 글롭(`*.parquet`, `*.json`)에 자동 탑승. **YAML은 분기에
   안 실리므로 가변 상태는 JSON으로 둔다** (`data/state/rebuy.json`과 동일 관례).
6. **가상 ≠ 실보유.** 이 포트폴리오는 owner의 실제 보유가 아니므로 리포트·Pages에
   공개해도 무방하다 (reporting-integrity의 "실보유 비공개"에 안 걸림).

---

## 0-1. ⭐ 핵심: 데이터셋을 둘로 분리

서로 다른 질문에 답하므로 분리한다. 둘 다 `data` 분기에 탑승.

| 데이터셋 | 답하는 질문 | 비용 | 단계 |
|---|---|---|---|
| **`signals.parquet`(피처 보강)** + `forward_returns()` | "어떤 setup이 통하나?" — 모든 추천 + 결과(넓은 표본, ML/Claude 분석) | 기존 파일에 컬럼만 추가 — **거의 공짜** | P-A |
| **`paper/trades.parquet`** (실제 청산엔진으로 굴림) | "이 시스템이 돈을 버나?" — 정직한 OOS 자산곡선 | 신규 모듈 | P-A |

`signals.parquet`은 **가상 매수 안 한 추천까지** 전부 라벨링되므로 표본이 훨씬
넓다. `paper/trades.parquet`은 슬롯·청산을 실제로 굴린 현실적 성적표다.

---

## 1. 데이터 레이아웃

```
data/paper/
  trades.parquet     # 청산 완료된 가상 거래 (정본, 라벨링 데이터셋) — append-only
  open.json          # 현재 보유 중인 가상 포지션 (가변 상태, 소량) — JSON
data/signals/
  signals.parquet    # (기존) 모든 시그널 + [신규] grade·confidence·regime·features
docs/paper/          # 파생물 (P-B에서 매 실행 재생성, 정본 아님)
  equity.json        # 자산 곡선 + 요약 통계 (Pages 차트용)
  journal.md         # 사람/Claude가 읽는 한국어 의사결정 일지
```

### 1-A. `signals.parquet` 보강 (P-A) — 넓은 라벨링 데이터셋

기존 컬럼(`signal_date, ticker, market, strategy_id, strength, price, stop_loss,
take_profit, entry_zone_top`)에 **추가**:

| 신규 컬럼 | 출처 | 용도 |
|---|---|---|
| `grade` | `Signal.grade` (A/B/C) | 등급별 적중률 분해 |
| `grade_value` | `Grade.value` 0~100 | 연속 점수 분석 |
| `confidence` | `conf.score` 0~1 | 신뢰도 vs 결과 상관 |
| `regime_factor` | `regime.downgrade_factor` | 시장국면 영향 |
| `features_json` | `Signal.indicators` (JSON 문자열) | 진입 지표 스냅샷 = 피처 |

기존 `forward_returns()`가 +5d/+10d 라벨을 제공 → (피처 + 라벨) 완성. 옛 행은 신규
컬럼이 NaN(하위호환 OK).

### 1-B. `paper/trades.parquet` (P-A) — 청산된 가상 거래 (정본)

`closed_trades.parquet`(실매매 원장)의 **상위집합**. 한 행 = 가상 거래 1건 =
재사용 가능한 self-contained 학습 샘플(조인 불필요).

| 컬럼 | 설명 |
|---|---|
| `trade_id` | uuid4 |
| `signal_date` `entry_date` | 추천일 / 가상 매수일 |
| `ticker` `market` `strategy_id` | |
| `grade` `grade_value` `strength` `confidence` `regime_factor` | 추천 품질 스냅샷 |
| `entry_rule` | `close` (P-A 고정) — 가상 체결 방식 |
| `entry_price` `entry_fill` `shares` `cash_allocated` | 진입(체결가 = 슬리피지·수수료 반영) |
| `stop_loss` `take_profit` `exit_mode` | 진입 시 계획 |
| `exit_date` `exit_price` `exit_fill` | 청산 |
| `exit_reason` | `stop`\|`trailing`\|`take_profit`\|`time_stop` (Korean 원문은 `exit_rationale_kr`) |
| `holding_days` `return_pct` `pnl` | 실현 성과 (return_pct = 체결가 기준, 통화중립) |
| `mae_pct` `mfe_pct` | 보유 중 최대 손실/이익 구간 — 손절·익절 위치 적정성 분석 |
| `features_json` | 진입 시점 `Signal.indicators` 스냅샷 |
| `rationale_kr` `exit_rationale_kr` | 왜 샀나 / 왜 팔았나 (한국어) |
| `schema_version` | int |

### 1-C. `paper/open.json` (P-A) — 보유 중 가상 포지션 (가변 상태)

JSON 객체 리스트. 필드: `trade_id, signal_date, entry_date, ticker, market,
strategy_id, grade, grade_value, strength, confidence, regime_factor,
entry_price, entry_fill, shares, cash_allocated, stop_loss, take_profit,
exit_mode, peak_close(트레일링 기준 최고 종가), mae_pct, mfe_pct, last_mark_date,
last_close, unrealized_pct, features(dict)`. 청산 시 행을 빼서 `trades`에 append.

### 1-D. 파생물 (P-B — parquet에서 100% 재생성, 정본 아님)

- `equity.json`: 자산곡선 + 누적 통계(총수익률, 승률, PF, 평균보유일, MDD, 등급별·
  전략별 분해), **벤치마크(SPY/QQQ·KOSPI) 대비**.
- `journal.md`: 한국어 의사결정 일지.

---

## 2. 운영 규칙 (시뮬레이션 정책 — owner 확정)

- **편입 대상:** 확정 스캔에서 **A등급 & 송신 컷오프 통과** 시그널, **미국+한국 둘
  다**. (`PAPER_GRADES=("A",)`)
- **체결 가정:** **확정 종가 매수**(`entry_rule="close"`). 슬리피지·수수료는
  `PAPER_SLIPPAGE_BPS`/`PAPER_FEE_BPS`로 양방향 명시 차감.
  - 정직성 노트: "종가 매수"는 스윙 표준이나 살짝 낙관적(종가 확정 후엔 그 가격에
    실제 체결 불가 → 현실은 익일). 슬리피지 가정으로 보정하고 리포트에 명시한다.
    더 보수적인 "익일 시가"는 차후 옵션으로 열어둠.
- **자본 모델(P-A, 단순):** 거래당 고정 노셔널 = `PAPER_START_EQUITY *
  PAPER_TRADE_FRACTION`(기본 10,000 × 0.2). 동시 보유는 `MAX_POSITION_SLOTS`(5)로
  상한. 미국·한국은 **하나의 노셔널 풀을 return 공간에서 공유**(FX 환산 없음 —
  return_pct는 통화중립, 절대 pnl은 추상 노셔널 단위). 자산곡선은 P-B에서 파생.
- **청산:** 매 확정 스캔에서 보유분을 `positions.evaluate_position()`로 평가 —
  **라이브와 동일 경로**(parity).
- **중복 방지:** 이미 open인 ticker는 재진입 안 함. 슬롯 가득이면 점수순으로 스킵.
- **예비(midday) 스캔은 손대지 않음**(in-progress 바 — 트레일링 규칙과 동일).
- **look-ahead 금지:** 순수 forward(OOS). 실현 결과로 전략을 자동 재튜닝하지
  않는다. Claude/백테스트는 **개선안 제안만**, `enabled`/파라미터 변경은 수동
  (CLAUDE.md 활성화 규칙).

---

## 3. 모듈/연동 지점

- 신규 `src/paper/portfolio.py` — `update_paper_portfolio(market, signals, store)`:
  ① open.json 로드 → ② 이 시장 보유분 청산 평가(evaluate_position 재사용) →
  ③ 신규 A등급 진입(확정 종가) → ④ open.json 저장 + 청산분 trades.parquet append.
- `main._scan` 확정 경로에서 `_publish()` **직전**에 1회 호출(파일이 분기에 실리도록).
- `src/backtest/tracker.record_signals` — 보강 컬럼 추가.
- `src/analysis/base_strategy.Signal` — `confidence`/`regime_factor`/`grade_value` 추가.
- `config/settings.py` — `PAPER_*` 설정.

---

## 4. 단계 (각 단계 후 STOP·승인)

- **P-A (포맷·토대) ← 진행 중:** signals.parquet 보강 + `src/paper/portfolio.py`
  (trades.parquet + open.json) + 스캔 배선 + 테스트. *결과물 포맷의 실체 확정.*
- **P-B (리포트):** Pages 자산곡선·통계 카드 + 벤치마크 비교 + Telegram 주간 "가상
  포트폴리오 성과" + **"오늘의 최우선 추천(1등)"** 명시 + journal.md.
- **P-C (피드백 루프):** trades.parquet/signals.parquet을 읽어 "무엇이 통했나"
  (등급별·전략별·지표 구간별 적중률, MAE/MFE 분포) 분석 도구. 개선은 **수동 적용**.
