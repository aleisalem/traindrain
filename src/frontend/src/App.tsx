import Dashboard from "./Dashboard";
import { ForcedPasswordChangeForm } from "./features/auth/ForcedPasswordChangeForm";
import { LoginForm } from "./features/auth/LoginForm";
import { useAuth } from "./features/auth/useAuth";

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

  return <Dashboard user={state.user} onLogout={() => void logout()} />;
}

export default App;
