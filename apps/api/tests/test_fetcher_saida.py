"""O portão de saída do pipeline: SSRF e exaustão de memória.

    python tests/test_fetcher_saida.py      (a 2ª parte usa rede)

As URLs que o pipeline visita vêm de BUSCA NA WEB — quem escolhe o destino, no
fim, é um terceiro. Dois riscos vinham daí:

1. SSRF. ``homepage_url`` aceitava qualquer host, e o requests seguia
   redirecionamento sozinho: bastava um site de lead responder 302 para
   ``169.254.169.254`` e o servidor buscava o metadata da instância na nuvem.
   Agora cada salto passa por ``destino_publico``.
2. Memória. ``response.text`` trazia a resposta inteira, e o pipeline roda 20
   páginas em paralelo — um site grande derrubava o container. O corpo passou a
   ser lido com teto.

REGRA QUE NÃO PODE QUEBRAR: site legítimo continua funcionando, inclusive com
redirecionamento (http -> https é o caso mais comum de todos).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.CRITICAL)

from app.fetcher import _MAX_BYTES, destino_publico  # noqa: E402

# (url, deve ser permitida)
DESTINOS = [
    ("http://127.0.0.1:8501/", False),
    ("http://localhost/admin", False),
    ("http://169.254.169.254/latest/meta-data/", False),   # metadata da nuvem
    ("http://10.0.0.5/", False),
    ("http://192.168.1.1/", False),
    ("http://172.16.0.1/", False),
    ("http://[::1]/", False),
    ("file:///etc/passwd", False),
    ("gopher://x/", False),
    ("ftp://arquivos.com/", False),
    ("https://google.com/", True),
    ("https://uol.com.br/", True),
]


def main() -> int:
    falhas = []
    for url, permitida in DESTINOS:
        if destino_publico(url) != permitida:
            falhas.append(f"{url}: esperado permitido={permitida}")

    if _MAX_BYTES > 8 * 1024 * 1024:
        falhas.append(f"teto de download alto demais ({_MAX_BYTES} bytes)")

    # Site real, com redirecionamento http -> https: não pode ter quebrado.
    try:
        from app.fetcher import fetch_homepage
        r = fetch_homepage("http://uol.com.br", timeout=20)
        if not r.ok or not r.title:
            falhas.append(f"site legítimo falhou (ok={r.ok}, erro={r.error!r})")
    except Exception as e:  # noqa: BLE001
        falhas.append(f"site legítimo levantou exceção: {e}")

    if falhas:
        print(f"FALHOU — {len(falhas)}:")
        for f in falhas:
            print("  -", f)
        return 1
    print(f"OK — {len(DESTINOS)} destinos classificados, teto de download e site real com "
          "redirect funcionando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
