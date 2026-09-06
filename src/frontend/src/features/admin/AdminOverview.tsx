import { useState } from "react";
import { useTranslation } from "react-i18next";

type PingState = { status: "idle" } | { status: "ok" } | { status: "error" };

export function AdminOverview() {
  const { t } = useTranslation();
  const [ping, setPing] = useState<PingState>({ status: "idle" });

  async function checkAdminAccess() {
    try {
      const response = await fetch("/api/admin/ping");
      setPing({ status: response.ok ? "ok" : "error" });
    } catch {
      setPing({ status: "error" });
    }
  }

  return (
    <section className="flex max-w-md flex-col gap-4">
      <h2 className="text-xl font-semibold">{t("admin.overview_heading")}</h2>
      <p className="text-sm text-fg-muted">{t("admin.overview_description")}</p>
      <button
        type="button"
        onClick={() => void checkAdminAccess()}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg"
      >
        {t("admin.ping_button")}
      </button>
      {ping.status === "ok" && <p className="text-sm text-success">{t("admin.ping_ok")}</p>}
      {ping.status === "error" && <p className="text-sm text-danger">{t("admin.ping_error")}</p>}
    </section>
  );
}
