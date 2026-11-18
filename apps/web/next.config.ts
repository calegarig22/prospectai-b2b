import type { NextConfig } from "next";

// A API mora em outro projeto (apps/api, na Cloudflare). O navegador fala só com
// este domínio: /api/* é repassado para a API pelo servidor do Next. Assim o
// cookie de sessão é da MESMA origem (sem cookie de terceiros, sem CORS) e a URL
// real da API não aparece para o usuário.
const apiUrl = (process.env.API_URL || "").replace(/\/+$/, "");
if (!apiUrl && process.env.NODE_ENV === "production") {
  throw new Error("Defina API_URL (URL da API) nas variáveis de ambiente.");
}

const dev = process.env.NODE_ENV !== "production";
const csp = [
  "default-src 'self'",
  // O Next injeta scripts inline de hidratação; em dev também usa eval.
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  // https: por causa da prévia do template de e-mail (imagens hospedadas fora).
  "img-src 'self' data: https:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl || "http://localhost:8000"}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
        ],
      },
    ];
  },
};

export default nextConfig;
