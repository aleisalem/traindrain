import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router-dom";

type Props = {
  onLogout: () => void;
};

export function AdminShell({ onLogout }: Props) {
  const { t } = useTranslation();

  return (
    <div className="min-h-screen bg-bg text-fg flex flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-6">
          <h1 className="text-lg font-semibold">{t("admin.shell_heading")}</h1>
          <nav className="flex gap-4 text-sm">
            <Link to="/admin/users" className="text-fg-muted hover:text-fg">
              {t("adminUsers.nav_link")}
            </Link>
            <Link to="/admin/roles" className="text-fg-muted hover:text-fg">
              {t("adminRoles.nav_link")}
            </Link>
            <Link to="/admin/groups" className="text-fg-muted hover:text-fg">
              {t("adminGroups.nav_link")}
            </Link>
            <Link to="/admin/invites" className="text-fg-muted hover:text-fg">
              {t("invites.nav_link")}
            </Link>
            <Link to="/admin/two-factor" className="text-fg-muted hover:text-fg">
              {t("adminTwoFactor.nav_link")}
            </Link>
            <Link to="/" className="text-fg-muted hover:text-fg">
              {t("admin.back_to_dashboard")}
            </Link>
          </nav>
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="rounded-md border border-border px-3 py-1.5 text-sm"
        >
          {t("auth.logout")}
        </button>
      </header>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
