"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errMsg, type AdminUser, type S } from "@/lib/api";
import { fmtDateTime, fmtNum, fmtStamp, gerarSenha, initials } from "@/lib/format";
import { Modal, Note } from "@/components/Modal";
import { useMembro, useSession } from "@/components/Session";

type Aba = "plano" | "usuarios" | "lotes" | "remetentes" | "atividade";
type UsersResp = S["UsersOut"];

export default function AdminPage() {
  const membro = useMembro();
  const [aba, setAba] = useState<Aba>("plano");
  if (!membro) return null;
  if (membro.me.user.role !== "admin") return <Note kind="err">Acesso restrito à administração.</Note>;
  const abas: [Aba, string][] = [["plano", "Plano"], ["usuarios", "Usuários"], ["lotes", "Lotes"], ["remetentes", "Remetentes"], ["atividade", "Atividade"]];
  return (
    <>
      <div className="sec">Administração</div>
      <div className="tabs" role="tablist">
        {abas.map(([k, rot]) => (
          <button key={k} role="tab" aria-selected={aba === k} className={aba === k ? "on" : ""} onClick={() => setAba(k)}>{rot}</button>
        ))}
      </div>
      {aba === "plano" && <Plano />}
      {aba === "usuarios" && <Usuarios />}
      {aba === "lotes" && <Lotes />}
      {aba === "remetentes" && <Remetentes />}
      {aba === "atividade" && <Atividade />}
    </>
  );
}

function useUsers() {
  const [data, setData] = useState<UsersResp | null>(null);
  const [erro, setErro] = useState("");
  const reload = useCallback(() => api<UsersResp>("/admin/users").then(setData).catch((e) => setErro(errMsg(e))), []);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, erro, reload };
}

// ------------------------------------------------------------------ Plano
const ROT_LIM: Record<string, string> = {
  usuarios: "Usuários", leads_mes: "Leads por mês", leads_clique: "Leads por clique",
  historico_dias: "Histórico (dias)", emails_dia: "E-mails por dia",
};
const ROT_REC: Record<string, string> = {
  porte: "Porte + dados da Receita", linkedin: "LinkedIn da empresa", filtro_regiao: "Filtro por macro-região",
};

