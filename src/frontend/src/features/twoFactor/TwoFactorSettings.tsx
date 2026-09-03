import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type Step =
  | { kind: "idle" }
  | { kind: "confirming"; secret: string; qrCodeDataUri: string }
  | { kind: "recovery_codes"; codes: string[] }
  | { kind: "disabling" }
  | { kind: "error"; message: string };

type Props = {
  enabled: boolean;
  onChanged: () => void | Promise<void>;
};

export function TwoFactorSettings({ enabled, onChanged }: Props) {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [code, setCode] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableError, setDisableError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function startEnrollment() {
    setSubmitting(true);
    const response = await fetch("/api/auth/2fa/enroll", { method: "POST" });
    setSubmitting(false);
    if (!response.ok) {
      setStep({ kind: "error", message: t("security.two_factor_enroll_error") });
      return;
    }
    const body: { secret: string; qr_code_data_uri: string } = await response.json();
    setStep({ kind: "confirming", secret: body.secret, qrCodeDataUri: body.qr_code_data_uri });
  }

  async function handleConfirm(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setConfirmError(null);
    const response = await fetch("/api/auth/2fa/enable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    setSubmitting(false);
    if (!response.ok) {
      setConfirmError(t("security.two_factor_enable_error_invalid_code"));
      return;
    }
    const body: { recovery_codes: string[] } = await response.json();
    setStep({ kind: "recovery_codes", codes: body.recovery_codes });
    setCode("");
  }

  async function finishRecoveryCodes() {
    setStep({ kind: "idle" });
    await onChanged();
  }

  async function handleDisable(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setDisableError(null);
    const response = await fetch("/api/auth/2fa/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: disablePassword }),
    });
    setSubmitting(false);
    if (!response.ok) {
      setDisableError(t("security.two_factor_disable_error_wrong_password"));
      return;
    }
    setStep({ kind: "idle" });
    setDisablePassword("");
    await onChanged();
  }

  if (step.kind === "recovery_codes") {
    return (
      <section className="flex max-w-md flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("security.two_factor_recovery_heading")}</h2>
        <p className="text-sm text-fg-muted">{t("security.two_factor_recovery_description")}</p>
        <ul className="grid grid-cols-2 gap-2 rounded-md border border-border bg-bg p-4 font-mono text-sm">
          {step.codes.map((recoveryCode) => (
            <li key={recoveryCode}>{recoveryCode}</li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => void finishRecoveryCodes()}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg"
        >
          {t("security.two_factor_recovery_done")}
        </button>
      </section>
    );
  }

  if (step.kind === "confirming") {
    return (
      <section className="flex max-w-md flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("security.two_factor_setup_heading")}</h2>
        <p className="text-sm text-fg-muted">{t("security.two_factor_setup_description")}</p>
        <img
          src={step.qrCodeDataUri}
          alt={t("security.two_factor_qr_alt")}
          className="h-40 w-40 self-start rounded-md border border-border bg-bg p-2"
        />
        <p className="text-sm text-fg-muted">
          {t("security.two_factor_setup_key_label")}{" "}
          <span className="font-mono">{step.secret}</span>
        </p>

        <form onSubmit={(event) => void handleConfirm(event)} className="flex flex-col gap-3">
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
          {confirmError && (
            <p role="alert" className="text-sm text-danger">
              {confirmError}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
          >
            {t("security.two_factor_confirm_submit")}
          </button>
        </form>
      </section>
    );
  }

  return (
    <section className="flex max-w-md flex-col gap-3">
      <h2 className="text-lg font-semibold">{t("security.heading")}</h2>
      {enabled ? (
        <>
          <p className="text-sm text-success">{t("security.two_factor_enabled_status")}</p>
          {step.kind === "disabling" ? (
            <form onSubmit={(event) => void handleDisable(event)} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-sm">
                {t("auth.password_label")}
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  value={disablePassword}
                  onChange={(event) => setDisablePassword(event.target.value)}
                  className="rounded-md border border-border bg-bg px-3 py-2"
                />
              </label>
              {disableError && (
                <p role="alert" className="text-sm text-danger">
                  {disableError}
                </p>
              )}
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={submitting}
                  className="self-start rounded-md border border-danger px-4 py-2 text-sm text-danger disabled:opacity-60"
                >
                  {t("security.two_factor_disable_confirm")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setStep({ kind: "idle" });
                    setDisablePassword("");
                    setDisableError(null);
                  }}
                  className="self-start rounded-md border border-border px-3 py-2 text-sm"
                >
                  {t("security.two_factor_disable_cancel")}
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setStep({ kind: "disabling" })}
              className="self-start rounded-md border border-border px-3 py-2 text-sm"
            >
              {t("security.two_factor_disable_button")}
            </button>
          )}
        </>
      ) : (
        <>
          <p className="text-sm text-fg-muted">{t("security.two_factor_disabled_status")}</p>
          {step.kind === "error" && (
            <p role="alert" className="text-sm text-danger">
              {step.message}
            </p>
          )}
          <button
            type="button"
            onClick={() => void startEnrollment()}
            disabled={submitting}
            className="self-start rounded-md border border-border px-3 py-2 text-sm disabled:opacity-60"
          >
            {t("security.two_factor_enable_button")}
          </button>
        </>
      )}
    </section>
  );
}
