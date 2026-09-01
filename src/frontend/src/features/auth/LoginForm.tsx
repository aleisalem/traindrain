import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type LoginResult = { ok: true } | { ok: false; error: "invalid_credentials" | "rate_limited" | "unknown" };

type Props = {
  onLogin: (email: string, password: string) => Promise<LoginResult>;
};

export function LoginForm({ onLogin }: Props) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await onLogin(email, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(t(`auth.login_error_${result.error}`));
    }
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex w-full max-w-sm flex-col gap-4"
    >
      <h1 className="text-center text-2xl font-semibold">{t("auth.login_heading")}</h1>

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

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.password_label")}
        <input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
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
        {t("auth.login_submit")}
      </button>
    </form>
  );
}
