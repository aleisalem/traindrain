import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { SUPPORTED_LANGUAGES } from "../../i18n";
import { resolveTheme, THEMES, type Theme } from "../../theme/useTheme";
import type { AuthUser } from "../auth/useAuth";

type Language = (typeof SUPPORTED_LANGUAGES)[number];

type NameResult = { ok: true } | { ok: false; error: "invalid" | "unknown" };
type PreferencesResult = { ok: true } | { ok: false; error: "unknown" };
type PasswordResult =
  | { ok: true }
  | { ok: false; error: "wrong_current_password" | "policy_violation" | "unknown" };

type Props = {
  user: AuthUser;
  onUpdateName: (firstName: string, lastName: string) => Promise<NameResult>;
  onUpdatePreferences: (language: Language, theme: Theme) => Promise<PreferencesResult>;
  onChangePassword: (currentPassword: string, newPassword: string) => Promise<PasswordResult>;
};

export function ProfilePage({ user, onUpdateName, onUpdatePreferences, onChangePassword }: Props) {
  const { t, i18n } = useTranslation();

  const [firstName, setFirstName] = useState(user.firstName ?? "");
  const [lastName, setLastName] = useState(user.lastName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);
  const [savingName, setSavingName] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSaved, setPasswordSaved] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);

  const currentTheme = resolveTheme(user.preferredTheme);
  const currentLanguage = (user.preferredLanguage as Language | null) ?? (i18n.resolvedLanguage as Language);

  async function handleNameSubmit(event: FormEvent) {
    event.preventDefault();
    setSavingName(true);
    setNameError(null);
    setNameSaved(false);
    const result = await onUpdateName(firstName, lastName);
    setSavingName(false);
    if (!result.ok) {
      setNameError(t(`profile.name_error_${result.error}`));
      return;
    }
    setNameSaved(true);
  }

  async function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    setSavingPassword(true);
    setPasswordError(null);
    setPasswordSaved(false);
    const result = await onChangePassword(currentPassword, newPassword);
    setSavingPassword(false);
    if (!result.ok) {
      setPasswordError(t(`auth.change_password_error_${result.error}`));
      return;
    }
    setCurrentPassword("");
    setNewPassword("");
    setPasswordSaved(true);
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-10 p-8">
      <div>
        <Link to="/" className="text-sm text-fg-muted hover:text-fg">
          {t("profile.back_to_dashboard")}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">{t("profile.heading")}</h1>
        <p className="text-sm text-fg-muted">{user.email}</p>
      </div>

      <form onSubmit={(event) => void handleNameSubmit(event)} className="flex max-w-sm flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("profile.name_heading")}</h2>
        <label className="flex flex-col gap-1 text-sm">
          {t("profile.first_name_label")}
          <input
            type="text"
            required
            value={firstName}
            onChange={(event) => setFirstName(event.target.value)}
            className="rounded-md border border-border bg-bg px-3 py-2"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("profile.last_name_label")}
          <input
            type="text"
            required
            value={lastName}
            onChange={(event) => setLastName(event.target.value)}
            className="rounded-md border border-border bg-bg px-3 py-2"
          />
        </label>
        {nameError && (
          <p role="alert" className="text-sm text-danger">
            {nameError}
          </p>
        )}
        {nameSaved && <p className="text-sm text-success">{t("profile.name_saved")}</p>}
        <button
          type="submit"
          disabled={savingName}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
        >
          {t("profile.name_submit")}
        </button>
      </form>

      <form
        onSubmit={(event) => void handlePasswordSubmit(event)}
        className="flex max-w-sm flex-col gap-3"
      >
        <h2 className="text-lg font-semibold">{t("profile.password_heading")}</h2>
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
        {passwordError && (
          <p role="alert" className="text-sm text-danger">
            {passwordError}
          </p>
        )}
        {passwordSaved && <p className="text-sm text-success">{t("profile.password_saved")}</p>}
        <button
          type="submit"
          disabled={savingPassword}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
        >
          {t("profile.password_submit")}
        </button>
      </form>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">{t("profile.language_heading")}</h2>
        <div className="flex gap-2">
          {SUPPORTED_LANGUAGES.map((language) => (
            <button
              key={language}
              type="button"
              onClick={() => void onUpdatePreferences(language, currentTheme)}
              aria-pressed={currentLanguage === language}
              className="rounded-md border border-border px-3 py-1.5 text-sm aria-pressed:bg-primary aria-pressed:text-primary-fg"
            >
              {language.toUpperCase()}
            </button>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">{t("profile.theme_heading")}</h2>
        <div className="flex gap-2">
          {THEMES.map((theme) => (
            <button
              key={theme}
              type="button"
              onClick={() => void onUpdatePreferences(currentLanguage, theme)}
              aria-pressed={currentTheme === theme}
              className="rounded-md border border-border px-3 py-1.5 text-sm aria-pressed:bg-primary aria-pressed:text-primary-fg"
            >
              {t(`profile.theme_${theme}`)}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
