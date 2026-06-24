export type Tab = "watch" | "paper" | "system";

const ICONS: Record<Tab, JSX.Element> = {
  watch: (
    <path
      d="M3 7h18M3 12h12M3 17h7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  ),
  paper: (
    <path
      d="M3 17l5-6 4 3 5-7 4 4"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ),
  system: (
    <>
      <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="2" fill="none" />
      <path
        d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </>
  ),
};

const LABELS: Record<Tab, string> = { watch: "관심", paper: "포트폴리오", system: "시스템" };

export function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav
      className="pb-safe shrink-0"
      style={{
        background: "color-mix(in srgb, var(--color-bg) 86%, transparent)",
        backdropFilter: "blur(18px)",
        WebkitBackdropFilter: "blur(18px)",
        borderTop: "1px solid var(--color-line)",
      }}
    >
      <div className="grid grid-cols-3 px-2 pt-1.5">
        {(Object.keys(LABELS) as Tab[]).map((t) => {
          const active = t === tab;
          return (
            <button
              key={t}
              onClick={() => onChange(t)}
              className="flex flex-col items-center gap-1 py-1.5 transition-colors"
              style={{ color: active ? "var(--color-accent)" : "var(--color-faint)" }}
            >
              <svg width="22" height="22" viewBox="0 0 24 24">
                {ICONS[t]}
              </svg>
              <span className="text-[10.5px] font-semibold">{LABELS[t]}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
