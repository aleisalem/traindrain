import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type VerifyResult =
  | { ok: true }
  | { ok: false; error: "invalid_code" | "rate_limited" | "unknown" };

type Props = {
  onVerify: (code: string) => Promise<VerifyResult>;
};

export function TwoFactorVerifyForm({ onVerify }: Props) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await onVerify(code);
    setSubmitting(false);
    if (!result.ok) {
      setError(t(`auth.two_factor_verify_error_${result.error}`));
    }
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex w-full max-w-sm flex-col gap-4"
    >
      <div className="text-center">
        <h1 className="text-2xl font-semibold">{t("auth.two_factor_verify_heading")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("auth.two_factor_verify_description")}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("auth.two_factor_code_label")}
        <input
          type="text"
          required
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
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
        {t("auth.two_factor_verify_submit")}
      </button>
    </form>
  );
}
