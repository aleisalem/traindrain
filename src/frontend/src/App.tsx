import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import Dashboard from "./Dashboard";
import { AdminDisableTwoFactorPage } from "./features/admin/AdminDisableTwoFactorPage";
import { AdminOverview } from "./features/admin/AdminOverview";
import { AdminShell } from "./features/admin/AdminShell";
import { InviteUserPage } from "./features/admin/InviteUserPage";
import { ForcedPasswordChangeForm } from "./features/auth/ForcedPasswordChangeForm";
import { ForgotPasswordPage } from "./features/auth/ForgotPasswordPage";
import { LoginForm } from "./features/auth/LoginForm";
import { ResetPasswordPage } from "./features/auth/ResetPasswordPage";
import { TwoFactorVerifyForm } from "./features/auth/TwoFactorVerifyForm";
import type { AuthUser } from "./features/auth/useAuth";
import { ADMINISTRATOR_ROLE, useAuth } from "./features/auth/useAuth";
import { AcceptInvitePage } from "./features/invites/AcceptInvitePage";

function AuthenticatedRoutes({
  user,
  onLogout,
  onRefreshUser,
}: {
  user: AuthUser;
  onLogout: () => void;
  onRefreshUser: () => Promise<void>;
}) {
  const isAdministrator = user.roles.includes(ADMINISTRATOR_ROLE);

  return (
    <Routes>
      <Route
        path="/"
        element={<Dashboard user={user} onLogout={onLogout} onRefreshUser={onRefreshUser} />}
      />
      {isAdministrator && (
        <Route path="/admin" element={<AdminShell onLogout={onLogout} />}>
          <Route index element={<AdminOverview />} />
          <Route path="invites" element={<InviteUserPage />} />
          <Route path="two-factor" element={<AdminDisableTwoFactorPage />} />
        </Route>
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  const { state, login, logout, changePassword, verifyTwoFactor, refresh } = useAuth();

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
      />
    </BrowserRouter>
  );
}

export default App;
