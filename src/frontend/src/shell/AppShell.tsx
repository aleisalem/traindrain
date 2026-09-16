import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import type { AuthUser } from "../features/auth/useAuth";
import { resolveNavPosition } from "../theme/useNavPosition";
import { getNavGroups } from "./navConfig";

type Props = {
  user: AuthUser;
  onLogout: () => void;
};

function initials(user: AuthUser): string {
  const first = user.firstName?.trim()?.[0] ?? "";
  const last = user.lastName?.trim()?.[0] ?? "";
  return (first + last).toUpperCase() || user.email[0]!.toUpperCase();
}

function displayName(user: AuthUser): string {
  const name = [user.firstName, user.lastName].filter(Boolean).join(" ");
  return name || user.email;
}

/**
 * The one navigation chrome every authenticated screen renders inside — it
 * replaced three near-identical, role-scoped shells. Which groups appear is
 * the union of what the user's roles unlock (everyone holds Learner, so that
 * group is always present); where they appear is the user's own
 * `navPosition` preference, set from the preferences page reachable through
 * the profile control below.
 */
export function AppShell({ user, onLogout }: Props) {
  const { t } = useTranslation();
  const navPosition = resolveNavPosition(user.navPosition);
  const isTop = navPosition === "top";
  const groups = getNavGroups(user.roles, t);

  const itemClassName = ({ isActive }: { isActive: boolean }) =>
    isTop
      ? `flex items-center gap-2 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium border-b-2 transition-colors ${
          isActive
            ? "border-primary text-fg"
            : "border-transparent text-fg-muted hover:text-fg"
        }`
      : `flex items-center gap-2.5 rounded-lg border-l-2 px-3 py-2 text-sm font-medium transition-colors ${
          isActive
            ? "border-primary bg-primary/10 text-primary"
            : "border-transparent text-fg-muted hover:bg-bg-subtle hover:text-fg"
        }`;

  const brand = (
    <div className="flex items-center gap-2 text-base font-semibold">
      <svg width="24" height="24" viewBox="0 0 28 28" aria-hidden="true" className="shrink-0">
        <rect x="2" y="2" width="24" height="24" rx="8" fill="url(#app-shell-logo)" />
        <path d="M9 14l4-6 4 6-4 6z" fill="var(--primary-fg)" opacity="0.92" />
        <defs>
          <linearGradient id="app-shell-logo" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--primary)" />
            <stop offset="1" stopColor="var(--accent)" />
          </linearGradient>
        </defs>
      </svg>
      {t("app.name")}
    </div>
  );

  const navGroups = groups.map((group) => (
    <div key={group.key} className={isTop ? "flex items-center gap-1" : "flex flex-col gap-1"}>
      {group.label && !isTop && (
        <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
          {group.label}
        </div>
      )}
      {group.items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end} className={itemClassName}>
          <item.icon className="shrink-0" />
          {item.label}
        </NavLink>
      ))}
    </div>
  ));

  const profileControl = (
    <NavLink
      to="/profile"
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-xl border px-2.5 py-2 text-left transition-colors ${
          isActive
            ? "border-primary/40 bg-primary/10"
            : "border-transparent hover:bg-bg-subtle"
        }`
      }
    >
      <span
        aria-hidden="true"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[image:var(--gradient)] text-xs font-bold text-primary-fg"
      >
        {initials(user)}
      </span>
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate text-xs font-semibold text-fg">{displayName(user)}</span>
        <span className="text-[11px] text-fg-muted">{t("profile.nav_link")}</span>
      </span>
    </NavLink>
  );

  const logoutButton = (
    <button
      type="button"
      onClick={onLogout}
      className="rounded-full border border-border bg-bg-elevated px-3 py-1.5 text-xs font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
    >
      {t("auth.logout")}
    </button>
  );

  if (isTop) {
    return (
      <div className="min-h-screen bg-bg text-fg flex flex-col">
        <header className="sticky top-0 z-10 flex flex-wrap items-center gap-4 border-b border-border bg-bg/80 px-4 py-3 backdrop-blur sm:px-6">
          {brand}
          <nav className="flex flex-1 flex-wrap items-center gap-4">{navGroups}</nav>
          <div className="flex items-center gap-3">
            {profileControl}
            {logoutButton}
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg text-fg flex">
      <aside className="flex w-60 shrink-0 flex-col gap-6 border-r border-border bg-bg-elevated p-4">
        {brand}
        <nav className="flex flex-1 flex-col gap-5 overflow-y-auto">{navGroups}</nav>
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          {profileControl}
          {logoutButton}
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto p-6 sm:p-8">
        <Outlet />
      </main>
    </div>
  );
}
