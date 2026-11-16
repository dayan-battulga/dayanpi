import { useEffect, useState } from "react";
import { request } from "@/lib/http";
import type { User } from "@/lib/types";

// With no answer (the Pi restarting, the VPN still connecting) it asks again this often; until then the owner
// sees the read-only page with no account menu.
export const ME_RETRY_MS = 5000;

export interface SignedIn {
  user: User | null; // null until /api/me answers
  setUser: (user: User) => void;
}

// Who's signed in. Without a session /api/me is a 401, and the request helper goes to /login.
export function useMe(): SignedIn {
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    let current = true;
    let timer: number | undefined;
    const ask = async () => {
      const reply = await request<{ user: User }>("GET", "/api/me");
      if (current && reply.body?.user != null) {
        setUser(reply.body.user);
      } else if (current && reply.status !== 401) {
        timer = window.setTimeout(ask, ME_RETRY_MS);
      }
    };
    void ask();
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, []);
  return { user, setUser };
}
