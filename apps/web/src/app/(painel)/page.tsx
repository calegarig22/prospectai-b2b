"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errMsg, type Job, type LeadRow, type Lote, type LoteDetail, type Meta, type Plan } from "@/lib/api";
import { fmtDuration, fmtNum, fmtStamp, sols, solsCurto } from "@/lib/format";
import { Note } from "@/components/Modal";
import { useMembro } from "@/components/Session";
import { useJob } from "@/components/useJob";

type LotesResp = { lotes: Lote[]; ocultos_por_plano: number; historico_dias: number };

export default function GerarLeadsPage() {
  const membro = useMembro();
  if (!membro) return null;
  return <GerarLeads reload={membro.reload} />;
}

function GerarLeads({ reload }: { reload: () => Promise<void> }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [lotes, setLotes] = useState<LotesResp | null>(null);
  const [sel, setSel] = useState("");
  const [resultado, setResultado] = useState<{ kind: "ok" | "warn" | "err"; text: string; log?: string[] } | null>(null);

  const carregarLotes = useCallback(async (escolher?: string) => {
    const r = await api<LotesResp>("/lotes");
    setLotes(r);
    setSel((atual) => escolher || (r.lotes.some((l) => l.id === atual) ? atual : r.lotes[0]?.id || ""));
  }, []);

  useEffect(() => {
    api<Meta>("/meta").then(setMeta).catch(() => undefined);
    api<LotesResp>("/lotes")
      .then((r) => { setLotes(r); setSel(r.lotes[0]?.id || ""); })
      .catch(() => undefined);
  }, []);

  const { job, running, start } = useJob("discover", (j: Job) => {
    const r = (j.result || {}) as { lote?: string; segundos?: number; aviso?: string; log?: string[] };
    if (j.status === "done") {
      setResultado({ kind: "ok", text: `Lote concluído em ${fmtDuration(r.segundos || 0)}.` });
      if (r.aviso) setResultado({ kind: "warn", text: r.aviso });
      carregarLotes(r.lote).catch(() => undefined);
      reload().catch(() => undefined);
    } else {
      setResultado({ kind: "err", text: j.error || "Não foi possível concluir agora.", log: r.log });
    }
  });

  return (
    <>
      <div className="sec">1 · Gerar a lista de leads</div>
      <div className="grid-2">
        <Gerar meta={meta} running={running} job={job} onStart={(j) => { setResultado(null); start(j); }} />
        <div className="card info">
          <div className="h">Como funciona</div>
          <div className="step"><b>Descobre</b><p>Busca na web as empresas do seu nicho{meta?.nicho_nome ? ` (${meta.nicho_nome})` : ""}, sempre novas para a sua empresa.</p></div>
          <div className="step"><b>Identifica a necessidade</b><p>Lê o site e aponta quais das suas soluções cabem ali{meta?.solucoes.length ? `: ${meta.solucoes.map((x) => x.curto).join(", ")}` : ""}.</p></div>
          <div className="step" style={{ marginBottom: 0 }}><b>Acha o decisor</b><p>Cargo decisor, e-mail, telefone e LinkedIn da empresa — só dado público, nada inventado.</p></div>
        </div>
      </div>
      {resultado && (
        <div style={{ marginTop: 14 }}>
          <Note kind={resultado.kind}>
            {resultado.text}
            {resultado.log && resultado.log.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary>Ver detalhes técnicos</summary>
                <pre className="log">{resultado.log.join("\n")}</pre>
              </details>
            )}
          </Note>
        </div>
      )}

      <div className="sec">2 · Seus leads — por lote (cada clique = um lote)</div>
      {!lotes ? (
        <p className="caption">Carregando lotes…</p>
      ) : lotes.lotes.length === 0 ? (
        <Note>Nenhum lote ainda. Clique em <b>Gerar agora</b> acima para criar o primeiro.</Note>
      ) : (
        <>
          <label className="field" style={{ maxWidth: 560 }}>
            Escolha o lote para ver
            <select className="input" value={sel} onChange={(e) => setSel(e.target.value)}>
              {lotes.lotes.map((l) => (
                <option key={l.id} value={l.id}>
                  {fmtStamp(l.id)} · {l.count} empresas{l.region ? ` · ${l.region === meta?.world ? "Brasil" : l.region}` : ""}
                  {l.device ? ` · ${l.device}` : ""}
                </option>
              ))}
            </select>
          </label>
          {lotes.ocultos_por_plano > 0 && (
            <p className="caption lock">
              {lotes.ocultos_por_plano} lote(s) com mais de {lotes.historico_dias} dias não aparecem neste plano.
              Os dados continuam guardados — mudar de plano os traz de volta.
            </p>
          )}
          {sel && <LoteView key={sel} loteId={sel} world={meta?.world || ""}
            curtos={Object.fromEntries((meta?.solucoes || []).map((x) => [x.nome, x.curto]))} />}
        </>
      )}
    </>
  );
}

