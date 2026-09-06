import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type Status = "form" | "submitting" | "done";

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("form");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus("submitting");
    try {
      await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
    } catch {
      // Fall through to the same generic confirmation as a successful call.
    }
    // The response never distinguishes a known from an unknown email, so
    // there's nothing to branch on here — always land on the same message.
    setStatus("done");
  }

  if (status === "done") {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("auth.forgot_password_done_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("auth.forgot_password_done_description")}</p>
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
        <h1 className="text-2xl font-semibold">{t("auth.forgot_password_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("auth.forgot_password_description")}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.email_label")}
        <input
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="rounded-md border border-border bg-bg px-3 py-2"
        />
      </label>

      <button
        type="submit"
        disabled={status === "submitting"}
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
      >
        {t("auth.forgot_password_submit")}
      </button>

      <a href="/" className="text-center text-sm text-primary underline">
        {t("auth.forgot_password_back_to_login")}
      </a>
    </form>
  );
}
