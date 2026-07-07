# 진입 성격 다변화 설계 (2026-07-07)

## 배경

소유자 피드백 4건: (1) 과매수 종목만 추천되어 진입이 어렵다, (2) 눌림목(설거지가
아닌) 추천 요청, (3) 와이코프 "distribution 마무리" 추천 가능 여부, (4) tape
reading 가능 여부.

2026-07-02 시그널 품질 개선 스펙의 후속. 당시 결과가 이번 설계의 출발점:

- 과열 가드 3종은 **구현 완료**됐으나 사전등록 기준(승률 +3%p) 미달로 미채택.
- 눌림목 계열 3전략(pullback / connors_rsi2 / zscore_meanrev) 전부 게이트 탈락.
  단, zscore_meanrev는 **표본만 부족**(OoS n=14<20, PF 1.77, bear PF 4.47).
- wyckoff_spring 탈락 (PF 0.73, n=12 — 표본 부족 포함).

### 용어 정리 (소유자와 합의됨)

- **매집(accumulation)** 완료 → 상승(markup). **분산(distribution)** 완료 →
  하락(markdown). 분산 = 속어로 "설거지". 분산 완료 시점 매수는 하락 구간을
  통째로 맞으므로 롱온리 3–20일 스윙에 부적합 — 요청 (3)은 매수 추천이 아닌
  **회피 경고**(Part 3)로, 상승 전환 진입은 **매집 완료 = spring**(Part 2c)으로
  대응한다.
- 고점 횡보가 분산이 아닌 **재매집**일 가능성이 있으므로 분산 의심은 차단이
  아닌 배지 표시만 한다 — 재매집으로 판명되면 이후 spring 신호가 잡는다.
- 요청 (4) tape reading: 틱/호가 데이터는 무료 일봉 파이프라인에서 불가.
  일봉 근사인 VPA(이미 구현: climax/소진/Weis wave)를 노출하는 것으로 대응
  (Part 4).

## 소유자 결정 사항 (2026-07-07 승인)

1. **과열 가드 새 채택 기준 승인**: OoS PF ≥ 베이스라인 ×1.05 AND OoS 승률 ≥
   베이스라인 −1%p AND OoS n ≥ ×0.7. 이 기준은 7/2 결과를 본 뒤 수립된
   **사후(post-hoc) 기준**이며, 이 사실을 YAML 주석과 리포트에 명시한다.
2. **분산 의심 처리 = 배지 표시만** (텔레그램 발송 제외/완전 제외 안 함).
3. **wyckoff_spring 표본 확대 재검증을 범위에 추가.**
4. 설계 전체 및 실행 순서(3→4→1→2) 승인.

## Part 3 — 분산(설거지) 배지 전면화 [실행 1순위]

- 보유 종목 전용이던 `src/risk/distribution.py` `check_distribution()`
  (UTAD/Buying Climax 감지)을 **시그널 후보 종목에도** 실행한다.
- 훅 지점: `signal_engine.scan_market()` — 시그널 종목의 지표 프레임은 이미
  `signal_frames`에 유지되므로 추가 fetch/메모리 부담 없음 (8GB 규칙 준수).
- 출력: 텔레그램 시그널 카드 + HTML 리포트에 "분산 의심" 경고 배지(한국어),
  헬스체크에 배지 부착 건수 카운트.
- **차단하지 않는다** — "시스템은 추천하고 인간이 결정한다" 원칙 + 재매집
  가능성 + 차단 효과 미검증. 이 감지기는 Part 2b의 거부 필터와 부품을 공유.

## Part 4 — VPA 컨텍스트 노출 [실행 2순위]

- 기존 VPA 엔진 출력(`diagnose_stage_count` / `wyckoff_badge_kr`,
  climax·소진 플래그)을 시그널 종목 카드·리포트에 **참고 정보 한 줄**로 표시.
- 전략 로직 불변, 표시 전용 → Phase-4 불필요. 사용자 문구 한국어.

## Part 1 — breakout 과열 가드 채택 절차 [실행 3순위]

- 코드 변경 없음 (가드 3종 구현·패리티 테스트 완료 상태).
- 7/2 그리드 결과에 새 기준 적용 → 후보 선정 (현재 데이터로는 max_ext_pct=15가
  유일 통과: PF ×1.10, 승률 −0.3%p, n 0.78×).
- 선정된 가드 파라미터로 **Phase-4 전체 게이트 재통과 후에만** strategies.yaml
  반영 (검증 출력 원문 첨부). 미통과 시 미채택 유지 — "개선 없음"도 결과.

