"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errMsg, type Job, type Lote, type Selection } from "@/lib/api";
import { fmtStamp } from "@/lib/format";
import { Note } from "@/components/Modal";
import { useMembro } from "@/components/Session";
import { useJob } from "@/components/useJob";

const CLASSES = ["HOT", "WARM", "COLD"] as const;
type Classe = (typeof CLASSES)[number];
type Template = { origem: "upload" | "padrao" | "nenhum"; preview_html: string; campos: string[] };

export default function EmailsPage() {
  const membro = useMembro();
  if (!membro) return null;
  return <Emails />;
}

function Emails() {
  const [lotes, setLotes] = useState<Lote[]>([]);
  const [lote, setLote] = useState("");
  const [classes, setClasses] = useState<Classe[]>(["HOT"]);
  const [sel, setSel] = useState<Selection | null>(null);
  const [erro, setErro] = useState("");
  const [confirmo, setConfirmo] = useState(false);
  const [resultado, setResultado] = useState<{ kind: "ok" | "warn" | "err"; text: string; itens?: string[] } | null>(null);

  const atualizar = useCallback(async () => {
    try {
      setSel(await api<Selection>("/email/selection", "POST", { lote: lote || null, classes }));
      setErro("");
    } catch (e) {
      setErro(errMsg(e));
    }
  }, [lote, classes]);

  useEffect(() => {
    api<{ lotes: Lote[] }>("/lotes").then((r) => setLotes(r.lotes)).catch(() => undefined);
  }, []);
  useEffect(() => {
    api<Selection>("/email/selection", "POST", { lote: lote || null, classes })
      .then((r) => { setSel(r); setErro(""); })
      .catch((e) => setErro(errMsg(e)));
  }, [lote, classes]);

  const { job, running, start } = useJob("email", (j: Job) => {
    const r = (j.result || {}) as { enviados?: number; falhas?: string[]; pulados?: string[] };
    if (j.status === "done") {
      const extras = [...(r.pulados || []).map((p) => `Descartado: ${p}`), ...(r.falhas || []).map((f) => `Falha: ${f}`)];
      setResultado({ kind: extras.length ? "warn" : "ok", text: `${r.enviados || 0} e-mail(s) enviado(s).`, itens: extras });
    } else {
      setResultado({ kind: "err", text: j.error || "Falha no disparo." });
    }
    setConfirmo(false);
    atualizar();
  });

  async function disparar() {
    setResultado(null);
    try {
      start(await api<Job>("/jobs/email", "POST", { lote: lote || null, classes, confirmar: true }));
    } catch (e) {
      setResultado({ kind: "err", text: errMsg(e) });
    }
  }

  const toggle = (c: Classe) => setClasses(classes.includes(c) ? classes.filter((x) => x !== c) : [...classes, c]);

  return (
    <>
      <div className="sec">Enviar e-mail para os seus leads</div>
      <div className="stack">
        <div className="row">
          <label className="field" style={{ flex: 3 }}>
            Para qual lista você quer enviar?
            <select className="input" value={lote} onChange={(e) => setLote(e.target.value)} disabled={running}>
              <option value="">Todos os leads</option>
              {lotes.map((l) => <option key={l.id} value={l.id}>{fmtStamp(l.id)} · {l.count} empresas</option>)}
            </select>
          </label>
          <div className="field" style={{ flex: 2 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--muted)" }}>Só estas prioridades (vazio = todas)</span>
            <div style={{ display: "flex", gap: 14, height: 44, alignItems: "center" }}>
              {CLASSES.map((c) => (
                <label key={c} className="check">
                  <input type="checkbox" checked={classes.includes(c)} onChange={() => toggle(c)} disabled={running} /> {c}
                </label>
              ))}
            </div>
          </div>
        </div>

        <TemplateBox />

        {erro && <Note kind="err">{erro}</Note>}
        {sel && (
          <>
            <p className="caption" style={{ margin: 0 }}>Seleção atual: <b>{sel.selecionadas}</b> empresa(s).</p>
            {sel.remetente && (
              <p className="caption" style={{ margin: 0 }}>
                Os e-mails sairão de <b>{sel.remetente.from_name} &lt;{sel.remetente.from_email}&gt;</b> ({sel.remetente.origem}).
              </p>
            )}
            {sel.pendentes > 0 && (
              <p className="caption" style={{ margin: 0 }}>
                Pendentes nesta lista: <b>{sel.pendentes}</b>. Cota de hoje: <b>{sel.cota_restante}</b> (teto {sel.teto_hoje}/dia
                {sel.warmup ? ", com aquecimento" : ""}). Este disparo envia <b>{sel.envia_agora}</b>, com pausa de {sel.delay_min}–{sel.delay_max}s
                entre cada um (~{sel.eta_min} min). Quem já recebeu nunca repete.
              </p>
            )}
            {!sel.pode_enviar && sel.motivo && <Note kind="warn">{sel.motivo}</Note>}
            <div className="row" style={{ alignItems: "center" }}>
              <label className="check" style={{ flex: 1 }}>
                <input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} disabled={!sel.pode_enviar || running} />
                Confirmo o envio
              </label>
              <button className="btn primary" style={{ flex: 2 }} onClick={disparar} disabled={!confirmo || !sel.pode_enviar || running}>
                {running ? <><span className="spinner" /> Enviando…</> : "Enviar e-mail"}
              </button>
            </div>
          </>
        )}
        {running && job && <Note><b>Disparo em andamento.</b> <span className="caption">{job.progress} · Pode sair desta tela; o envio continua no servidor.</span></Note>}
        {resultado && (
          <Note kind={resultado.kind}>
            {resultado.text}
            {resultado.itens && resultado.itens.length > 0 && (
              <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>{resultado.itens.slice(0, 10).map((x) => <li key={x}>{x}</li>)}</ul>
            )}
          </Note>
        )}
      </div>
    </>
  );
}

