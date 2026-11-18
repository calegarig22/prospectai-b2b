// Cliente da API. Tudo passa por /api (proxy do Next → apps/api).
// Os tipos vêm de api-types.ts, gerado do /openapi.json da API (npm run gen:api).

import type { components } from "./api-types";

export type S = components["schemas"];
export type Me = S["MeOut"];
export type Lote = S["LoteOut"];
export type LoteDetail = S["LoteDetail"];
export type Job = S["JobOut"];
export type Selection = S["SelectionOut"];
export type Meta = S["MetaOut"];
export type AdminUser = S["AdminUser"];
export type LeadRow = Record<string, string | number>;
export type Tenant = S["TenantOut"];
export type Marca = S["Marca"];
export type Plan = S["PlanOut"];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

function detail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    // Erro de validação do FastAPI: lista de problemas por campo.
    if (Array.isArray(d) && d.length) return "Confira os campos: alguns valores não são válidos.";
  }
  if (status >= 500) return "O servidor não respondeu como esperado. Tente novamente em instantes.";
  return "Não foi possível concluir agora.";
}

export async function api<T>(path: string, method: Method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      // Proteção CSRF: a API recusa escrita sem este cabeçalho.
      "X-Requested-With": "prospectai",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    // 401 no login é "senha errada"; em qualquer outra rota é sessão vencida.
    if (res.status === 401 && typeof window !== "undefined" && path !== "/auth/login") {
      // Fora de componente não há router: recarrega na página de login.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login?expirou=1";
    }
    throw new ApiError(res.status, detail(data, res.status));
  }
  return data as T;
}

export function errMsg(e: unknown): string {
  return e instanceof ApiError ? e.message : "Sem conexão com o servidor. Tente novamente.";
}
