import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type Status =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "ready"; email: string }
  | { kind: "success" };

export function AcceptInvitePage() {
  const { t } = useTranslation();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function checkInvite() {
      if (!token) {
        setStatus({ kind: "invalid" });
        return;
      }
      try {
        const response = await fetch(`/api/invites/${encodeURIComponent(token)}`);
        if (cancelled) return;
        if (!response.ok) {
          setStatus({ kind: "invalid" });
          return;
        }
        const body: { email: string } = await response.json();
        setStatus({ kind: "ready", email: body.email });
      } catch {
        if (!cancelled) setStatus({ kind: "invalid" });
      }
    }

    void checkInvite();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError(t("invites.accept_error_password_mismatch"));
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch(`/api/invites/${encodeURIComponent(token)}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (response.status === 204) {
        setStatus({ kind: "success" });
        return;
      }
      if (response.status === 410) {
        setStatus({ kind: "invalid" });
        return;
      }
      if (response.status === 422) {
        setError(t("invites.accept_error_policy_violation"));
        return;
      }
      setError(t("invites.accept_error_unknown"));
    } catch {
      setError(t("invites.accept_error_unknown"));
    } finally {
      setSubmitting(false);
    }
  }

  if (status.kind === "loading") {
    return <p className="text-sm text-fg-muted">{t("invites.accept_loading")}</p>;
  }

  if (status.kind === "invalid") {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("invites.accept_invalid_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("invites.accept_invalid_description")}</p>
      </div>
    );
  }

  if (status.kind === "success") {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("invites.accept_success_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("invites.accept_success_description")}</p>
        <a href="/" className="mt-4 inline-block text-sm text-primary underline">
          {t("invites.accept_success_login_link")}
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
        <h1 className="text-2xl font-semibold">{t("invites.accept_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">
          {t("invites.accept_description", { email: status.email })}
        </p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("invites.new_password_label")}
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
        {t("invites.confirm_password_label")}
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
        {t("invites.accept_submit")}
      </button>
    </form>
  );
}
