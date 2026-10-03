import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AssetKind, ModuleAsset } from "./types";
import type { ModuleAssetsState } from "./useModuleAssets";

type Props = {
  assets: ModuleAssetsState;
};

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0";

/** Byte counts are for people, not for machines. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The accept hints. Convenience for the file picker; the server is the gate. */
const ACCEPT: Record<AssetKind, string> = {
  image: "image/png,image/jpeg,image/gif,image/webp",
  attachment:
    ".pdf,.docx,.xlsx,.pptx,.txt,.csv," +
    "application/pdf," +
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document," +
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet," +
    "application/vnd.openxmlformats-officedocument.presentationml.presentation," +
    "text/plain,text/csv",
};

function UploadButton({
  kind,
  label,
  disabled,
  onPick,
}: {
  kind: AssetKind;
  label: string;
  disabled: boolean;
  onPick: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement | null>(null);

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className={pillClassName}
      >
        {label}
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT[kind]}
        aria-label={label}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Cleared so picking the same file twice in a row still fires.
          event.target.value = "";
          if (file) onPick(file);
        }}
      />
    </>
  );
}

function AssetRow({
  asset,
  disabled,
  onDelete,
}: {
  asset: ModuleAsset;
  disabled: boolean;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);

  return (
    <li className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-bg-elevated p-3">
      {asset.kind === "image" ? (
        <img
          src={asset.url}
          alt=""
          className="h-12 w-12 shrink-0 rounded-lg object-cover"
        />
      ) : (
        <span
          aria-hidden="true"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-border text-lg"
        >
          📄
        </span>
      )}

      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{asset.original_filename}</span>
        <span className="block text-xs text-fg-muted">
          {formatBytes(asset.size_bytes)}
          {asset.kind === "image" &&
            ` · ${t("assets.used_on_pages", { count: asset.referenced_by_pages })}`}
        </span>
      </span>

      {asset.kind === "attachment" && (
        <a
          href={asset.url}
          className="rounded-full border border-border px-3 py-1 text-xs font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("assets.download")}
        </a>
      )}

      {confirming ? (
        <span className="flex items-center gap-2">
          <span className="text-xs text-fg-muted">
            {/* A published version referencing it is the heavier warning and
                wins the line: a snapshot is immutable, so unlike a draft page
                there is no edit that could repair the hole afterwards. */}
            {asset.referenced_by_versions > 0
              ? t("assets.confirm_delete_in_version", {
                  count: asset.referenced_by_versions,
                })
              : asset.referenced_by_pages > 0
                ? t("assets.confirm_delete_in_use", { count: asset.referenced_by_pages })
                : t("assets.confirm_delete")}
          </span>
          <button
            type="button"
            disabled={disabled}
            onClick={onDelete}
            className="rounded-full border border-danger px-3 py-1 text-xs font-medium text-danger disabled:opacity-40"
          >
            {t("assets.confirm_delete_yes")}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded-full border border-border px-3 py-1 text-xs"
          >
            {t("assets.confirm_delete_no")}
          </button>
        </span>
      ) : (
        <button
          type="button"
          disabled={disabled}
          aria-label={t("assets.delete_asset", { name: asset.original_filename })}
          onClick={() => setConfirming(true)}
          className="rounded-full border border-danger px-2 py-0.5 text-xs text-danger disabled:opacity-40"
        >
          ×
        </button>
      )}
    </li>
  );
}

/**
 * A module's images and downloadable files.
 *
 * Deleting asks first, and says how many pages still use the asset — the server
 * allows the deletion either way, so the guard against silently leaving a gap
 * on a page is telling the author before they confirm rather than refusing.
 */
export function ModuleAssetsPanel({ assets }: Props) {
  const { t } = useTranslation();

  if (assets.loadError) {
    return (
      <section className="flex flex-col gap-3">
        <h3 className="text-lg font-medium">{t("assets.heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  const everything = [...assets.images, ...assets.attachments];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-medium">{t("assets.heading")}</h3>
          <p className="text-sm text-fg-muted">{t("assets.description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <UploadButton
            kind="image"
            label={t("assets.upload_image")}
            disabled={assets.busy}
            onPick={(file) => void assets.upload("image", file)}
          />
          <UploadButton
            kind="attachment"
            label={t("assets.upload_attachment")}
            disabled={assets.busy}
            onPick={(file) => void assets.upload("attachment", file)}
          />
        </div>
      </div>

      <p className="text-xs text-fg-muted">
        {t("assets.usage", {
          used: formatBytes(assets.totalBytes),
          total: formatBytes(assets.maxModuleBytes),
        })}
        {" · "}
        {t("assets.per_file_limits", {
          image: formatBytes(assets.maxImageBytes),
          attachment: formatBytes(assets.maxAttachmentBytes),
        })}
      </p>

      {assets.error && (
        <p role="alert" className="text-sm text-danger">
          {assets.error}
        </p>
      )}

      {everything.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("assets.none")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {everything.map((asset) => (
            <AssetRow
              key={asset.id}
              asset={asset}
              disabled={assets.busy}
              onDelete={() => void assets.remove(asset.id)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
