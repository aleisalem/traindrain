import { useEffect } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AdminDisableTwoFactorPage } from "./features/admin/AdminDisableTwoFactorPage";
import { AdminGroupsPage } from "./features/admin/AdminGroupsPage";
import { AdminOverview } from "./features/admin/AdminOverview";
import { AdminRolesPage } from "./features/admin/AdminRolesPage";
import { AdminUsersPage } from "./features/admin/AdminUsersPage";
import { InviteUserPage } from "./features/admin/InviteUserPage";
import { ForcedPasswordChangeForm } from "./features/auth/ForcedPasswordChangeForm";
import { ForgotPasswordPage } from "./features/auth/ForgotPasswordPage";
import { LoginForm } from "./features/auth/LoginForm";
import { ResetPasswordPage } from "./features/auth/ResetPasswordPage";
import { TwoFactorVerifyForm } from "./features/auth/TwoFactorVerifyForm";
import type { AuthUser } from "./features/auth/useAuth";
import { ADMINISTRATOR_ROLE, canAuthorContent, useAuth } from "./features/auth/useAuth";
import { ContentModulesPage } from "./features/content/ContentModulesPage";
import { ModuleFormPage } from "./features/content/ModuleFormPage";
import { ModuleReportsPage } from "./features/content/ModuleReportsPage";
import { AcceptInvitePage } from "./features/invites/AcceptInvitePage";
import { CatalogPage } from "./features/learning/CatalogPage";
import { ModuleViewerPage } from "./features/learning/ModuleViewerPage";
import { MyLearningPage } from "./features/learning/MyLearningPage";
import { ProfilePage } from "./features/profile/ProfilePage";
import i18n from "./i18n";
import { AppShell } from "./shell/AppShell";
import { getLandingPath } from "./shell/navConfig";
import { resolveTheme, useAppliedTheme } from "./theme/useTheme";

type AuthenticatedRoutesProps = {
  user: AuthUser;
  onLogout: () => void;
  onRefreshUser: () => Promise<void>;
  onUpdateName: ReturnType<typeof useAuth>["updateName"];
  onUpdatePreferences: ReturnType<typeof useAuth>["updatePreferences"];
  onChangePassword: ReturnType<typeof useAuth>["changePassword"];
};

function AuthenticatedRoutes({
  user,
  onLogout,
  onRefreshUser,
  onUpdateName,
  onUpdatePreferences,
  onChangePassword,
}: AuthenticatedRoutesProps) {
  const isAdministrator = user.roles.includes(ADMINISTRATOR_ROLE);
  // `/content` sits alongside `/admin`, not inside it: authoring needs no
  // Release 0 administrator permission, and this gate does not widen `/admin`.
  const canAuthor = canAuthorContent(user.roles);

  // The user's server-persisted theme/language preferences (ticket 12) are
  // applied here, once, for the whole authenticated app — rather than by
  // whichever screen happens to be mounted — so they stick across
  // navigation. A user with no stored preference falls back to the OS
  // light/dark default; the language detector's own default stands until
  // the user has one.
  useAppliedTheme(resolveTheme(user.preferredTheme));

  useEffect(() => {
    if (user.preferredLanguage) void i18n.changeLanguage(user.preferredLanguage);
  }, [user.preferredLanguage]);

  return (
    <Routes>
      <Route element={<AppShell user={user} onLogout={onLogout} />}>
        <Route
          path="/profile"
          element={
            <ProfilePage
              user={user}
              onUpdateName={onUpdateName}
              onUpdatePreferences={onUpdatePreferences}
              onChangePassword={onChangePassword}
              onRefreshUser={onRefreshUser}
            />
          }
        />
        {/* Reading is not a privilege: every authenticated user has a learner
            area, whatever else they can also do. */}
        <Route path="/modules" element={<Outlet />}>
          <Route index element={<MyLearningPage />} />
          <Route path="browse" element={<CatalogPage />} />
          <Route path=":groupId" element={<ModuleViewerPage />} />
        </Route>
        {isAdministrator && (
          <Route path="/admin" element={<Outlet />}>
            <Route index element={<AdminOverview />} />
            <Route path="users" element={<AdminUsersPage currentUserId={user.id} />} />
            <Route path="roles" element={<AdminRolesPage />} />
            <Route path="groups" element={<AdminGroupsPage />} />
            <Route path="invites" element={<InviteUserPage />} />
            <Route path="two-factor" element={<AdminDisableTwoFactorPage />} />
          </Route>
        )}
        {canAuthor && (
          <Route path="/content" element={<Outlet />}>
            <Route index element={<ContentModulesPage />} />
            <Route path="new" element={<ModuleFormPage isAdministrator={isAdministrator} />} />
            <Route
              path="reports"
              element={<ModuleReportsPage isAdministrator={isAdministrator} />}
            />
            <Route
              path=":moduleId"
              element={<ModuleFormPage isAdministrator={isAdministrator} />}
            />
          </Route>
        )}
      </Route>
      {/* Every user's homepage depends on their role — the highest-privilege
          area they hold, not a shared placeholder. */}
      <Route path="/" element={<Navigate to={getLandingPath(user.roles)} replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  const {
    state,
    login,
    logout,
    changePassword,
    verifyTwoFactor,
    refresh,
    updateName,
    updatePreferences,
  } = useAuth();

  // An invite or password-reset link is followed by a signed-out visitor —
  // reachable regardless of session state, unlike every other route in the app.
  if (window.location.pathname === "/accept-invite") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <AcceptInvitePage />
      </main>
    );
  }

  if (window.location.pathname === "/forgot-password") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <ForgotPasswordPage />
      </main>
    );
  }

  if (window.location.pathname === "/reset-password") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <ResetPasswordPage />
      </main>
    );
  }

  if (state.status === "loading") {
    return <main className="min-h-screen bg-bg" />;
  }

  if (state.status === "anonymous") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <LoginForm onLogin={login} />
      </main>
    );
  }

  if (state.status === "two_factor_required") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <TwoFactorVerifyForm onVerify={verifyTwoFactor} />
      </main>
    );
  }

  if (state.status === "forced_password_change") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <ForcedPasswordChangeForm onChangePassword={changePassword} />
      </main>
    );
  }

  return (
    <BrowserRouter>
      <AuthenticatedRoutes
        user={state.user}
        onLogout={() => void logout()}
        onRefreshUser={refresh}
        onUpdateName={updateName}
        onUpdatePreferences={updatePreferences}
        onChangePassword={changePassword}
      />
    </BrowserRouter>
  );
}

export default App;