function TemplateBox() {
  const [tpl, setTpl] = useState<Template | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const carregar = () => api<Template>("/email/template").then(setTpl).catch(() => undefined);
  useEffect(() => {
    carregar();
  }, []);

  async function subir(file: File | undefined) {
    if (!file) return;
    if (file.size > 500_000) return setMsg({ kind: "err", text: "Arquivo grande demais (máx. 500 KB)." });
    try {
      await api("/email/template", "PUT", { html: await file.text() });
      setMsg({ kind: "ok", text: "Template atualizado." });
      carregar();
    } catch (e) {
      setMsg({ kind: "err", text: errMsg(e) });
    }
  }

  return (
    <details className="card" style={{ padding: "14px 18px" }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>Template do e-mail (prévia e troca)</summary>
      <div className="stack" style={{ marginTop: 12 }}>
        <p className="caption" style={{ margin: 0 }}>
          Este template é <b>só seu</b> — trocá-lo não afeta os outros usuários. Campos disponíveis:{" "}
          {(tpl?.campos || []).map((c) => <code key={c} style={{ marginRight: 6 }}>{c}</code>)}
        </p>
        <label className="field">
          Subir um .html novo
          <input type="file" accept=".html,.htm,text/html" onChange={(e) => subir(e.target.files?.[0])} />
        </label>
        {msg && <Note kind={msg.kind}>{msg.text}</Note>}
        {tpl && tpl.preview_html && (
          <>
            <p className="caption" style={{ margin: 0 }}>
              Em uso: <b>{tpl.origem === "upload" ? "seu upload" : "modelo padrão"}</b>. Prévia:
            </p>
            {/* sandbox vazio: sem script, sem formulário, origem isolada — o HTML
                veio de upload e é renderizado aqui só para ser visto. */}
            <iframe className="preview" sandbox="" srcDoc={tpl.preview_html} title="Prévia do e-mail" />
            {tpl.origem === "upload" && (
              <div>
                <button className="btn sm" onClick={async () => { await api("/email/template", "DELETE").catch(() => undefined); carregar(); }}>
                  Voltar ao modelo padrão
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </details>
  );
}
