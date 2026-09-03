import { useCallback, useEffect, useState } from "react";

export const ADMINISTRATOR_ROLE = "Administrator";

export type AuthUser = {
  id: string;
  email: string;
  firstName: string | null;
  lastName: string | null;
  mustChangePassword: boolean;
  roles: string[];
  twoFactorEnabled: boolean;
};

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "two_factor_required" }
  | { status: "forced_password_change" }
  | { status: "authenticated"; user: AuthUser };

type LoginError = "invalid_credentials" | "rate_limited" | "unknown";
type ChangePasswordError = "wrong_current_password" | "policy_violation" | "unknown";
type TwoFactorVerifyError = "invalid_code" | "rate_limited" | "unknown";

type ActionResult<E extends string> = { ok: true } | { ok: false; error: E };

type MeResponseBody = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  must_change_password: boolean;
  roles: string[];
  two_factor_enabled: boolean;
};

type LoginResponseBody = {
  must_change_password: boolean;
  two_factor_required: boolean;
};

function toAuthUser(body: MeResponseBody): AuthUser {
  return {
    id: body.id,
    email: body.email,
    firstName: body.first_name,
    lastName: body.last_name,
    mustChangePassword: body.must_change_password,
    roles: body.roles,
    twoFactorEnabled: body.two_factor_enabled,
  };
}

async function fetchAuthState(): Promise<AuthState> {
  // /api/auth/me is gated the same as every other endpoint: a session with
  // must_change_password set gets a 403 here too, which is how the app
  // learns to show the forced-change screen rather than a normal 200.
  const response = await fetch("/api/auth/me");
  if (response.status === 401) return { status: "anonymous" };
  if (response.status === 403) return { status: "forced_password_change" };
  if (!response.ok) throw new Error("Failed to load the current session.");

  const user = toAuthUser((await response.json()) as MeResponseBody);
  return { status: "authenticated", user };
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const refresh = useCallback(async () => {
    setState(await fetchAuthState());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string): Promise<ActionResult<LoginError>> => {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (response.status === 401) return { ok: false, error: "invalid_credentials" };
      if (response.status === 429) return { ok: false, error: "rate_limited" };
      if (!response.ok) return { ok: false, error: "unknown" };

      const body = (await response.json()) as LoginResponseBody;
      if (body.two_factor_required) {
        setState({ status: "two_factor_required" });
        return { ok: true };
      }

      await refresh();
      return { ok: true };
    },
    [refresh],
  );

  const verifyTwoFactor = useCallback(
    async (code: string): Promise<ActionResult<TwoFactorVerifyError>> => {
      const response = await fetch("/api/auth/2fa/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (response.status === 401) return { ok: false, error: "invalid_code" };
      if (response.status === 429) return { ok: false, error: "rate_limited" };
      if (!response.ok) return { ok: false, error: "unknown" };

      await refresh();
      return { ok: true };
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setState({ status: "anonymous" });
  }, []);

  const changePassword = useCallback(
    async (
      currentPassword: string,
      newPassword: string,
    ): Promise<ActionResult<ChangePasswordError>> => {
      const response = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (response.status === 401) return { ok: false, error: "wrong_current_password" };
      if (response.status === 422) return { ok: false, error: "policy_violation" };
      if (!response.ok) return { ok: false, error: "unknown" };

      await refresh();
      return { ok: true };
    },
    [refresh],
  );

  return { state, login, logout, changePassword, verifyTwoFactor, refresh };
}
