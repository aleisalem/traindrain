import type { ComponentType } from "react";
import type { TFunction } from "i18next";

import { ADMINISTRATOR_ROLE, canAuthorContent } from "../features/auth/useAuth";
import {
  BookIcon,
  ChartIcon,
  CompassIcon,
  GroupsIcon,
  LayersIcon,
  LockIcon,
  MailIcon,
  ShieldIcon,
  UsersIcon,
} from "./icons";

export type NavItem = {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  end?: boolean;
};

export type NavGroup = {
  key: string;
  label: string | null;
  items: NavItem[];
};

/**
 * Every authenticated user holds the Learner role (invite acceptance
 * auto-assigns it), so the learning group is always present — the nav shows
 * the union of what a user's roles unlock, not just their "primary" one. An
 * Administrator who never touches content still sees the Content group,
 * because require_content_manager admits Administrators too.
 */
export function getNavGroups(roles: string[], t: TFunction): NavGroup[] {
  const groups: NavGroup[] = [
    {
      key: "learning",
      label: t("shell.group_learning"),
      items: [
        { to: "/modules", label: t("learning.nav_my_learning"), icon: BookIcon, end: true },
        { to: "/modules/browse", label: t("learning.nav_catalog"), icon: CompassIcon },
      ],
    },
  ];

  if (canAuthorContent(roles)) {
    groups.push({
      key: "content",
      label: t("content.nav_link"),
      items: [
        { to: "/content", label: t("content.nav_modules"), icon: LayersIcon, end: true },
        { to: "/content/reports", label: t("contentReports.nav_link"), icon: ChartIcon },
      ],
    });
  }

  if (roles.includes(ADMINISTRATOR_ROLE)) {
    groups.push({
      key: "admin",
      label: t("admin.nav_link"),
      items: [
        { to: "/admin", label: t("admin.nav_overview"), icon: ShieldIcon, end: true },
        { to: "/admin/invites", label: t("invites.nav_link"), icon: MailIcon },
        { to: "/admin/users", label: t("adminUsers.nav_link"), icon: UsersIcon },
        { to: "/admin/roles", label: t("adminRoles.nav_link"), icon: ShieldIcon },
        { to: "/admin/groups", label: t("adminGroups.nav_link"), icon: GroupsIcon },
        { to: "/admin/two-factor", label: t("adminTwoFactor.nav_link"), icon: LockIcon },
      ],
    });
  }

  return groups;
}

/** Where a user lands after signing in — the highest-privilege area they hold. */
export function getLandingPath(roles: string[]): string {
  if (roles.includes(ADMINISTRATOR_ROLE)) return "/admin";
  if (canAuthorContent(roles)) return "/content";
  return "/modules";
}
