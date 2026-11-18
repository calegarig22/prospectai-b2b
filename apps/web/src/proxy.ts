import { NextResponse, type NextRequest } from "next/server";

// Checagem OTIMISTA: sem o cookie de sessão, nem renderiza o painel — vai direto
// para o login. Quem valida a sessão de verdade é a API, a cada requisição.
const PUBLIC = ["/login"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const logado = request.cookies.has("tp_session");
  if (!logado && !PUBLIC.includes(pathname)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Fora: a API (proxy), arquivos do Next e estáticos.
  matcher: ["/((?!api/|_next/|favicon.ico|.*\\.(?:png|svg|ico|webp|jpg)$).*)"],
};
