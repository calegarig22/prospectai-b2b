"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errMsg } from "@/lib/api";
import { Note } from "@/components/Modal";

type Modo = "carregando" | "login" | "bootstrap" | "bloqueado" | "reset1" | "reset2" | "reset3";

export default function LoginPage() {
  const [modo, setModo] = useState<Modo>("carregando");
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const router = useRouter();

  useEffect(() => {
    api<{ needs_bootstrap: boolean; bootstrap_enabled: boolean }>("/auth/status")
      .then((s) => {
        if (new URLSearchParams(window.location.search).get("expirou")) {
          setAviso("Sua sessão expirou. Entre novamente.");
        }
        setModo(s.needs_bootstrap ? (s.bootstrap_enabled ? "bootstrap" : "bloqueado") : "login");
      })
      .catch((e) => {
        setErro(errMsg(e));
        setModo("login");
      });
  }, []);

  async function enviar(fn: () => Promise<void>) {
    setErro("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setErro(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  function campos(form: HTMLFormElement) {
    return Object.fromEntries(new FormData(form)) as Record<string, string>;
  }

  const entrar = () => {
    router.replace("/");
    router.refresh();
  };

  return (
    <main className="auth">
      <div className="card">
        <div className="auth-mark"><div className="mark">P</div></div>
        {aviso && <div style={{ marginBottom: 12 }}><Note>{aviso}</Note></div>}

        {modo === "carregando" && <p className="caption">Carregando…</p>}

        {modo === "bloqueado" && (
          <>
            <p className="card-title">Acesso bloqueado</p>
            <p className="card-desc">Defina <code>APP_PASSWORD</code> no servidor para criar o primeiro acesso.</p>
          </>
        )}

        {modo === "login" && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = campos(e.currentTarget);
              enviar(async () => {
                await api("/auth/login", "POST", { email: f.email, password: f.password });
                entrar();
              });
            }}
          >
            <div>
              <p className="card-title">Entrar</p>
              <p className="card-desc" style={{ margin: 0 }}>Acesse com seu e-mail e senha.</p>
            </div>
            <label className="field">E-mail<input className="input" name="email" type="email" autoComplete="username" required /></label>
            <label className="field">Senha<input className="input" name="password" type="password" autoComplete="current-password" required /></label>
            {erro && <Note kind="err">{erro}</Note>}
            <button className="btn primary block" disabled={busy}>Entrar</button>
            <button type="button" className="btn block" onClick={() => { setErro(""); setAviso(""); setModo("reset1"); }}>
              Esqueci minha senha
            </button>
          </form>
        )}

        {modo === "bootstrap" && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = campos(e.currentTarget);
              if (f.password !== f.password2) return setErro("As senhas não coincidem.");
              enviar(async () => {
                await api("/auth/bootstrap", "POST", {
                  app_password: f.app_password, name: f.name, email: f.email, password: f.password,
                });
                entrar();
              });
            }}
          >
            <div>
              <p className="card-title">Criar o acesso do dono da plataforma</p>
              <p className="card-desc" style={{ margin: 0 }}>Ainda não há usuários. Informe a senha do time (APP_PASSWORD) para criar a conta de quem administra a plataforma e as empresas clientes.</p>
            </div>
            <label className="field">Senha do time<input className="input" name="app_password" type="password" required /></label>
            <label className="field">Seu nome<input className="input" name="name" required /></label>
            <label className="field">E-mail de login<input className="input" name="email" type="email" required /></label>
            <label className="field">Senha (mín. 6)<input className="input" name="password" type="password" minLength={6} autoComplete="new-password" required /></label>
            <label className="field">Repita a senha<input className="input" name="password2" type="password" minLength={6} autoComplete="new-password" required /></label>
            {erro && <Note kind="err">{erro}</Note>}
            <button className="btn primary block" disabled={busy}>Criar acesso</button>
          </form>
        )}

        {modo === "reset1" && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = campos(e.currentTarget);
              enviar(async () => {
                const r = await api<{ detail: string }>("/auth/reset/start", "POST", { email: f.email });
                setEmail(f.email);
                setAviso(r.detail);
                setModo("reset2");
              });
            }}
          >
            <div>
              <p className="card-title">Redefinir senha</p>
              <p className="card-desc" style={{ margin: 0 }}>Passo 1 de 3 — informe seu e-mail e enviaremos um código.</p>
            </div>
            <label className="field">Seu e-mail de login<input className="input" name="email" type="email" required /></label>
            {erro && <Note kind="err">{erro}</Note>}
            <button className="btn primary block" disabled={busy}>Enviar código</button>
            <button type="button" className="btn block" onClick={() => { setErro(""); setModo("login"); }}>Voltar ao login</button>
          </form>
        )}

        {modo === "reset2" && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = campos(e.currentTarget);
              enviar(async () => {
                await api("/auth/reset/verify", "POST", { email, code: f.code.trim() });
                setCode(f.code.trim());
                setAviso("");
                setModo("reset3");
              });
            }}
          >
            <div>
              <p className="card-title">Digite o código</p>
              <p className="card-desc" style={{ margin: 0 }}>Passo 2 de 3 — se <b>{email}</b> estiver cadastrado, o código chegou por e-mail.</p>
            </div>
            <label className="field">Código de 6 dígitos<input className="input" name="code" inputMode="numeric" pattern="\d{6}" maxLength={6} autoComplete="one-time-code" required /></label>
            {erro && <Note kind="err">{erro}</Note>}
            <button className="btn primary block" disabled={busy}>Continuar</button>
            <div className="row">
              <button type="button" className="btn" disabled={busy} onClick={() => enviar(async () => {
                const r = await api<{ detail: string }>("/auth/reset/start", "POST", { email });
                setAviso(r.detail);
              })}>Reenviar código</button>
              <button type="button" className="btn" onClick={() => { setErro(""); setModo("reset1"); }}>Voltar</button>
            </div>
          </form>
        )}

        {modo === "reset3" && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = campos(e.currentTarget);
              if (f.password !== f.password2) return setErro("As senhas não conferem.");
              enviar(async () => {
                await api("/auth/reset/confirm", "POST", { email, code, password: f.password });
                setAviso("Senha redefinida! Entre com a nova senha.");
                setModo("login");
              });
            }}
          >
            <div>
              <p className="card-title">Crie a nova senha</p>
              <p className="card-desc" style={{ margin: 0 }}>Passo 3 de 3 — defina sua nova senha de acesso.</p>
            </div>
            <label className="field">Nova senha (mín. 6)<input className="input" name="password" type="password" minLength={6} autoComplete="new-password" required /></label>
            <label className="field">Repita a nova senha<input className="input" name="password2" type="password" minLength={6} autoComplete="new-password" required /></label>
            {erro && <Note kind="err">{erro}</Note>}
            <button className="btn primary block" disabled={busy}>Salvar nova senha</button>
          </form>
        )}
      </div>
    </main>
  );
}