function Gerar({ meta, running, job, onStart }: { meta: Meta | null; running: boolean; job: Job | null; onStart: (j: Job) => void }) {
  const membro = useMembro();
  if (!membro) return null;
  const pl = membro.me.plan;
  return <GerarForm pl={pl} meta={meta} running={running} job={job} onStart={onStart} />;
}

function GerarForm({ pl, meta, running, job, onStart }: { pl: Plan; meta: Meta | null; running: boolean; job: Job | null; onStart: (j: Job) => void }) {
  const teto = pl.limites.leads_clique;
  const [qtd, setQtd] = useState(Math.min(40, teto));
  const [regiao, setRegiao] = useState("");
  const [soContato, setSoContato] = useState(true);
  const [erro, setErro] = useState("");
  const [busy, setBusy] = useState(false);

  const cota = pl.limites.leads_mes;
  const ilim = cota >= pl.ilimitado;
  const resta = Math.max(0, cota - pl.uso_leads_mes);
  const semCota = !ilim && resta < qtd;
  const podeRegiao = pl.recursos.filtro_regiao;
  const regLabel = regiao && regiao !== meta?.world ? ` · ${regiao}` : "";

  async function gerar() {
    setErro("");
    setBusy(true);
    try {
      const j = await api<Job>("/jobs/discover", "POST", {
        quantidade: qtd,
        regiao: regiao && regiao !== meta?.world ? regiao : null,
        so_com_contato: soContato,
      });
      onStart(j);
    } catch (e) {
      setErro(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="row">
        <label className="field" style={{ flex: 3 }}>
          Quantos leads trazer por clique? <b style={{ color: "var(--ink)" }}>{qtd}</b>
          <input type="range" min={10} max={teto} step={5} value={qtd} onChange={(e) => setQtd(Number(e.target.value))} disabled={running} />
          <span className="caption">O plano {pl.nome} traz até {teto} por clique. A memória garante empresas NOVAS a cada vez.</span>
        </label>
        <label className="field" style={{ flex: 2 }}>
          Região
          <select className="input" value={regiao} onChange={(e) => setRegiao(e.target.value)} disabled={!podeRegiao || running}>
            {(meta?.regions || []).map((r) => <option key={r} value={r === meta?.world ? "" : r}>{r}</option>)}
          </select>
          {!podeRegiao && <span className="caption lock">Disponível no plano Profissional</span>}
        </label>
      </div>
      <div className="card">
        <p className="card-title">Gerar novos leads</p>
        <p className="card-desc">Busca empresas NOVAS do seu nicho na web (e na base curada, se houver). Identifica a necessidade de cada uma, acha o decisor e valida os contatos.</p>
        <div className="stack">
          <label className="check" title="Ligado: só entram empresas com pelo menos UM canal — e-mail, telefone ou LinkedIn.">
            <input type="checkbox" checked={soContato} onChange={(e) => setSoContato(e.target.checked)} disabled={running} />
            Só empresas com contato
          </label>
          {!ilim && (
            <p className="caption" style={{ margin: 0 }}>
              Cota do mês: <b>{fmtNum(pl.uso_leads_mes)}</b> de {fmtNum(cota)} leads · restam {fmtNum(resta)}
            </p>
          )}
          {semCota && <Note kind="warn">Faltam {fmtNum(resta)} leads na cota deste mês e você pediu {qtd}. Reduza a quantidade ou mude de plano.</Note>}
          {erro && <Note kind="err">{erro}</Note>}
          <button className="btn primary block" onClick={gerar} disabled={busy || running || semCota}>
            {running ? <><span className="spinner" /> Gerando…</> : `Gerar agora · ${qtd} empresas${regLabel}`}
          </button>
          {running && job && (
            <Note>
              <b>{job.status === "queued" ? "Na fila — outro lote está terminando." : "Buscando e analisando empresas…"}</b>
              <br />
              <span className="caption">{job.progress} · Isso leva alguns minutos. Pode navegar; o progresso continua.</span>
            </Note>
          )}
        </div>
      </div>
    </div>
  );
}

const REQ: Record<string, string> = { "Soluções": "Soluções", "E-mail": "Email", Telefone: "Phone", LinkedIn: "LinkedIn", Cidade: "City" };
const LABELS: Record<string, string> = {
  Company: "Empresa", Porte: "Porte", "Soluções": "Soluções", Situação: "Situação", Desde: "Desde",
  City: "Cidade", Phone: "Telefone", Email: "E-mail", TipoEmail: "Quem lê", Score: "Score",
  Classification: "Classe", Website: "Site", LinkedIn: "LinkedIn",
};

const preenchido = (v: unknown) => String(v ?? "").trim() !== "";

// Lead que vale manter mesmo SEM telefone: site, e-mail, necessidade e score >= 75.
const altaQualidade = (r: LeadRow) =>
  preenchido(r.Website) && preenchido(r.Email) && preenchido(r["Soluções"]) && Number(r.Score || 0) >= 75;

function LoteView({ loteId, world, curtos }: { loteId: string; world: string; curtos: Record<string, string> }) {
  const [det, setDet] = useState<LoteDetail | null>(null);
  const [erro, setErro] = useState("");
  const [filtroSol, setFiltroSol] = useState<string[]>([]);
  const [busca, setBusca] = useState("");
  const [exige, setExige] = useState<string[]>([]);
  const [ordem, setOrdem] = useState<{ col: string; asc: boolean }>({ col: "Score", asc: false });

  useEffect(() => {
    api<LoteDetail>(`/lotes/${encodeURIComponent(loteId)}`).then(setDet).catch((e) => setErro(errMsg(e)));
  }, [loteId]);

  const rows = useMemo(() => (det?.rows || []) as LeadRow[], [det]);
  const contagem = useMemo(() => {
    const c = new Map<string, number>();
    rows.forEach((r) => sols(r["Soluções"]).forEach((s) => c.set(s, (c.get(s) || 0) + 1)));
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [rows]);

  const { view, mantidos } = useMemo(() => {
    let v = rows;
    if (filtroSol.length) v = v.filter((r) => sols(r["Soluções"]).some((s) => filtroSol.includes(s)));
    if (busca.trim()) v = v.filter((r) => String(r.Company || "").toLowerCase().includes(busca.trim().toLowerCase()));
    let mantidos = 0;
    for (const rot of exige) {
      const col = REQ[rot];
      if (rot === "Telefone") {
        mantidos = v.filter((r) => !preenchido(r.Phone) && altaQualidade(r)).length;
        v = v.filter((r) => preenchido(r.Phone) || altaQualidade(r));
      } else {
        v = v.filter((r) => preenchido(r[col]));
      }
    }
    const { col, asc } = ordem;
    v = [...v].sort((a, b) => {
      const x = a[col] ?? "", y = b[col] ?? "";
      const cmp = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "pt-BR");
      return asc ? cmp : -cmp;
    });
    return { view: v, mantidos };
  }, [rows, filtroSol, busca, exige, ordem]);

  if (erro) return <Note kind="err">{erro}</Note>;
  if (!det) return <p className="caption">Carregando lote…</p>;

  const lote = det.lote;
  const n = rows.length;
  const conta = (col: string) => rows.filter((r) => preenchido(r[col])).length;
  const porClasse = (c: string) => rows.filter((r) => r.Classification === c).length;
  const [hot, warm, cold] = [porClasse("HOT"), porClasse("WARM"), porClasse("COLD")];
  const total = Math.max(hot + warm + cold, 1);
  const cols = det.columns;
  const regiao = lote.region === world ? "Brasil" : lote.region;
  const toggle = (lista: string[], v: string) => (lista.includes(v) ? lista.filter((x) => x !== v) : [...lista, v]);

  return (
    <div className="stack" style={{ marginTop: 14 }}>
      {lote.gen_seconds > 0 && (
        <Note kind="ok">
          Este lote foi gerado em <b>{fmtDuration(lote.gen_seconds)}</b> ({n} empresas · ~{(lote.gen_seconds / Math.max(n, 1)).toFixed(1)}s por empresa).
        </Note>
      )}
      {(regiao || lote.device) && (
        <div className="caption" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          Gerado em {regiao && <span className="tag reg">{regiao}</span>} {lote.device && <span className="tag">{lote.device}</span>}
        </div>
      )}

      <div className="kpis">
        <div className="kpi"><div className="n">{n}</div><div className="l">Empresas</div></div>
        <div className="kpi"><div className="n">{conta("Soluções")}</div><div className="l">Com necessidade</div></div>
        <div className="kpi"><div className="n">{conta("Email")}</div><div className="l">Com e-mail</div></div>
        <div className="kpi"><div className="n">{conta("Phone")}</div><div className="l">Com telefone</div></div>
        <div className="kpi hot"><div className="n">{hot}</div><div className="l">HOT</div></div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="ph">Suas soluções mais demandadas neste lote</div>
          <div className="pb">
            {contagem.length === 0 ? (
              <span className="caption">Nenhuma necessidade identificada neste lote</span>
            ) : (
              contagem.slice(0, 14).map(([s, c]) => (
                <button key={s} className={`chip${filtroSol.includes(s) ? " on" : ""}`} onClick={() => setFiltroSol(toggle(filtroSol, s))} aria-pressed={filtroSol.includes(s)}>
                  {s} <b>{c}</b>
                </button>
              ))
            )}
          </div>
        </div>
        <div className="panel">
          <div className="ph">Prioridade dos leads</div>
          <div className="pb">
            <div className="distbar">
              <span style={{ width: `${(100 * hot) / total}%`, background: "var(--hot)" }} />
              <span style={{ width: `${(100 * warm) / total}%`, background: "var(--warm)" }} />
              <span style={{ width: `${(100 * cold) / total}%`, background: "var(--cold)" }} />
            </div>
            <div className="legend">
              <span><i style={{ background: "var(--hot)" }} />HOT · {hot}</span>
              <span><i style={{ background: "var(--warm)" }} />WARM · {warm}</span>
              <span><i style={{ background: "var(--cold)" }} />COLD · {cold}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="sec">3 · Filtrar por solução e explorar</div>
      <p className="caption" style={{ margin: 0 }}>
        Clique nas soluções acima para filtrar (empresa que precise de QUALQUER uma das escolhidas).
        {filtroSol.length > 0 && <> <button className="link-btn" onClick={() => setFiltroSol([])}>Limpar filtro</button></>}
      </p>
      <div className="row">
        <input className="input" style={{ flex: 3 }} placeholder="Buscar empresa pelo nome…" value={busca} onChange={(e) => setBusca(e.target.value)} aria-label="Buscar empresa" />
        <div style={{ flex: 2, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <span className="caption">Mostrar só com:</span>
          {Object.keys(REQ).filter((k) => k !== "LinkedIn" || cols.includes("LinkedIn")).map((k) => (
            <label key={k} className="check" style={{ fontSize: 13 }}>
              <input type="checkbox" checked={exige.includes(k)} onChange={() => setExige(toggle(exige, k))} /> {k}
            </label>
          ))}
        </div>
      </div>

      <div className="table-wrap has-cards">
        <table className="data">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c} onClick={() => setOrdem({ col: c, asc: ordem.col === c ? !ordem.asc : true })} aria-sort={ordem.col === c ? (ordem.asc ? "ascending" : "descending") : "none"}>
                  {LABELS[c] || c}{ordem.col === c ? (ordem.asc ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.map((r, i) => (
              <tr key={`${r.Website}-${i}`}>
                {cols.map((c) => <Cell key={c} col={c} value={r[c]} curtos={curtos} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="lcards">
        {view.map((r, i) => (
          <div className="lcard" key={`${r.Website}-${i}`}>
            <div className="lc-top">
              <span className="lc-name">{String(r.Company || "—")}</span>
              <span className={`cls ${r.Classification}`}>{String(r.Classification || "—")}</span>
            </div>
            {preenchido(r["Soluções"]) && <div className="lc-sols">{String(r["Soluções"])}</div>}
            <div className="lc-meta">{[r.Porte, r.City, r.Score ? `Score ${r.Score}` : ""].filter(preenchido).join(" · ")}</div>
            {preenchido(r.Phone) && <span className="lc-c">{String(r.Phone)}</span>}
            {preenchido(r.Email) && <span className="lc-c">{String(r.Email)}{r.TipoEmail ? ` · ${r.TipoEmail}` : ""}</span>}
            {safeUrl(r.Website) && <a href={safeUrl(r.Website)} target="_blank" rel="noopener noreferrer" style={{ display: "inline-block", marginTop: 10 }}>Ir para o site</a>}
          </div>
        ))}
      </div>
      <p className="caption" style={{ margin: 0 }}>
        Mostrando {view.length} de {n} empresas
        {filtroSol.length > 0 && ` · filtrando por: ${filtroSol.join(", ")}`}
        {mantidos > 0 && ` · ${mantidos} mantida(s) sem telefone por alta qualidade`}.
      </p>
      {det.bloqueios.length > 0 && (
        <Note>
          <span className="lock" />
          {det.bloqueios.map((b) => `${b.nome} — ${b.selo}`).join(" · ")}
        </Note>
      )}
      <div>
        <a className="btn" href={`/api/lotes/${encodeURIComponent(loteId)}/xlsx`} download>Baixar planilha (.xlsx)</a>
      </div>
    </div>
  );
}

// Só http(s): um "javascript:" vindo do site de terceiro nunca vira link clicável.
function safeUrl(v: unknown): string {
  const s = String(v ?? "").trim();
  return /^https?:\/\//i.test(s) ? s : "";
}

function Cell({ col, value, curtos }: { col: string; value: unknown; curtos: Record<string, string> }) {
  const s = String(value ?? "");
  if (col === "Company") return <td className="company">{s || "—"}</td>;
  if (col === "Website") return <td style={{ whiteSpace: "nowrap" }}>{safeUrl(s) ? <a href={safeUrl(s)} target="_blank" rel="noopener noreferrer">Ir para o site</a> : ""}</td>;
  if (col === "LinkedIn") return <td>{safeUrl(s) ? <a href={safeUrl(s)} target="_blank" rel="noopener noreferrer">Abrir</a> : ""}</td>;
  if (col === "Soluções") return <td title={s} style={{ minWidth: 160 }}>{solsCurto(s, curtos)}</td>;
  if (col === "Email") return <td className="email">{s}</td>;
  if (col === "Classification") return <td>{s && <span className={`cls ${s}`}>{s}</span>}</td>;
  return <td style={{ whiteSpace: col === "Phone" ? "nowrap" : undefined }}>{s}</td>;
}
