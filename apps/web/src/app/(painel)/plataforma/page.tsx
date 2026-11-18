"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, errMsg, type Marca, type S, type Tenant } from "@/lib/api";
import { fmtDate, gerarSenha } from "@/lib/format";
import { Selo } from "@/components/Marca";
import { Modal, Note } from "@/components/Modal";
import { useSession } from "@/components/Session";

const PLANOS = [["essencial", "Essencial"], ["profissional", "Profissional"], ["empresarial", "Empresarial"]] as const;
type Msg = { kind: "ok" | "err" | "warn"; text: string } | null;

export default function PlataformaPage() {
  const { me } = useSession();
  const router = useRouter();
  const dono = me.user.role === "superadmin";
  useEffect(() => {
    if (!dono) router.replace("/");
  }, [dono, router]);
  if (!dono) return null;
  return <Empresas />;
}

function Empresas() {
  const [lista, setLista] = useState<Tenant[] | null>(null);
  const [erro, setErro] = useState("");
  const [nova, setNova] = useState(false);
  const [gerir, setGerir] = useState<Tenant | null>(null);
  const carregar = useCallback(() => api<Tenant[]>("/plataforma/empresas").then(setLista).catch((e) => setErro(errMsg(e))), []);
  useEffect(() => {
    carregar();
  }, [carregar]);

  return (
    <>
      <div className="sec">Empresas clientes</div>
      <div className="stack">
        <div className="list-row">
          <p className="caption" style={{ margin: 0 }}>
            Cada empresa tem o seu nicho (o que buscar, como pontuar e o que oferecer), a sua marca e o seu plano.
            Os dados de uma nunca aparecem para outra — nem para você.
          </p>
          <button className="btn primary" onClick={() => setNova(true)}>Nova empresa</button>
        </div>
        {erro && <Note kind="err">{erro}</Note>}
        {lista && lista.length === 0 && <Note>Nenhuma empresa ainda. Crie a primeira em <b>Nova empresa</b>.</Note>}
        {lista && lista.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Empresa</th><th>Nicho</th><th>Plano</th><th>Usuários</th><th>Situação</th><th></th></tr></thead>
              <tbody>
                {lista.map((t) => (
                  <tr key={t.id}>
                    <td className="company">{t.name}</td>
                    <td>{t.nicho_nome || "—"}</td>
                    <td>{PLANOS.find(([k]) => k === t.plano)?.[1] || t.plano}{t.trial_ate ? ` · teste até ${fmtDate(t.trial_ate)}` : ""}</td>
                    <td>{t.usuarios}</td>
                    <td><span className={`status ${t.active ? "on" : "off"}`}>{t.active ? "Ativa" : "Suspensa"}</span></td>
                    <td><button className="btn sm" onClick={() => setGerir(t)}>Configurar</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {nova && <NovaEmpresa onClose={() => setNova(false)} onOk={() => { setNova(false); carregar(); }} />}
      {gerir && <Configurar t={gerir} onClose={() => { setGerir(null); carregar(); }} />}
    </>
  );
}

function NovaEmpresa({ onClose, onOk }: { onClose: () => void; onOk: () => void }) {
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="Nova empresa" onClose={onClose}>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
          setBusy(true);
          setErro("");
          try {
            await api("/plataforma/empresas", "POST", {
              name: f.name, plano: f.plano, trial_ate: f.trial_ate || "",
              admin_name: f.admin_name, admin_email: f.admin_email, admin_password: senha,
            });
            onOk();
          } catch (err) {
            setErro(errMsg(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="caption" style={{ margin: 0 }}>A empresa nasce com o nicho de exemplo. Depois você ajusta em <b>Configurar → Nicho</b>.</p>
        <label className="field">Nome da empresa<input className="input" name="name" required minLength={2} maxLength={120} /></label>
        <div className="row">
          <label className="field">Plano
            <select className="input" name="plano" defaultValue="essencial">
              {PLANOS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}
            </select>
          </label>
          <label className="field">Teste liberado até<input className="input" name="trial_ate" type="date" /></label>
        </div>
        <hr className="divider" />
        <p className="caption" style={{ margin: 0 }}><b>Primeiro administrador</b> da empresa (ele cria os vendedores).</p>
        <label className="field">Nome<input className="input" name="admin_name" /></label>
        <label className="field">E-mail de login<input className="input" name="admin_email" type="email" required /></label>
        <div className="row">
          <label className="field" style={{ flex: 3 }}>
            Senha inicial (mín. 6)
            <input className="input" type="text" value={senha} onChange={(e) => setSenha(e.target.value)} minLength={6} autoComplete="off" required />
          </label>
          <button type="button" className="btn" style={{ flex: 1 }} onClick={() => setSenha(gerarSenha())}>Gerar</button>
        </div>
        {senha && <p className="caption" style={{ margin: 0 }}>Copie a senha agora e envie ao administrador (ele pode trocá-la depois).</p>}
        {erro && <Note kind="err">{erro}</Note>}
        <div className="row">
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={busy}>Criar empresa</button>
        </div>
      </form>
    </Modal>
  );
}

function Configurar({ t, onClose }: { t: Tenant; onClose: () => void }) {
  const [aba, setAba] = useState<"dados" | "nicho" | "marca">("dados");
  return (
    <Modal title={`Configurar · ${t.name}`} onClose={onClose} large>
      <div className="tabs" role="tablist">
        {([["dados", "Dados e plano"], ["nicho", "Nicho"], ["marca", "Marca"]] as const).map(([k, r]) => (
          <button key={k} role="tab" aria-selected={aba === k} className={aba === k ? "on" : ""} onClick={() => setAba(k)}>{r}</button>
        ))}
      </div>
      {aba === "dados" && <Dados t={t} />}
      {aba === "nicho" && <Nicho t={t} />}
      {aba === "marca" && <MarcaEditor t={t} />}
      <div style={{ marginTop: 16 }}><button className="btn block" onClick={onClose}>Fechar</button></div>
    </Modal>
  );
}

function Dados({ t }: { t: Tenant }) {
  const [ativa, setAtiva] = useState(t.active);
  const [msg, setMsg] = useState<Msg>(null);
  async function patch(body: object, ok: string) {
    try {
      await api(`/plataforma/empresas/${t.id}`, "PATCH", body);
      setMsg({ kind: "ok", text: ok });
    } catch (e) {
      setMsg({ kind: "err", text: errMsg(e) });
    }
  }
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
        patch({ name: f.name, plano: f.plano, trial_ate: f.trial_ate || "" }, "Dados salvos.");
      }}
    >
      <label className="field">Nome<input className="input" name="name" defaultValue={t.name} required minLength={2} /></label>
      <div className="row">
        <label className="field">Plano
          <select className="input" name="plano" defaultValue={t.plano}>
            {PLANOS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}
          </select>
        </label>
        <label className="field">Teste liberado até (vazio = sem teste)<input className="input" name="trial_ate" type="date" defaultValue={t.trial_ate} /></label>
      </div>
      <button className="btn primary">Salvar dados</button>
      <hr className="divider" />
      <div className="list-row">
        <span className="caption">{ativa ? "A empresa está ativa." : "A empresa está SUSPENSA: ninguém dela consegue entrar."}</span>
        <button
          type="button"
          className="btn"
          onClick={async () => {
            await patch({ active: !ativa }, ativa ? "Empresa suspensa." : "Empresa reativada.");
            setAtiva(!ativa);
          }}
        >
          {ativa ? "Suspender acesso" : "Reativar acesso"}
        </button>
      </div>
      {msg && <Note kind={msg.kind}>{msg.text}</Note>}
    </form>
  );
}

function Nicho({ t }: { t: Tenant }) {
  const [yaml, setYaml] = useState("");
  const [resumo, setResumo] = useState<S["NichoOut"] | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<S["NichoOut"]>(`/plataforma/empresas/${t.id}/nicho`).then((r) => { setYaml(r.yaml); setResumo(r); })
      .catch((e) => setMsg({ kind: "err", text: errMsg(e) }));
  }, [t.id]);

  async function rodar(fn: () => Promise<void>) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ kind: "err", text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <p className="caption" style={{ margin: 0 }}>
        O nicho define <b>o tipo de lead</b> desta empresa: palavras de busca, pesos da nota, concorrentes, o
        <b> catálogo de soluções</b> (e as pistas no site que indicam cada uma), os cargos decisores e como medir o porte.
        Vale a partir do próximo lote. Guia: <code>docs/CONFIGURAR-NICHO.md</code>.
      </p>
      {resumo && <p className="caption" style={{ margin: 0 }}>Atual: <b>{resumo.nome}</b> · {resumo.palavras_chave} palavra(s)-chave · {resumo.solucoes} solução(ões)</p>}
      <textarea className="input code-edit" spellCheck={false} value={yaml} onChange={(e) => setYaml(e.target.value)} aria-label="Configuração do nicho (YAML)" />
      {msg && <Note kind={msg.kind}>{msg.text}</Note>}
      <div className="row">
        <button className="btn" disabled={busy} onClick={() => rodar(async () => {
          const r = await api<S["NichoOut"]>("/plataforma/nicho/validar", "POST", { yaml });
          setMsg({ kind: "ok", text: `Tudo certo: ${r.nome} · ${r.palavras_chave} palavra(s)-chave · ${r.solucoes} solução(ões).` });
        })}>Conferir</button>
        <button className="btn" disabled={busy} onClick={() => rodar(async () => {
          const r = await api<S["NichoOut"]>("/plataforma/nicho/exemplo");
          setYaml(r.yaml);
          setMsg({ kind: "warn", text: "Exemplo carregado no editor. Nada foi salvo ainda." });
        })}>Carregar exemplo</button>
        <button className="btn primary" disabled={busy} onClick={() => rodar(async () => {
          const r = await api<{ detail: string }>(`/plataforma/empresas/${t.id}/nicho`, "PUT", { yaml });
          const novo = await api<S["NichoOut"]>(`/plataforma/empresas/${t.id}/nicho`);
          setResumo(novo);
          setMsg({ kind: "ok", text: r.detail });
        })}>Salvar nicho</button>
      </div>
    </div>
  );
}