## Part 2 — 과매도/매집 전략 재검증 [실행 4순위, 최대 소요]

공통: 검증 유니버스를 US 77 → 약 150종목으로 확장 (표본 확보 목적). 생존 편향
고지 강화. 무거운 풀런은 GitHub Actions로 (8GB 로컬 규칙).

- **2a. zscore_meanrev**: 유일 탈락 사유가 표본(n=14<20). 확장 유니버스로
  재실행, OoS n ≥ 20 확보 목표. 전 게이트 통과 시에만 활성화.
- **2b. pullback v2**: 기존 진입 조건 + **분산 거부 필터** — 최근 N봉 내
  UTAD/Buying Climax 발생 종목은 눌림이 아닌 분산으로 보고 진입 거부.
  선택적 파라미터(YAML 미설정 = 기존 동작, 패리티 테스트)로 구현 후 Phase-4.
  거부 창 N은 값 2~3개의 소규모 그리드만 비교 (7/2 Part B와 동일한 과적합 방지).
  솔직한 기대치: 베이스라인 OoS PF 0.69는 통과선에서 멀어 탈락 가능성 높음.
- **2c. wyckoff_spring**: 표본 확대(n=12 → 목표 ≥20) 재검증. "매집 마무리
  진입" 요청의 정공법. 통과 시에만 활성화.

활성 상한 확인: 현재 1개 활성, 전부 통과해도 최대 4개 — 7-cap 이내.

## 테스트 전략

- 모든 코드 변경 TDD (실패 테스트 → 구현 → 전체 스위트).
- Part 3/2b: 파라미터/플래그 부재 시 기존 동작과 바이트 동일 패리티 테스트.
- 커밋 전 `.venv/bin/pytest tests/ -q` 그린 필수.
- YAML `enabled` 변경은 검증 리포트 실행 출력 원문 첨부 후에만
  (reporting-integrity). 백테스트는 과거 성과 — 미래 수익 보장 없음 고지 유지.

## 실행 순서

**3 → 4 → 1 → 2** — 공유 감지기 먼저, 표시 전용 다음, 검증 절차 재사용,
무거운 백테스트 마지막.

## 실행 결과 (2026-07-07 진행 로그)

### Part 4 — 코드 변경 없음 (기구현 확인)

VPA 컨텍스트는 U4/U5에서 이미 구현되어 있음을 확인: 텔레그램 카드 와이코프 배지
(messages.py), 리포트 VPA 단계 체크리스트 + 주봉 컨텍스트 (report.html.j2 —
lw_chart.vpa_diagnosis). 추가 구현은 YAGNI로 생략. Part 3의 분산 배지가
매도측(sell-side) 컨텍스트를 보완한다.

### Part 1 — 과열 가드 Phase-4 재검증

**절차**: `tests/validate_breakout_guard.py` 신규 작성 — breakout 전략에
`max_ext_pct=15.0` 가드를 적용한 config로 `validate_strategy()`(Phase-4 전체
게이트: OoS PF>1, WR 유지, walk-forward 3분할, Monte Carlo(1,000회, 10%
사이징) MDD 상한, 파라미터 민감도 ±20%, 최소 OoS 표본)를 실행. 선정 기준은
owner-approved POST-HOC 기준(2026-07-07, 7/2 그리드 결과를 본 뒤 정의됨 —
투명성 고지): OoS PF ≥ baseline ×1.05 AND OoS WR ≥ baseline −1%p AND OoS
n ≥ baseline ×0.7. 해당 그리드에서 유일 통과 후보가 `max_ext_pct=15`
(PF ×1.10, WR −0.3%p, n 0.78×)였고, 이 스크립트는 그 후보의 **채택 게이트**
— Phase-4 전체를 다시 통과해야만 YAML을 바꾼다.

**실행 명령**: `.venv/bin/python tests/validate_breakout_guard.py` (백그라운드
실행, 표본은 `settings.VAL_SAMPLE_US=160`으로 확장된 유니버스).

**결과: 전체 게이트 PASS.** OoS PF 1.15, OoS WR 40.7%(n=145), walk-forward
3/3(W1=1.85, W2=1.21, W3=1.24), Monte Carlo(1,000회) worst-tail MDD 19.6%,
sensitivity 4/4. 아래는 스크립트의 verbatim, 원문 그대로의 출력.

