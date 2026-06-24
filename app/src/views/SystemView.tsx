import { Pill, StatBox } from "../components/ui";
import type { SystemBlock } from "../types";

export function SystemView({ system }: { system: SystemBlock }) {
  const on = system.adaptive_loop_enabled;
  return (
    <div className="px-4 pt-2 pb-28 flex flex-col gap-3">
      <div className="px-1 mb-1">
        <h2 className="text-[22px] font-extrabold tracking-tight">시스템 상태</h2>
        <p className="text-[12px]" style={{ color: "var(--color-faint)" }}>
          적응형 루프 · 송신 컷오프 · 활성 전략
        </p>
      </div>

      <div className="surface rounded-[16px] p-4 flex items-center justify-between">
        <div>
          <div className="text-[14px] font-semibold">적응형 루프</div>
          <div className="text-[12px]" style={{ color: "var(--color-faint)" }}>
            과거 실현 통계 기반 자동 억제
          </div>
        </div>
        <Pill tone={on ? "up" : "dim"}>{on ? "ON" : "OFF"}</Pill>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <StatBox label="기본 송신 컷오프">{fmt(system.min_strength_send)}</StatBox>
        <StatBox label="적용 컷오프">{fmt(system.effective_cutoff)}</StatBox>
      </div>

      <div className="surface rounded-[16px] p-4">
        <div className="text-[12px] mb-2" style={{ color: "var(--color-faint)" }}>
          활성 전략 ({system.enabled_strategies?.length ?? 0})
        </div>
        <div className="flex flex-wrap gap-1.5">
          {(system.enabled_strategies ?? []).map((s) => (
            <Pill key={s.strategy_id} tone="accent">
              {s.name}
            </Pill>
          ))}
          {(system.enabled_strategies?.length ?? 0) === 0 && (
            <span className="text-[13px]" style={{ color: "var(--color-faint)" }}>
              없음
            </span>
          )}
        </div>
      </div>

      {(system.recent_audit?.length ?? 0) > 0 && (
        <div className="surface rounded-[16px] p-4">
          <div className="text-[12px] mb-2" style={{ color: "var(--color-faint)" }}>
            최근 적응 이력
          </div>
          {system.recent_audit!.slice().reverse().map((a, i) => (
            <div key={i} className="py-1.5 text-[12.5px]" style={{ borderTop: "1px solid var(--color-line)" }}>
              <div className="flex justify-between">
                <span className="font-semibold">{a.lever ?? "—"}</span>
                <span className="tnum" style={{ color: "var(--color-faint)" }}>
                  {String(a.ts ?? "").slice(0, 10)}
                </span>
              </div>
              {a.trigger && (
                <div style={{ color: "var(--color-dim)" }}>{a.trigger}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <p className="text-[11px] px-1 mt-1" style={{ color: "var(--color-faint)" }}>
        ※ 시스템은 추천만 제공하며, 매매 판단과 책임은 사용자에게 있습니다.
      </p>
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  return v == null || !isFinite(v) ? "—" : v.toFixed(1);
}