function MarcaEditor({ t }: { t: Tenant }) {
  const [m, setM] = useState<Marca | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  useEffect(() => {
    api<Marca>(`/plataforma/empresas/${t.id}/marca`).then(setM).catch((e) => setMsg({ kind: "err", text: errMsg(e) }));
  }, [t.id]);
  if (!m) return msg ? <Note kind={msg.kind}>{msg.text}</Note> : <p className="caption">Carregando…</p>;

  function lerLogo(file: File | undefined) {
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      return setMsg({ kind: "err", text: "Use PNG, JPEG ou WEBP." });
    }
    if (file.size > 150_000) return setMsg({ kind: "err", text: "Logo grande demais (máx. 150 KB)." });
    const leitor = new FileReader();
    leitor.onload = () => setM({ ...m!, logo: String(leitor.result || "") });
    leitor.readAsDataURL(file);
  }

  return (
    <div className="stack">
      <div className="ucard">
        <Selo marca={m} nome={m.nome || t.name} grande />
        <div><div className="u-name">{m.nome || t.name}</div><div className="u-mail">Prévia do selo no menu</div></div>
      </div>
      <label className="field">Nome de exibição<input className="input" value={m.nome} maxLength={60} onChange={(e) => setM({ ...m, nome: e.target.value })} /></label>
      <div className="row">
        <label className="field">Cor principal
          <input className="input" type="color" value={m.cor || "#3b5bdb"} onChange={(e) => setM({ ...m, cor: e.target.value })} />
        </label>
        <label className="field">Logo (PNG, JPEG ou WEBP, até 150 KB)
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => lerLogo(e.target.files?.[0])} />
        </label>
      </div>
      {m.logo && <div><button className="btn sm" onClick={() => setM({ ...m, logo: "" })}>Tirar logo</button></div>}
      {msg && <Note kind={msg.kind}>{msg.text}</Note>}
      <button className="btn primary" onClick={async () => {
        try {
          const r = await api<{ detail: string }>(`/plataforma/empresas/${t.id}/marca`, "PUT", m);
          setMsg({ kind: "ok", text: r.detail });
        } catch (e) {
          setMsg({ kind: "err", text: errMsg(e) });
        }
      }}>Salvar marca</button>
    </div>
  );
}
