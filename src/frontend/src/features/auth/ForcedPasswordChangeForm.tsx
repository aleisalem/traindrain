import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type ChangePasswordResult =
  | { ok: true }
  | { ok: false; error: "wrong_current_password" | "policy_violation" | "unknown" };

type Props = {
  onChangePassword: (currentPassword: string, newPassword: string) => Promise<ChangePasswordResult>;
};

export function ForcedPasswordChangeForm({ onChangePassword }: Props) {
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await onChangePassword(currentPassword, newPassword);
    setSubmitting(false);
    if (!result.ok) {
      setError(t(`auth.change_password_error_${result.error}`));
    }
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex w-full max-w-sm flex-col gap-4"
    >
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("auth.forced_change_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("auth.forced_change_description")}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.current_password_label")}
        <input
          type="password"
          required
          autoComplete="current-password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
          className="rounded-md border border-border bg-bg px-3 py-2"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.new_password_label")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
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
        {t("auth.change_password_submit")}
      </button>
    </form>
  );
}
