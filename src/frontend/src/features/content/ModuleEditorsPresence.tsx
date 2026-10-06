import { useTranslation } from "react-i18next";

import type { ModuleEditor } from "./useModuleEditors";

type Props = {
  editors: ModuleEditor[];
  /** What is being edited; picks the wording. */
  subject?: "module" | "campaign";
};

/** "Cora Manager" → "CM"; "cora@example.com" → "C". */
export function initials(displayName: string): string {
  const words = displayName.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0][0].toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/** A stable colour per person, so the same face keeps the same badge. */
function hue(id: string): number {
  let total = 0;
  for (const character of id) total = (total * 31 + character.charCodeAt(0)) % 360;
  return total;
}

/**
 * Who else is in this module right now.
 *
 * Deliberately prominent rather than a subtle hint: this is the warning that
 * the author's next save might land on top of someone's work, and it is only
 * worth anything if they notice it before they type.
 */
export function ModuleEditorsPresence({ editors, subject = "module" }: Props) {
  const { t } = useTranslation();

  if (editors.length === 0) return null;

  const names = editors.map((editor) => editor.display_name).join(", ");

  return (
    <div
      // Polite, not assertive: a colleague arriving should be announced, but
      // not interrupt someone mid-sentence in the editor.
      aria-live="polite"
      className="flex flex-wrap items-center gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3"
    >
      <ul className="flex -space-x-2" aria-hidden="true">
        {editors.map((editor) => (
          <li
            key={editor.id}
            title={editor.display_name}
            style={{
              backgroundColor: `hsl(${hue(editor.id)} 55% 45%)`,
            }}
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-bg-elevated text-xs font-semibold text-white"
          >
            {initials(editor.display_name)}
          </li>
        ))}
      </ul>
      <p className="text-sm">
        <span className="font-medium">
          {t(subject === "campaign" ? "presence.campaign_editing_now" : "presence.editing_now", { count: editors.length, names })}
        </span>{" "}
        <span className="text-fg-muted">{t("presence.overwrite_hint")}</span>
      </p>
    </div>
  );
}
