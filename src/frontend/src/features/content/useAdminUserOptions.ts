import { useEffect, useState } from "react";

export type UserOption = { id: string; label: string };

type AdminUser = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  disabled_at: string | null;
  erased_at: string | null;
};

/**
 * Active users an Administrator may name. Does nothing unless `enabled`, so a
 * Content Manager's screen never reaches for the staff directory.
 */
export function useAdminUserOptions(enabled: boolean): UserOption[] {
  const [options, setOptions] = useState<UserOption[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/admin/users");
        if (!response.ok || cancelled) return;
        const users: AdminUser[] = await response.json();
        setOptions(
          users
            .filter((user) => user.disabled_at === null && user.erased_at === null)
            .map((user) => ({
              id: user.id,
              label: [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email,
            })),
        );
      } catch {
        // The picker simply stays empty.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return options;
}
