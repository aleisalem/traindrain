import { useEffect, useState } from "react";

export type ModuleEditor = {
  id: string;
  display_name: string;
};

/** How often the open editor tells the server it is still here. */
const HEARTBEAT_MS = 15_000;

/**
 * Who else currently has this module open.
 *
 * A heartbeat rather than a socket: it needs no new infrastructure, works
 * behind a load balancer without sticky routing, and the question ("who is in
 * here with me?") tolerates being a few seconds out of date. The server's
 * presence window is generous next to this interval, so one slow request does
 * not make a colleague flicker out of the list.
 */
export function useModuleEditors(moduleId: string | undefined): ModuleEditor[] {
  const [editors, setEditors] = useState<ModuleEditor[]>([]);

  useEffect(() => {
    if (!moduleId) return;
    let stopped = false;

    async function ping() {
      try {
        const response = await fetch(`/api/content/modules/${moduleId}/editing`, {
          method: "POST",
        });
        if (stopped || !response.ok) return;
        const body: { editors: ModuleEditor[] } = await response.json();
        setEditors(body.editors);
      } catch {
        // A dropped heartbeat is not worth surfacing — the next one is 15
        // seconds away, and the presence list is an aid, not a control.
      }
    }

    void ping();
    const timer = setInterval(() => void ping(), HEARTBEAT_MS);

    return () => {
      stopped = true;
      clearInterval(timer);
      // Leave explicitly so colleagues see the seat free immediately rather
      // than waiting out the presence window. `keepalive` lets it survive the
      // page being navigated away from or closed.
      void fetch(`/api/content/modules/${moduleId}/editing`, {
        method: "DELETE",
        keepalive: true,
      }).catch(() => undefined);
    };
  }, [moduleId]);

  return editors;
}
