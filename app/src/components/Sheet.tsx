import { AnimatePresence, motion } from "framer-motion";
import type { ReactNode } from "react";

export function Sheet({
  open,
  onClose,
  title,
  children,
  full = false,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  full?: boolean;
}) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40"
            style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(2px)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="fixed left-0 right-0 bottom-0 z-50 flex flex-col pb-safe"
            style={{
              height: full ? "94vh" : "auto",
              maxHeight: "94vh",
              background: "var(--color-bg2)",
              borderTopLeftRadius: 22,
              borderTopRightRadius: 22,
              borderTop: "1px solid var(--color-line2)",
              boxShadow: "0 -20px 60px rgba(0,0,0,0.55)",
            }}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 34, stiffness: 360 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.4 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 130 || info.velocity.y > 700) onClose();
            }}
          >
            <div className="shrink-0 pt-2.5 pb-1 flex justify-center">
              <span className="w-10 h-1 rounded-full" style={{ background: "var(--color-line2)" }} />
            </div>
            {title && (
              <div className="shrink-0 flex items-center justify-between px-5 pb-3">
                <div className="text-[17px] font-bold">{title}</div>
                <button
                  onClick={onClose}
                  className="text-[14px] font-semibold"
                  style={{ color: "var(--color-accent)" }}
                >
                  닫기
                </button>
              </div>
            )}
            <div className="scroll-y flex-1 min-h-0">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
