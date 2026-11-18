"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { api, errMsg, type Me } from "@/lib/api";
import { fmtDate, fmtNum, initials } from "@/lib/format";
import { AplicaMarca, Selo } from "@/components/Marca";
import { Modal, Note } from "@/components/Modal";
import { SessionProvider } from "@/components/Session";

export default function PainelLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      {(me) =>
        me ? (
          <Shell me={me}>{children}</Shell>
        ) : (
          <main className="auth"><p className="caption">Carregando…</p></main>
        )
      }
    </SessionProvider>
  );
}

function Shell({ me, children }: { me: Me; children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [aberto, setAberto] = useState(false);
  const [trocar, setTrocar] = useState(false);
  const [toast, setToast] = useState("");
  const nome = me.user.name || me.user.email;
  const dono = me.user.role === "superadmin";
  const marcaNome = dono ? "ProspectAI" : me.org.marca.nome || me.org.name;
  const pl = me.plan;
  const papel = dono ? "Dono da plataforma" : me.user.role === "admin" ? "Administrador" : "Vendedor";

  const item = (href: string, rotulo: string) => (
    <Link href={href} className={path === href ? "active" : ""} onClick={() => setAberto(false)}>
      {rotulo}
    </Link>
  );

  async function sair() {
    await api("/auth/logout", "POST").catch(() => undefined);
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="shell">
      {!dono && <AplicaMarca marca={me.org.marca} />}
      <button className="btn sm menu-btn" onClick={() => setAberto(!aberto)} aria-label="Abrir menu">☰ Menu</button>
      <aside className={`sidebar${aberto ? " open" : ""}`}>
        <div className="brand">
          <Selo marca={dono ? { nome: "", cor: "", logo: "" } : me.org.marca} nome={marcaNome} />
          <div className="brand-name">{marcaNome}</div>
        </div>
        <nav className="nav">
          {dono ? (
            item("/plataforma", "Empresas")
          ) : (
            <>
              {item("/", "Gerar Leads")}
              {item("/emails", "Enviar E-mails")}
              {me.user.role === "admin" && item("/admin", "Administrar")}
            </>
          )}
        </nav>
        {/* O cliente precisa ver o que contratou e quanto já usou: sem isso o
            limite parece defeito da ferramenta, não fronteira do plano. */}
        {pl && <PlanoCard pl={pl} />}
        <hr className="divider" />
        <div className="sb-user">
          <div className="avatar">{initials(nome)}</div>
          <div>
            <div className="acct-name">{nome}</div>
            <div className="acct-role">{papel}</div>
          </div>
        </div>
        <button className="btn block" onClick={() => setTrocar(true)}>Trocar senha</button>
        <button className="btn block" onClick={sair}>Sair</button>
        {toast && <Note kind="ok">{toast}</Note>}
      </aside>
      <main className="main">
        <div className="container">
          <header className="hero">
            <Selo marca={dono ? { nome: "", cor: "", logo: "" } : me.org.marca} nome={marcaNome} grande />
            <div>
              <p className="eyebrow">{dono ? "ProspectAI · Plataforma" : `${me.org.name} · Prospecção B2B`}</p>
              <h1>{dono ? <>Prospect<em>AI</em></> : marcaNome}</h1>
              <p>
                {dono
                  ? "Crie as empresas clientes e configure o nicho de cada uma: o que buscar, como pontuar e o que oferecer."
                  : "Encontra empresas que precisam do que você vende — identifica a necessidade, o decisor e o contato."}
              </p>
            </div>
            <div className="pill"><span className="dot" /> Ativo</div>
          </header>
          {children}
          <div className="foot"><b>ProspectAI</b> · prospecção B2B configurável</div>
        </div>
      </main>
      {trocar && (
        <TrocarSenha
          onClose={() => setTrocar(false)}
          onOk={() => {
            setTrocar(false);
            setToast("Senha alterada com sucesso!");
            setTimeout(() => setToast(""), 4000);
          }}
        />
      )}
    </div>
  );
}

function PlanoCard({ pl }: { pl: NonNullable<Me["plan"]> }) {
  const cota = pl.limites.leads_mes;
  const ilim = cota >= pl.ilimitado;
  const pct = ilim ? 0 : Math.min(100, Math.round((100 * pl.uso_leads_mes) / Math.max(1, cota)));
  return (
    <div className="plano-card">
      <div className="pl-top">
        <span className="pl-nome">{pl.nome}</span>
        {pl.em_teste && <span className="pl-teste">teste até {fmtDate(pl.trial_ate)}</span>}
      </div>
      {!ilim && (
        <>
          <div className="bar"><span style={{ width: `${pct}%` }} /></div>
          <div className="pl-uso">
            {fmtNum(pl.uso_leads_mes)} de {fmtNum(cota)} leads neste mês
            <br />
            <span style={{ color: "var(--faint)" }}>renova em {fmtDate(pl.renova_em).slice(0, 5)}</span>
          </div>
        </>
      )}
    </div>
  );
}

function TrocarSenha({ onClose, onOk }: { onClose: () => void; onOk: () => void }) {
  const [erro, setErro] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="Trocar senha" onClose={onClose}>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
          if (f.new !== f.new2) return setErro("As senhas não coincidem.");
          setBusy(true);
          setErro("");
          try {
            await api("/auth/password", "POST", { current: f.current, new: f.new });
            onOk();
          } catch (err) {
            setErro(errMsg(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="caption" style={{ margin: 0 }}>Confirme a senha atual e defina a nova. As outras sessões abertas serão encerradas.</p>
        <label className="field">Senha atual<input className="input" name="current" type="password" autoComplete="current-password" required /></label>
        <label className="field">Nova senha (mín. 6)<input className="input" name="new" type="password" minLength={6} autoComplete="new-password" required /></label>
        <label className="field">Repita a nova senha<input className="input" name="new2" type="password" minLength={6} autoComplete="new-password" required /></label>
        {erro && <Note kind="err">{erro}</Note>}
        <div className="row">
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" disabled={busy}>Salvar nova senha</button>
        </div>
      </form>
    </Modal>
  );
}
