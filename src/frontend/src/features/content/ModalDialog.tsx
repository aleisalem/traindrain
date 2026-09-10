import type { ReactNode } from "react";

type Props = {
  /** The id of the heading inside `children` that names this dialog. */
  labelledBy: string;
  describedBy?: string;
  onCancel: () => void;
  children: ReactNode;
};

/**
 * The shell every modal in the authoring area shares: the dimmed backdrop, the
 * card, and Escape as the way out.
 *
 * Deliberately holds no buttons and no focus handling. Each dialog decides what
 * it is asking and therefore what should be focused first — the overwrite
 * warning focuses its confirming button, the publish dialog its heading,
 * because nothing there should be one keystroke from confirmed before it has
 * been read.
 */
export function ModalDialog({ labelledBy, describedBy, onCancel, children }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        className="flex w-full max-w-md flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-6 shadow-[var(--shadow)]"
      >
        {children}
      </div>
    </div>
  );
}
