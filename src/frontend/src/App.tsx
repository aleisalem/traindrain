import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import Dashboard from "./Dashboard";
import { AdminOverview } from "./features/admin/AdminOverview";
import { AdminShell } from "./features/admin/AdminShell";
import { ForcedPasswordChangeForm } from "./features/auth/ForcedPasswordChangeForm";
import { LoginForm } from "./features/auth/LoginForm";
import type { AuthUser } from "./features/auth/useAuth";
import { ADMINISTRATOR_ROLE, useAuth } from "./features/auth/useAuth";

function AuthenticatedRoutes({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const isAdministrator = user.roles.includes(ADMINISTRATOR_ROLE);

  return (
    <Routes>
      <Route path="/" element={<Dashboard user={user} onLogout={onLogout} />} />
      {isAdministrator && (
        <Route path="/admin" element={<AdminShell onLogout={onLogout} />}>
          <Route index element={<AdminOverview />} />
        </Route>
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  const { state, login, logout, changePassword } = useAuth();

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

  if (state.status === "forced_password_change") {
    return (
      <main className="min-h-screen bg-bg text-fg flex items-center justify-center p-8">
        <ForcedPasswordChangeForm onChangePassword={changePassword} />
      </main>
    );
  }

  return (
    <BrowserRouter>
      <AuthenticatedRoutes user={state.user} onLogout={() => void logout()} />
    </BrowserRouter>
  );
}

export default App;
