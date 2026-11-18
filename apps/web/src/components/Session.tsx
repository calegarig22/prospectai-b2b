"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Me, type Plan } from "@/lib/api";

type SessionCtx = { me: Me; reload: () => Promise<void> };
const Ctx = createContext<SessionCtx | null>(null);

export function SessionProvider({ children }: { children: (me: Me | null) => React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const reload = useCallback(async () => {
    setMe(await api<Me>("/auth/me"));       // 401 → api() já manda para o login
  }, []);
  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch(() => undefined);
  }, []);
  return <Ctx.Provider value={me ? { me, reload } : null}>{children(me)}</Ctx.Provider>;
}

export function useSession(): SessionCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession fora do SessionProvider");
  return v;
}

// Telas das EMPRESAS (gerar leads, e-mail, admin). O dono da plataforma não tem
// plano nem leads: é levado para a área dele.
export function useMembro(): { me: Me & { plan: Plan }; reload: () => Promise<void> } | null {
  const { me, reload } = useSession();
  const router = useRouter();
  const dono = me.user.role === "superadmin" || !me.plan;
  useEffect(() => {
    if (dono) router.replace("/plataforma");
  }, [dono, router]);
  return dono ? null : { me: me as Me & { plan: Plan }, reload };
}
