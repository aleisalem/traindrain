import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { pageExtensions } from "../../content/extensions";
import { HEADING_LEVELS, type PageDocument } from "../../content/schema";
import type { ModuleAsset } from "./types";

/**
 * What the editor needs in order to place a picture: what this module already
 * holds, and a way to add to it. A narrow slice of `ModuleAssetsState` rather
 * than the whole thing, so the editor cannot reach asset *management* — it has
 * no business deleting anything.
 */
export type ImageLibrary = {
  /** The module's uploaded images, the only thing an `image` node may point at. */
  images: ModuleAsset[];
  /** Upload a new image and get it back, so it can be inserted right away. */
  upload: (file: File) => Promise<ModuleAsset | null>;
  busy: boolean;
};

type Props = {
  /** The page being edited. Changing the key remounts the editor for a new page. */
  document: PageDocument;
  onChange: (document: PageDocument) => void;
  library: ImageLibrary;
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

/**
 * Insert an image the module already holds, or upload one and insert it.
 *
 * There is no "image URL" field, deliberately: an `image` node's `src` may only
 * be one of this platform's own asset paths, so anything typed in would be a
 * document the server refuses. Picking from what has been uploaded is not a
 * simplification of the real thing — it *is* the real thing.
 */
function ImageControls({ editor, library }: { editor: Editor; library: ImageLibrary }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [alt, setAlt] = useState("");
  const input = useRef<HTMLInputElement | null>(null);

  function insert(asset: ModuleAsset) {
    const description = alt.trim();
    editor
      .chain()
      .focus()
      // Omitted rather than nulled when empty, so the attribute takes the
      // schema's own default — an empty alt on a decorative image is a
      // meaningful choice, and a made-up one would be worse than none.
      .setImage({ src: asset.url, alt: description === "" ? undefined : description })
      .run();
    setAlt("");
    setOpen(false);
  }

  return (
    <>
      <ToolbarButton
        label={t("editor.image")}
        active={open}
        onClick={() => setOpen((current) => !current)}
      />
      {open && (
        <div className="flex w-full flex-col gap-3 rounded-xl border border-border bg-bg p-3">
          <label className="flex flex-col gap-1 text-xs">
            {t("editor.image_alt_label")}
            <input
              type="text"
              value={alt}
              onChange={(event) => setAlt(event.target.value)}
              placeholder={t("editor.image_alt_placeholder")}
              className="rounded-full border border-border bg-bg-elevated px-3 py-1 text-xs focus:border-primary focus:outline-none"
            />
          </label>
          <p className="text-xs text-fg-muted">{t("editor.image_alt_hint")}</p>

          <div>
            <button
              type="button"
              disabled={library.busy}
              onClick={() => input.current?.click()}
              className={buttonClassName(false)}
            >
              {t("editor.image_upload")}
            </button>
            <input
              ref={input}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              aria-label={t("editor.image_upload")}
              className="sr-only"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (!file) return;
                const uploaded = await library.upload(file);
                // A refusal is reported by the asset panel, which owns the
                // error state; there is simply nothing to insert.
                if (uploaded) insert(uploaded);
              }}
            />
          </div>

          {library.images.length === 0 ? (
            <p className="text-xs text-fg-muted">{t("editor.image_none")}</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {library.images.map((image) => (
                <li key={image.id}>
                  <button
                    type="button"
                    onClick={() => insert(image)}
                    title={image.original_filename}
                    className="rounded-lg border border-border p-1 transition hover:-translate-y-0.5 hover:border-primary hover:shadow-[var(--shadow)]"
                  >
                    <img
                      src={image.url}
                      alt={t("editor.image_insert", { name: image.original_filename })}
                      className="h-16 w-16 rounded object-cover"
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}

function Toolbar({ editor, library }: { editor: Editor; library: ImageLibrary }) {
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
      <ImageControls editor={editor} library={library} />
    </div>
  );
}

export function PageEditor({ document, onChange, library }: Props) {
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
      <Toolbar editor={editor} library={library} />
      <EditorContent editor={editor} />
    </div>
  );
}
