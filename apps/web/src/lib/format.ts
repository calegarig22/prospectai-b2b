// Formatação para a tela — mesmas regras do painel antigo.

export function fmtStamp(stamp: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})/.exec(stamp || "");
  return m ? `${m[3]}/${m[2]}/${m[1]} · ${m[4]}:${m[5]}` : stamp;
}

export function fmtDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

export function fmtDateTime(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : iso;
}

export function fmtDuration(seconds: number): string {
  const s = Math.round(seconds || 0);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}min ${String(s % 60).padStart(2, "0")}s`;
}

export function isIlimitado(valor: number, ilimitado: number): boolean {
  return valor >= ilimitado;
}

export function fmtNum(valor: number, ilimitado?: number): string {
  if (ilimitado !== undefined && valor >= ilimitado) return "ilimitado";
  return valor.toLocaleString("pt-BR");
}

export function sols(value: unknown): string[] {
  return String(value ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// Nomes curtos só para a TELA (vêm do nicho da empresa) — a lista inteira
// continua na planilha e no e-mail.
export function solsCurto(value: unknown, curtos: Record<string, string>, teto = 3): string {
  const itens = sols(value).map((s) => curtos[s] ?? s);
  if (itens.length <= teto) return itens.join(" · ");
  return `${itens.slice(0, teto).join(" · ")}  +${itens.length - teto}`;
}

export function initials(name: string): string {
  const parts = name.replace(/[.@]/g, " ").split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map((p) => p[0]).join("") || name.slice(0, 2)).toUpperCase();
}

// Senha forte e aleatória (cripto-segura), sem caracteres ambíguos (l/1/I, o/0/O).
export function gerarSenha(tamanho = 14): string {
  const alf = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789@#%&*?";
  const buf = new Uint32Array(tamanho);
  crypto.getRandomValues(buf);
  return Array.from(buf, (n) => alf[n % alf.length]).join("");
}
