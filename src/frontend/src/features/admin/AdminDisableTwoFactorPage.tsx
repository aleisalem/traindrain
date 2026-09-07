import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type Result = { kind: "idle" } | { kind: "success"; email: string } | { kind: "error"; message: string };

export function AdminDisableTwoFactorPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<Result>({ kind: "idle" });
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setResult({ kind: "idle" });

    const response = await fetch("/api/admin/users/2fa/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    setSubmitting(false);

    if (response.status === 204) {
      setResult({ kind: "success", email });
      setEmail("");
      return;
    }
    if (response.status === 404) {
      setResult({ kind: "error", message: t("adminTwoFactor.error_not_found") });
      return;
    }
    if (response.status === 409) {
      setResult({ kind: "error", message: t("adminTwoFactor.error_not_enabled") });
      return;
    }
    setResult({ kind: "error", message: t("adminTwoFactor.error_unknown") });
  }

  return (
    <div className="flex max-w-md flex-col gap-4">
      <h2 className="text-xl font-semibold">{t("adminTwoFactor.heading")}</h2>
      <p className="text-sm text-fg-muted">{t("adminTwoFactor.description")}</p>

      <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          {t("adminTwoFactor.email_label")}
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none"
          />
        </label>

        {result.kind === "error" && (
          <p role="alert" className="text-sm text-danger">
            {result.message}
          </p>
        )}
        {result.kind === "success" && (
          <p className="text-sm text-success">
            {t("adminTwoFactor.success", { email: result.email })}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="self-start rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {t("adminTwoFactor.submit")}
        </button>
      </form>
    </div>
  );
}
