import { useCallback, useEffect, useState } from "react";

type ListState<T> =
  | { status: "loading" }
  | { status: "ready"; items: T[] }
  | { status: "error" };

/**
 * One list of the learner's own material, fetched once.
 *
 * The catalog and "my learning" ask different questions of the server but have
 * the same three states to be in, and duplicating that in both screens would
 * mean two places to get the error case wrong.
 */
export function useLearnerList<T>(path: string): ListState<T> {
  const [state, setState] = useState<ListState<T>>({ status: "loading" });

  const load = useCallback(async () => {
    try {
      const response = await fetch(path);
      if (!response.ok) {
        setState({ status: "error" });
        return;
      }
      setState({ status: "ready", items: await response.json() });
    } catch {
      setState({ status: "error" });
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  return state;
}