```
INFO:src.backtest.run_validation:frames[us]: 154/160 sample tickers usable
INFO:src.backtest.validation:[breakout] generating entry plans for 154 tickers...
INFO:src.backtest.validation:[breakout] gates: {'G1_oos_pf_gt_1': True, 'G2_wr_holdup': True, 'G3_walk_forward': True, 'G4_mc_mdd_bound': True, 'G5_sensitivity': True, 'G6_min_oos_trades': True} -> PASS
breakout + max_ext_pct=15 — US sample 154 (GATING)
주의: 생존 편향(현재 유니버스 기준) — 결과는 과거 성과이며 미래 보장 없음
### breakout — PASS → enabled
| metric | IS | OoS |
|---|---|---|
| trades | 282 | 145 |
| win rate | 45.0% | 40.7% |
| profit factor | 1.28 | 1.15 |
- walk-forward PF: W1=1.85(n=84), W2=1.21(n=167), W3=1.24(n=175)
- Monte Carlo(1000): 5%ile final equity x0.95, worst-tail MDD 19.6%
- sensitivity: vol_multx0.8→PF 1.646✓, vol_multx1.2→PF 1.658✓, adx_minx0.8→PF 1.816✓, adx_minx1.2→PF 2.132✓
- regimes: bull: n=349, PF=1.20, bear: n=12, PF=0.30, sideways: n=66, PF=1.88
- benchmark (index B&H same span): +72.5%
- gates: ✅G1_oos_pf_gt_1 ✅G2_wr_holdup ✅G3_walk_forward ✅G4_mc_mdd_bound ✅G5_sensitivity ✅G6_min_oos_trades
```

**결정: 채택.** `config/strategies.yaml` breakout 블록 `params`에
`max_ext_pct: 15.0`을 브리프 지정 정확한 주석과 함께 추가함
(2026-06-12/07-02 기존 주석 블록 아래에 07-07 재검증 요약 주석도 추가).
정직한 고지: 선정 기준 자체가 POST-HOC(그리드 결과를 본 뒤 정의)였음을
위 절차 설명에 명시했고, 백테스트 결과는 과거 성과이며 미래 수익을
보장하지 않고, 생존 편향(현재 US 유니버스 기준)이 적용된다.

**테스트 여파 (투명 공개):** YAML 반영 직후 `.venv/bin/pytest tests/ -q`가
4건 실패 — `tests/test_strategies.py`의 `TestBreakout::test_fires`,
`TestBreakoutOverheatGuards::test_baseline_has_exactly_four_conditions`,
`::test_max_ext_atr_blocks_and_passes`, `::test_rsi_max_blocks_and_passes`.
원인 조사: `CFG = load_strategy_config()`가 실제 운영 YAML을 그대로 읽으므로
(single source of truth), 이제 CFG에 `max_ext_pct=15`가 항상 포함된다.
(1) `TestBreakoutOverheatGuards.cfg_with()`는 기존에 CFG 위에 `update()`로
가드 파라미터를 얹는 방식이라, 다른 종류의 가드(`max_ext_atr`, `rsi_max`)를
개별 테스트할 때 이미 baked-in된 `max_ext_pct=15`와 이중으로 겹쳐 픽스처의
ext_pct(+22%)를 차단 — "가드 1개씩 격리 테스트"라는 원래 의도가 깨짐.
(2) `test_baseline_has_exactly_four_conditions`도 같은 이유로 조건 개수가
4가 아니라 5로 나옴. 수정: `cfg_with()`가 이제 알려진 가드 키 3종을 먼저
전부 pop한 뒤 요청된 것만 적용하도록 바꿔 원래의 격리 의도를 운영 YAML
내용과 무관하게 복원함 (운영 채택과 무관한 순수 테스트 위생 수정).
(3) `TestBreakout::test_fires`는 가드와 무관한 일반 돌파 발화 테스트인데
고정된 sma20=50, close=61로 ext_pct=+22%가 되어 신규 채택된 15% 가드에
막힘 — 픽스처에 `sma20=54.0`을 명시해 ext_pct≈13%로 낮춰 가드 아래에서
정상 발화하도록 수정(가드 자체를 우회/무력화하지 않음, 조건 계산 로직은
무변경). 수정 후 `.venv/bin/pytest tests/ -q` → 175 passed. 정직 고지: 이
수정은 "YAML 파라미터 채택이 optional-key parity를 깨지 않아야 한다"는
브리프 조건을 만족시키기 위해 필요했고, 프로덕션 전략 로직(`conditions()`)은
전혀 건드리지 않았다 — 테스트 픽스처/격리 헬퍼만 수정했다.
