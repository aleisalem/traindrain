import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

type Props = {
  onLogout: () => void;
};

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "border-b-2 border-primary pb-0.5 font-semibold text-fg"
    : "border-b-2 border-transparent pb-0.5 text-fg-muted transition-colors hover:text-fg";

export function AdminShell({ onLogout }: Props) {
  const { t } = useTranslation();

  return (
    <div className="min-h-screen bg-bg text-fg flex flex-col">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-bg/80 px-6 py-4 backdrop-blur">
        <div className="flex items-center gap-6">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <svg width="24" height="24" viewBox="0 0 28 28" aria-hidden="true">
              <rect x="2" y="2" width="24" height="24" rx="8" fill="url(#admin-shell-logo)" />
              <path d="M9 14l4-6 4 6-4 6z" fill="var(--primary-fg)" opacity="0.92" />
              <defs>
                <linearGradient id="admin-shell-logo" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="var(--primary)" />
                  <stop offset="1" stopColor="var(--accent)" />
                </linearGradient>
              </defs>
            </svg>
            {t("admin.shell_heading")}
          </h1>
          <nav className="flex gap-4 text-sm">
            <NavLink to="/admin/users" className={navLinkClassName}>
              {t("adminUsers.nav_link")}
            </NavLink>
            <NavLink to="/admin/roles" className={navLinkClassName}>
              {t("adminRoles.nav_link")}
            </NavLink>
            <NavLink to="/admin/groups" className={navLinkClassName}>
              {t("adminGroups.nav_link")}
            </NavLink>
            <NavLink to="/admin/invites" className={navLinkClassName}>
              {t("invites.nav_link")}
            </NavLink>
            <NavLink to="/admin/two-factor" className={navLinkClassName}>
              {t("adminTwoFactor.nav_link")}
            </NavLink>
            <NavLink to="/" end className={navLinkClassName}>
              {t("admin.back_to_dashboard")}
            </NavLink>
          </nav>
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
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
