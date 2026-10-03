export type NavPosition = "left" | "top";

export const NAV_POSITIONS: readonly NavPosition[] = ["left", "top"];

/**
 * The nav placement to render for a user: their own stored preference if
 * they have one, otherwise a left sidebar. Unlike theme, there's no OS
 * signal to fall back to — "left" is just the default until they choose.
 */
export function resolveNavPosition(preferredNavPosition: string | null): NavPosition {
  return (preferredNavPosition as NavPosition | null) ?? "left";
}
