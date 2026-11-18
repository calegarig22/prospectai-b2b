"""O e-mail de login passa pelo MESMO validador do disparo.

    python tests/test_email_cadastro.py     (usa rede: consulta DNS via HTTPS)

Antes bastava conter "@": "a@" era aceito. Um login que não recebe e-mail é um
usuário que não consegue redefinir a própria senha.

Descoberto junto: ``dnspython`` nunca esteve no requirements, então a checagem
de MX devolvia "incerto" para tudo — em silêncio. Valia para o DISPARO também,
que mandava e-mail para domínio inexistente e colhia bounce. A resolução passou
a usar DNS sobre HTTPS (mesma técnica do pipeline, sem lib nova).

REGRA QUE NÃO PODE QUEBRAR: na dúvida, ACEITA. Rede instável não pode impedir
um cadastro legítimo — só se recusa com resposta clara do DNS.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("DATABASE_URL", None)

from app.users import _valida_email  # noqa: E402

# (e-mail, deve ser aceito, o que o caso representa)
CASOS = [
    ("fulano@gmail.com", True, "endereço real"),
    ("fulano.de.tal@gmail.com", True, "real com ponto no nome"),
    ("a@", False, "domínio ausente — o furo antigo"),
    ("semarroba.com", False, "sem @"),
    ("@dominio.com", False, "sem parte local"),
    ("com espaco@gmail.com", False, "espaço no endereço"),
    ("noreply@gmail.com", False, "caixa técnica: não recebe contato"),
    ("teste@dominio-que-nao-existe-xyz123abc.com.br", False, "domínio inexistente"),
    ("nome@empresa.local", False, "domínio interno: reset de senha não chegaria"),
]


def main() -> int:
    falhas = []
    for email, aceita, desc in CASOS:
        veio, _ = _valida_email(email)
        if veio != aceita:
            falhas.append(f"{email} ({desc}): esperado aceito={aceita}, veio {veio}")

    # A regra de ouro: incerteza NÃO recusa.
    from app.email_validate import _mx_cache, check
    _mx_cache["dominio-incerto-teste.com"] = None
    ok, _ = check("alguem@dominio-incerto-teste.com")
    if not ok:
        falhas.append("recusou endereço com DNS incerto — rede instável barraria cadastro bom")

    if falhas:
        print(f"FALHOU — {len(falhas)}:")
        for f in falhas:
            print("  -", f)
        return 1
    print(f"OK — {len(CASOS) + 1} verificações do e-mail de cadastro passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
