// Worker que publica a API do ProspectAI rodando num Container (Python/FastAPI).
//
// Por que Container: o motor de busca é Python (busca web, leitura de sites,
// Receita) e um lote leva minutos — não cabe no runtime dos Workers.
//
// Uma instância só (max_instances = 1): a fila de lotes e o limite de
// tentativas de login vivem na memória do processo.
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  API: DurableObjectNamespace<ApiContainer>;
  // Segredos: cadastrados com `wrangler secret put NOME`, nunca no código.
  DATABASE_URL: string;
  JWT_SECRET: string;
  APP_PASSWORD: string;
  EMAIL_ENC_KEY: string;
  SMTP_FROM?: string;
  SMTP_PASSWORD?: string;
  SMTP_HOST?: string;
  SMTP_PORT?: string;
}

export class ApiContainer extends Container<Env> {
  defaultPort = 8000;
  // Sem requisição por 15 min, a Cloudflare pergunta se pode desligar (abaixo).
  sleepAfter = "15m";
  pingEndpoint = "localhost/health";

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    // Repassa ao container só o que a API usa.
    this.envVars = {
      APP_ENV: "production",
      DATABASE_URL: env.DATABASE_URL,
      JWT_SECRET: env.JWT_SECRET,
      APP_PASSWORD: env.APP_PASSWORD,
      EMAIL_ENC_KEY: env.EMAIL_ENC_KEY,
      SMTP_FROM: env.SMTP_FROM ?? "",
      SMTP_PASSWORD: env.SMTP_PASSWORD ?? "",
      SMTP_HOST: env.SMTP_HOST ?? "smtp.gmail.com",
      SMTP_PORT: env.SMTP_PORT ?? "587",
    };
  }

  // Desligar por inatividade no meio de um lote mataria o job. Antes de parar,
  // pergunta à API se há lote/disparo rodando; se houver, mantém ligado (o
  // contador de inatividade recomeça e a pergunta se repete).
  override async onActivityExpired(): Promise<void> {
    try {
      const r = await this.containerFetch("http://localhost/health");
      const saude = (await r.json()) as { ocupado?: boolean };
      if (saude.ocupado) return;
    } catch {
      // API não respondeu: pode desligar
    }
    await this.stop();
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return getContainer(env.API).fetch(request);
  },
} satisfies ExportedHandler<Env>;
