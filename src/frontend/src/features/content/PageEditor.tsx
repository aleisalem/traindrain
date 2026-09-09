import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { pageExtensions } from "../../content/extensions";
import { HEADING_LEVELS, type PageDocument } from "../../content/schema";

type Props = {
  /** The page being edited. Changing the key remounts the editor for a new page. */
  document: PageDocument;
  onChange: (document: PageDocument) => void;
};

const buttonClassName = (active: boolean) =>
  [
    "rounded-full border px-3 py-1 text-xs font-medium transition",
    active
      ? "border-primary bg-primary/10 text-fg"
      : "border-border bg-bg-elevated text-fg-muted hover:text-fg hover:-translate-y-0.5 hover:shadow-[var(--shadow)]",
  ].join(" ");

function ToolbarButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={buttonClassName(active)}
    >
      {label}
    </button>
  );
}

function LinkControls({ editor }: { editor: Editor }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [href, setHref] = useState("");

  const linkActive = editor.isActive("link");

  function apply() {
    const trimmed = href.trim();
    if (trimmed === "") return;
    editor.chain().focus().extendMarkRange("link").setLink({ href: trimmed }).run();
    setHref("");
    setOpen(false);
  }

  return (
    <>
      <ToolbarButton
        label={t("editor.link")}
        active={linkActive}
        onClick={() => {
          setHref((editor.getAttributes("link").href as string | undefined) ?? "");
          setOpen((current) => !current);
        }}
      />
      {linkActive && (
        <ToolbarButton
          label={t("editor.unlink")}
          active={false}
          onClick={() => editor.chain().focus().extendMarkRange("link").unsetLink().run()}
        />
      )}
      {open && (
        <span className="flex items-center gap-2">
          <label className="text-xs text-fg-muted" htmlFor="editor-link-href">
            {t("editor.link_href_label")}
          </label>
          <input
            id="editor-link-href"
            type="text"
            value={href}
            placeholder="https://"
            onChange={(event) => setHref(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                apply();
              }
            }}
            className="rounded-full border border-border bg-bg-elevated px-3 py-1 text-xs focus:border-primary focus:outline-none"
          />
          <button type="button" onClick={apply} className={buttonClassName(false)}>
            {t("editor.link_apply")}
          </button>
        </span>
      )}
    </>
  );
}

function Toolbar({ editor }: { editor: Editor }) {
  const { t } = useTranslation();

  return (
    <div
      role="toolbar"
      aria-label={t("editor.toolbar_label")}
      className="flex flex-wrap items-center gap-2 border-b border-border pb-3"
    >
      {HEADING_LEVELS.map((level) => (
        <ToolbarButton
          key={level}
          label={t("editor.heading", { level })}
          active={editor.isActive("heading", { level })}
          onClick={() => editor.chain().focus().toggleHeading({ level }).run()}
        />
      ))}
      <ToolbarButton
        label={t("editor.bold")}
        active={editor.isActive("bold")}
        onClick={() => editor.chain().focus().toggleBold().run()}
      />
      <ToolbarButton
        label={t("editor.italic")}
        active={editor.isActive("italic")}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      />
      <ToolbarButton
        label={t("editor.code")}
        active={editor.isActive("code")}
        onClick={() => editor.chain().focus().toggleCode().run()}
      />
      <ToolbarButton
        label={t("editor.bullet_list")}
        active={editor.isActive("bulletList")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      />
      <ToolbarButton
        label={t("editor.ordered_list")}
        active={editor.isActive("orderedList")}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      />
      <ToolbarButton
        label={t("editor.blockquote")}
        active={editor.isActive("blockquote")}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      />
      <ToolbarButton
        label={t("editor.code_block")}
        active={editor.isActive("codeBlock")}
        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
      />
      <ToolbarButton
        label={t("editor.horizontal_rule")}
        active={false}
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
      />
      <ToolbarButton
        label={t("editor.hard_break")}
        active={false}
        onClick={() => editor.chain().focus().setHardBreak().run()}
      />
      <LinkControls editor={editor} />
    </div>
  );
}

export function PageEditor({ document, onChange }: Props) {
  const { t } = useTranslation();
  const editor = useEditor({
    extensions: pageExtensions,
    content: document,
    // Rendered inside React, never through an HTML string.
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: "page-prose min-h-48 focus:outline-none",
        "aria-label": t("editor.body_label"),
      },
    },
    onUpdate: ({ editor: instance }) => onChange(instance.getJSON() as PageDocument),
  });

  // No teardown effect here: `useEditor` destroys the instance on unmount
  // itself, and doing it again risks tearing down an editor the hook still
  // holds a reference to.
  if (!editor) return null;

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-4 shadow-[var(--shadow)]">
      <Toolbar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
}
