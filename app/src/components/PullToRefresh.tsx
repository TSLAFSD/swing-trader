import { useRef, useState, type ReactNode } from "react";

const THRESHOLD = 72;

export function PullToRefresh({
  onRefresh,
  children,
}: {
  onRefresh: () => Promise<unknown>;
  children: ReactNode;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const startY = useRef<number | null>(null);
  const [pull, setPull] = useState(0);
  const [busy, setBusy] = useState(false);

  const onTouchStart = (e: React.TouchEvent) => {
    startY.current =
      scroller.current && scroller.current.scrollTop <= 0 ? e.touches[0].clientY : null;
  };
  const onTouchMove = (e: React.TouchEvent) => {
    if (startY.current == null || busy) return;
    const dy = e.touches[0].clientY - startY.current;
    if (dy > 0) setPull(Math.min(dy * 0.5, 110));
  };
  const onTouchEnd = async () => {
    if (pull >= THRESHOLD && !busy) {
      setBusy(true);
      setPull(THRESHOLD);
      try {
        await onRefresh();
      } finally {
        setBusy(false);
        setPull(0);
      }
    } else {
      setPull(0);
    }
    startY.current = null;
  };

  const ready = pull >= THRESHOLD;
  const rotation = busy ? 0 : Math.min(pull / THRESHOLD, 1) * 270;

  return (
    <div className="relative flex-1 min-h-0">
      <div
        className="absolute left-0 right-0 flex justify-center pointer-events-none z-10"
        style={{ top: Math.max(pull - 34, 6), opacity: pull > 6 || busy ? 1 : 0, transition: "opacity .15s" }}
      >
        <div
          className="flex items-center justify-center w-9 h-9 rounded-full surface"
          style={{ color: ready || busy ? "var(--color-accent)" : "var(--color-dim)" }}
        >
          <svg
            className={busy ? "spin" : ""}
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            style={{ transform: busy ? undefined : `rotate(${rotation}deg)`, transition: busy ? undefined : "transform .05s" }}
          >
            <path
              d="M21 12a9 9 0 1 1-2.64-6.36"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
            />
            {!busy && <path d="M21 4v5h-5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />}
          </svg>
        </div>
      </div>
      <div
        ref={scroller}
        className="scroll-y h-full"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        style={{
          transform: `translateY(${pull}px)`,
          transition: startY.current == null ? "transform .28s cubic-bezier(.22,1,.36,1)" : "none",
        }}
      >
        {children}
      </div>
    </div>
  );
}
