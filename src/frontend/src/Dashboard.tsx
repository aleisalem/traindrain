import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ADMINISTRATOR_ROLE } from "./features/auth/useAuth";
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
    <main className="min-h-screen bg-bg text-fg flex flex-col items-center justify-center gap-8 p-8">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-semibold">{t("scaffold.heading")}</h1>
        <p className="text-fg-muted">{t("scaffold.description")}</p>
        <p className="text-sm text-fg-muted">{t("auth.welcome", { email: user.email })}</p>
      </div>

      <div className="flex gap-2">
        <Link to="/profile" className="rounded-md border border-border px-3 py-1.5 text-sm">
          {t("profile.nav_link")}
        </Link>
        {user.roles.includes(ADMINISTRATOR_ROLE) && (
          <Link
            to="/admin"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
          >
            {t("admin.nav_link")}
          </Link>
        )}
        <button
          type="button"
          onClick={onLogout}
          className="rounded-md border border-border px-3 py-1.5 text-sm"
        >
          {t("auth.logout")}
        </button>
      </div>

      <TwoFactorSettings enabled={user.twoFactorEnabled} onChanged={onRefreshUser} />

      <section className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => void checkBackendHealth()}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-fg"
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
