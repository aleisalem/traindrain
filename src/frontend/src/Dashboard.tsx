import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ADMINISTRATOR_ROLE, canAuthorContent } from "./features/auth/useAuth";
import type { AuthUser } from "./features/auth/useAuth";
import { TwoFactorSettings } from "./features/twoFactor/TwoFactorSettings";

type HealthState =
  | { status: "idle" }
  | { status: "ok"; backendStatus: string }
  | { status: "error" };

type Props = {
  user: AuthUser;
  onLogout: () => void;
  onRefreshUser: () => Promise<void>;
};

function Dashboard({ user, onLogout, onRefreshUser }: Props) {
  const { t } = useTranslation();
  const [health, setHealth] = useState<HealthState>({ status: "idle" });

  async function checkBackendHealth() {
    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error("non-2xx response");
      const body: { status: string } = await response.json();
      setHealth({ status: "ok", backendStatus: body.status });
    } catch {
      setHealth({ status: "error" });
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-bg text-fg flex flex-col items-center justify-center gap-8 p-8">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 right-[-4rem] -z-10 h-64 w-64 rounded-full opacity-30 blur-[80px]"
        style={{ background: "var(--gradient)" }}
      />

      <div className="relative text-center space-y-2">
        <svg width="40" height="40" viewBox="0 0 28 28" className="mx-auto mb-2" aria-hidden="true">
          <rect x="2" y="2" width="24" height="24" rx="8" fill="url(#dashboard-logo)" />
          <path d="M9 14l4-6 4 6-4 6z" fill="var(--primary-fg)" opacity="0.92" />
          <defs>
            <linearGradient id="dashboard-logo" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="var(--primary)" />
              <stop offset="1" stopColor="var(--accent)" />
            </linearGradient>
          </defs>
        </svg>
        <h1 className="text-3xl font-semibold">{t("scaffold.heading")}</h1>
        <p className="text-fg-muted">{t("scaffold.description")}</p>
        <p className="text-sm text-fg-muted">{t("auth.welcome", { email: user.email })}</p>
      </div>

      <div className="flex gap-2">
        <Link to="/profile" className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]">
          {t("profile.nav_link")}
        </Link>
        {canAuthorContent(user.roles) && (
          <Link
            to="/content"
            className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.nav_link")}
          </Link>
        )}
        {user.roles.includes(ADMINISTRATOR_ROLE) && (
          <Link
            to="/admin"
            className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("admin.nav_link")}
          </Link>
        )}
        <button
          type="button"
          onClick={onLogout}
          className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("auth.logout")}
        </button>
      </div>

      <TwoFactorSettings enabled={user.twoFactorEnabled} onChanged={onRefreshUser} />

      <section className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => void checkBackendHealth()}
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("scaffold.backend_health_button")}
        </button>
        {health.status === "ok" && (
          <p className="text-success text-sm">
            {t("scaffold.backend_health_ok", { status: health.backendStatus })}
          </p>
        )}
        {health.status === "error" && (
          <p className="text-danger text-sm">{t("scaffold.backend_health_error")}</p>
        )}
      </section>
    </main>
  );
}

export default Dashboard;