function Plano() {
  const [p, setP] = useState<S["PlanAdminOut"] | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    api<S["PlanAdminOut"]>("/admin/plan").then(setP).catch((e) => setErro(errMsg(e)));
  }, []);
  if (!p) return erro ? <Note kind="err">{erro}</Note> : <p className="caption">Carregando…</p>;
  const m = p.matriz;

  return (
    <div className="stack">
      {p.em_teste ? (
        <Note kind="ok">
          <b>Em teste até {p.trial_ate}</b> — a empresa roda liberada como <b>{m.planos[p.efetivo].nome}</b>. Ao fim do período volta para <b>{m.planos[p.contratado].nome}</b>.
        </Note>
      ) : (
        <p className="caption" style={{ margin: 0 }}>Plano em vigor: <b>{m.planos[p.efetivo].nome}</b></p>
      )}
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Recurso</th>{m.ordem.map((k) => <th key={k}>{m.planos[k].nome}{k === p.efetivo ? " (atual)" : ""}</th>)}</tr></thead>
          <tbody>
            {Object.entries(ROT_LIM).map(([k, rot]) => (
              <tr key={k}><td>{rot}</td>{m.ordem.map((pl) => <td key={pl}>{fmtNum(m.planos[pl].limites[k], m.ilimitado)}</td>)}</tr>
            ))}
            {Object.entries(ROT_REC).map(([k, rot]) => (
              <tr key={k}><td>{rot}</td>{m.ordem.map((pl) => <td key={pl}>{m.planos[pl].recursos[k] ? "✓" : "—"}</td>)}</tr>
            ))}
            <tr><td>Preço por mês</td>{m.ordem.map((pl) => <td key={pl}>{m.planos[pl].preco}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <p className="caption" style={{ margin: 0 }}>Para mudar de plano, fale com o suporte da plataforma.</p>
    </div>
  );
}

// --------------------------------------------------------------- Usuários
function Usuarios() {
  const { me } = useSession();
  const { data, erro, reload } = useUsers();
  const [novo, setNovo] = useState(false);
  const [gerir, setGerir] = useState<AdminUser | null>(null);
  if (erro) return <Note kind="err">{erro}</Note>;
  if (!data) return <p className="caption">Carregando…</p>;
  const cheio = !data.ilimitado && data.total >= data.limite;
  const inativos = data.total - data.ativos;

  return (
    <div className="stack">
      <div className="list-row">
        <span className="caption" style={{ fontWeight: 600 }}>
          {data.ilimitado ? `${data.total} usuário(s)` : `${data.total} de ${data.limite} usuário(s) do plano`}
          {` · ${data.ativos} ativo(s) · ${data.admins} admin(s)`}
          {inativos > 0 && ` · ${inativos} inativo(s), que segue(m) ocupando vaga`}
        </span>
        <button className="btn primary" disabled={cheio} onClick={() => setNovo(true)}
          title={cheio ? "O plano está cheio, contando os inativos. Remova um usuário ou mude de plano — desativar não libera a vaga." : undefined}>
          Novo usuário
        </button>
      </div>
      {data.users.map((u) => (
        <div key={u.id} className="card list-row" style={{ padding: 14 }}>
          <div className="ucard">
            <div className="avatar">{initials(u.name || u.email)}</div>
            <div>
              <div className="u-name">{u.name || "—"}</div>
              <div className="u-mail">{u.email}</div>
              <div className="badges">
                <span className={`badge${u.role === "admin" ? " admin" : ""}`}>{u.role === "admin" ? "Admin" : "Vendedor"}</span>
                <span className={`status ${u.active ? "on" : "off"}`}>{u.active ? "Ativo" : "Inativo"}</span>
              </div>
            </div>
          </div>
          <button className="btn sm" onClick={() => setGerir(u)}>Gerenciar</button>
        </div>
      ))}
      {novo && <NovoUsuario cheio={cheio} limite={data.limite} total={data.total} onClose={() => setNovo(false)} onOk={() => { setNovo(false); reload(); }} />}
      {gerir && <Gerenciar u={gerir} self={gerir.id === me.user.id} onClose={() => setGerir(null)} onOk={() => { setGerir(null); reload(); }} />}
    </div>
  );
}

function NovoUsuario({ cheio, limite, total, onClose, onOk }: { cheio: boolean; limite: number; total: number; onClose: () => void; onOk: () => void }) {
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  return (
    <Modal title="Novo usuário" onClose={onClose}>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
          try {
            await api("/admin/users", "POST", { email: f.email, name: f.name, role: f.role, password: senha });
            onOk();
          } catch (err) {
            setErro(errMsg(err));
          }
        }}
      >
        {cheio && <Note kind="warn">O plano permite {limite} usuário(s) e a conta já tem {total}, contando os inativos. Remova um usuário ou mude de plano — desativar não libera a vaga.</Note>}
        <label className="field">E-mail<input className="input" name="email" type="email" required /></label>
        <label className="field">Nome<input className="input" name="name" /></label>
        <label className="field">Papel<select className="input" name="role" defaultValue="vendedor"><option value="vendedor">vendedor</option><option value="admin">admin</option></select></label>
        <div className="row">
          <label className="field" style={{ flex: 3 }}>
            Senha inicial (mín. 6)
            <input className="input" type="text" value={senha} onChange={(e) => setSenha(e.target.value)} minLength={6} autoComplete="off" required />
          </label>
          <button type="button" className="btn" style={{ flex: 1 }} onClick={() => setSenha(gerarSenha())}>Gerar</button>
        </div>
        {senha && <p className="caption" style={{ margin: 0 }}>Copie a senha agora e envie ao usuário (ele pode trocá-la depois).</p>}
        {erro && <Note kind="err">{erro}</Note>}
        <div className="row">
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={cheio}>Criar usuário</button>
        </div>
      </form>
    </Modal>
  );
}

