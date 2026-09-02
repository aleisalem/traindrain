import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type Status = "form" | "invalid" | "success";

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const [status, setStatus] = useState<Status>("form");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!token) {
      setStatus("invalid");
      return;
    }

    if (password !== confirmPassword) {
      setError(t("auth.reset_password_error_mismatch"));
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      if (response.status === 204) {
        setStatus("success");
        return;
      }
      if (response.status === 410) {
        setStatus("invalid");
        return;
      }
      if (response.status === 422) {
        setError(t("auth.reset_password_error_policy_violation"));
        return;
      }
      setError(t("auth.reset_password_error_unknown"));
    } catch {
      setError(t("auth.reset_password_error_unknown"));
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "invalid") {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("auth.reset_password_invalid_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("auth.reset_password_invalid_description")}</p>
        <a href="/forgot-password" className="mt-4 inline-block text-sm text-primary underline">
          {t("auth.forgot_password_heading")}
        </a>
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("auth.reset_password_success_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("auth.reset_password_success_description")}</p>
        <a href="/" className="mt-4 inline-block text-sm text-primary underline">
          {t("auth.forgot_password_back_to_login")}
        </a>
      </div>
    );
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex w-full max-w-sm flex-col gap-4"
    >
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("auth.reset_password_heading")}</h1>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.new_password_label")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="rounded-md border border-border bg-bg px-3 py-2"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.confirm_password_label")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          className="rounded-md border border-border bg-bg px-3 py-2"
        />
      </label>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
      >
        {t("auth.reset_password_submit")}
      </button>
    </form>
  );
}
