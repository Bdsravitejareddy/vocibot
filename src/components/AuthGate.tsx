"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getAuthStatus, signOut, type User } from "@/lib/auth/api";

const SessionContext = createContext<{ user: User; signOut: () => Promise<void> } | null>(null);

/** The signed-in user; only valid inside an AuthGate. */
export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside AuthGate");
  return value;
}

/** Renders children only for a signed-in user; otherwise routes to setup or sign-in. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    getAuthStatus().then((status) => {
      if (cancelled) return;
      if (status.setup_required) return router.replace("/setup");
      if (!status.user) return router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      if (status.user.must_change_password && pathname !== "/account") return router.replace("/account?required=1");
      setUser(status.user);
    }).catch(() => { if (!cancelled) setError("The VociBot server is not reachable."); });
    return () => { cancelled = true; };
  }, [pathname, router]);
  if (error) return <div className="auth-page"><div className="auth-card"><div className="warning-banner">{error}</div></div></div>;
  if (!user) return <div className="auth-page"><div className="loading-state">Checking your session…</div></div>;
  return <SessionContext.Provider value={{ user, signOut: async () => { await signOut().catch(() => undefined); router.replace("/login"); } }}>{children}</SessionContext.Provider>;
}
