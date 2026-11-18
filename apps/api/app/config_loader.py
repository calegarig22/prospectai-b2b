"""Carregamento e validação do arquivo de configuração.

Lê ``config/config.yaml`` e devolve um dicionário com valores padrão aplicados,
de modo que o restante do código nunca precise lidar com chaves ausentes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Caminho padrão do arquivo de configuração, relativo à raiz do projeto.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

# Valores padrão aplicados quando uma chave não está presente no YAML.
DEFAULTS: dict[str, Any] = {
    "search": {
        "max_results": 20,
        "region": "br-pt",
        "safesearch": "moderate",
        "pause_seconds": 2.0,
        "max_retries": 3,
    },
    "fetch": {
        "timeout_seconds": 10,
        "max_text_chars": 10000,
        "max_workers": 8,
        "user_agent": "Mozilla/5.0 (compatible; ProspectAI/1.0)",
    },
    "blacklist": ["wikipedia.org", "google.com", "facebook.com", "instagram.com",
                  "linkedin.com", "youtube.com", "x.com", "amazon.com", "mercadolivre.com.br"],
    "enrichment": {
        "max_workers": 6,
        "max_product_pages": 3,
        "web_contact_lookup": "all",
        "infer_role_email": False,
    },
    # Precisa existir AQUI: o _merge_defaults só repassa as chaves declaradas nos
    # padrões — sem esta seção, o bloco `outreach` do YAML seria descartado.
    "outreach": {
        "daily_limit": 10,
        "delay_min": 30,
        "delay_max": 90,
        "warmup": True,
        "validate_emails": True,
        "subject": "",
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
    },
}


def _merge_defaults(loaded: dict[str, Any]) -> dict[str, Any]:
    """Combina os valores carregados com os padrões (merge raso por seção)."""
    config: dict[str, Any] = {}
    for key, default_value in DEFAULTS.items():
        if isinstance(default_value, dict):
            section = {**default_value, **(loaded.get(key) or {})}
            config[key] = section
        else:
            config[key] = loaded.get(key, default_value)
    return config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Carrega a configuração do YAML, aplicando valores padrão.

    Levanta ``FileNotFoundError`` se o arquivo não existir e ``ValueError`` se
    nenhuma palavra-chave estiver configurada (não há o que prospectar).
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        raise ValueError("O arquivo de configuração deve conter um mapeamento YAML válido.")

    return _merge_defaults(loaded)