function Gerenciar({ u, self, onClose, onOk }: { u: AdminUser; self: boolean; onClose: () => void; onOk: () => void }) {
  const [erro, setErro] = useState("");
  const [msg, setMsg] = useState("");
  const [confirmar, setConfirmar] = useState<"remover" | "desativar" | null>(null);

  async function patch(body: object) {
    setErro("");
    try {
      const r = await api<{ detail: string }>(`/admin/users/${u.id}`, "PATCH", body);
      if (r.detail === "Nenhuma alteração.") setMsg(r.detail);
      else onOk();
    } catch (e) {
      setErro(errMsg(e));
    }
  }

  return (
    <Modal title="Gerenciar usuário" onClose={onClose} large>
      <div className="ucard" style={{ marginBottom: 14 }}>
        <div className="avatar">{initials(u.name || u.email)}</div>
        <div><div className="u-name">{u.name || "—"}</div><div className="u-mail">{u.email}</div></div>
      </div>
      {confirmar ? (
        <div className="stack">
          <p style={{ margin: 0 }}>
            {confirmar === "remover" ? <>Remover <b>{u.name || u.email}</b> em definitivo? Esta ação não poderá ser desfeita.</> : <>Desativar <b>{u.name || u.email}</b>? O usuário perde o acesso até ser reativado.</>}
          </p>
          {erro && <Note kind="err">{erro}</Note>}
          <div className="row">
            <button className="btn" onClick={() => setConfirmar(null)}>Cancelar</button>
            <button
              className="btn primary"
              onClick={async () => {
                if (confirmar === "desativar") return patch({ active: false });
                try {
                  await api(`/admin/users/${u.id}`, "DELETE");
                  onOk();
                } catch (e) {
                  setErro(errMsg(e));
                }
              }}
            >
              Sim, confirmar
            </button>
          </div>
        </div>
      ) : (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
            patch({ role: f.role, name: f.name, ...(f.password ? { password: f.password } : {}) });
          }}
        >
          <label className="field">Papel<select className="input" name="role" defaultValue={u.role}><option value="vendedor">vendedor</option><option value="admin">admin</option></select></label>
          <label className="field">Nome<input className="input" name="name" defaultValue={u.name} /></label>
          <label className="field">Nova senha de acesso (em branco = manter)<input className="input" name="password" type="password" minLength={6} autoComplete="new-password" /></label>
          {erro && <Note kind="err">{erro}</Note>}
          {msg && <Note>{msg}</Note>}
          <button className="btn primary">Salvar acesso</button>
          <hr className="divider" />
          <div className="row">
            {u.active ? (
              <button type="button" className="btn" disabled={self} onClick={() => setConfirmar("desativar")}>Desativar</button>
            ) : (
              <button type="button" className="btn" onClick={() => patch({ active: true })}>Reativar</button>
            )}
            <button type="button" className="btn" disabled={self} onClick={() => setConfirmar("remover")}>Remover</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

// ------------------------------------------------------------------- Lotes
function Lotes() {
  const { data: users } = useUsers();
  const [lotes, setLotes] = useState<S["AdminLote"][] | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [alvo, setAlvo] = useState<Record<string, string>>({});
  const carregar = useCallback(() => api<S["AdminLote"][]>("/admin/lotes").then(setLotes).catch((e) => setMsg({ kind: "err", text: errMsg(e) })), []);
  useEffect(() => {
    carregar();
  }, [carregar]);
  const vendedores = (users?.users || []).filter((u) => u.active && u.role !== "admin");
  if (!lotes) return msg ? <Note kind="err">{msg.text}</Note> : <p className="caption">Carregando…</p>;

  return (
    <div className="stack">
      {msg && <Note kind={msg.kind}>{msg.text}</Note>}
      {lotes.length === 0 && <p className="caption">Nenhum lote no banco ainda.</p>}
      {lotes.map((l) => (
        <div key={l.id} className="card list-row" style={{ padding: 14, flexWrap: "wrap" }}>
          <div>
            <b>{fmtStamp(l.id)}</b> · {l.count} leads · {l.device || "—"}
            <div className="caption">gerou: <b>{l.generated_by_name}</b> · trabalhando: <b>{l.owner_name}</b></div>
          </div>
          {vendedores.length === 0 ? (
            <span className="caption">Cadastre um vendedor para atribuir.</span>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <select className="input" style={{ width: 200 }} value={alvo[l.id] || vendedores[0].id} onChange={(e) => setAlvo({ ...alvo, [l.id]: e.target.value })} aria-label="Atribuir para">
                {vendedores.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
              </select>
              <button
                className="btn primary sm"
                style={{ height: 44 }}
                onClick={async () => {
                  try {
                    const r = await api<{ detail: string }>(`/admin/lotes/${l.id}/owner`, "POST", { user_id: alvo[l.id] || vendedores[0].id });
                    setMsg({ kind: "ok", text: r.detail });
                    carregar();
                  } catch (e) {
                    setMsg({ kind: "err", text: errMsg(e) });
                  }
                }}
              >
                Atribuir lote
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------------------------- Remetentes
function Remetentes() {
  const { me } = useSession();
  const [data, setData] = useState<S["SendersOut"] | null>(null);
  const [uid, setUid] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const carregar = useCallback(() => api<S["SendersOut"]>("/admin/senders").then((r) => {
    setData(r);
    setUid((atual) => atual || r.senders[0]?.user_id || "");
  }).catch((e) => setMsg({ kind: "err", text: errMsg(e) })), []);
  useEffect(() => {
    carregar();
  }, [carregar]);
  if (!data) return msg ? <Note kind="err">{msg.text}</Note> : <p className="caption">Carregando…</p>;
  const atual = data.senders.find((s) => s.user_id === uid);

  return (
    <div className="stack">
      <p className="caption" style={{ margin: 0 }}>
        Cada vendedor dispara da PRÓPRIA caixa — assim as respostas e a pasta Enviados ficam com ele, e a reputação do
        domínio não fica concentrada num remetente só.
      </p>
      {!data.encryption_available && (
        <Note kind="warn">Defina <b>EMAIL_ENC_KEY</b> no servidor para guardar a senha de app cifrada. Sem ela, o cadastro de remetente fica bloqueado — o app não grava senha em texto puro.</Note>
      )}
      <label className="field">
        Vendedor
        <select className="input" value={uid} onChange={(e) => { setUid(e.target.value); setMsg(null); }}>
          {data.senders.map((s) => <option key={s.user_id} value={s.user_id}>{s.user_name}{s.configured ? "  ·  remetente ativo" : ""}</option>)}
        </select>
      </label>
      {atual && (
        <form
          key={atual.user_id}
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
            try {
              const r = await api<{ detail: string }>(`/admin/senders/${atual.user_id}`, "PUT", {
                from_email: f.from_email, from_name: f.from_name, smtp_host: f.smtp_host,
                smtp_port: Number(f.smtp_port), smtp_password: f.smtp_password || null,
              });
              setMsg({ kind: "ok", text: r.detail });
              carregar();
            } catch (err) {
              setMsg({ kind: "err", text: errMsg(err) });
            }
          }}
        >
          <label className="field">E-mail de envio<input className="input" name="from_email" type="email" defaultValue={atual.from_email || atual.user_email} required /></label>
          <label className="field">
            Senha de app {atual.has_password ? "(em branco = manter a atual)" : ""}
            <input className="input" name="smtp_password" type="password" autoComplete="new-password" />
            <span className="caption">Gmail: senha de APP de 16 letras. A senha normal da conta não funciona.</span>
          </label>
          <label className="field">Nome de exibição<input className="input" name="from_name" defaultValue={atual.from_name || me.org.marca.nome || me.org.name} /></label>
          <details>
            <summary className="caption" style={{ cursor: "pointer" }}>Outro provedor (não-Gmail)</summary>
            <div className="row" style={{ marginTop: 10 }}>
              <label className="field">Servidor SMTP<input className="input" name="smtp_host" defaultValue={atual.smtp_host} /></label>
              <label className="field">Porta<input className="input" name="smtp_port" type="number" defaultValue={atual.smtp_port} /></label>
            </div>
          </details>
          {msg && <Note kind={msg.kind}>{msg.text}</Note>}
          <button className="btn primary" disabled={!data.encryption_available}>Salvar remetente</button>
          {atual.configured && (
            <>
              <p className="caption" style={{ margin: 0 }}>Hoje dispara de: <b>{atual.from_name} &lt;{atual.from_email}&gt;</b></p>
              <div>
                <button type="button" className="btn sm" onClick={async () => {
                  await api(`/admin/senders/${atual.user_id}`, "DELETE").catch(() => undefined);
                  carregar();
                }}>Remover remetente</button>
              </div>
            </>
          )}
        </form>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Atividade
function Atividade() {
  const { data: users } = useUsers();
  const [filtro, setFiltro] = useState("");
  const [logs, setLogs] = useState<S["AuditEntry"][] | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api<S["AuditEntry"][]>(`/admin/audit${filtro ? `?user_id=${encodeURIComponent(filtro)}` : ""}`).then(setLogs).catch((e) => setErro(errMsg(e)));
  }, [filtro]);

  return (
    <div className="stack">
      <label className="field" style={{ maxWidth: 360 }}>
        Filtrar por usuário
        <select className="input" value={filtro} onChange={(e) => setFiltro(e.target.value)}>
          <option value="">(todos)</option>
          {(users?.users || []).map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
        </select>
      </label>
      {erro && <Note kind="err">{erro}</Note>}
      {logs && logs.length === 0 && <p className="caption">Sem registros ainda.</p>}
      {logs && logs.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Quando</th><th>Usuário</th><th>Ação</th><th>Detalhe</th></tr></thead>
            <tbody>
              {logs.map((l, i) => (
                <tr key={`${l.ts}-${i}`}><td style={{ whiteSpace: "nowrap" }}>{fmtDateTime(l.ts)}</td><td>{l.user}</td><td>{l.action}</td><td>{l.detail}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
