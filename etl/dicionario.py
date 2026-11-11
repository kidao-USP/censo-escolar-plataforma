"""Leitura (melhor esforco) do dicionario de dados .xlsx do Inep.

O layout do dicionario varia entre edicoes; por isso procuramos, em cada aba,
a linha de cabecalho que contem "nome" e "descri" e extraimos nome, descricao
e (se houver) a coluna de categorias. Qualquer falha aqui NAO interrompe a carga:
as variaveis ficam apenas sem descricao.
"""
from __future__ import annotations

import io
import unicodedata

from openpyxl import load_workbook


def _norm(texto) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).strip().lower()


def escolher_dicionario(arquivos: list[tuple[str, int]]) -> str | None:
    """Escolhe o .xlsx do dicionario entre (caminho, tamanho) dos arquivos do ZIP.

    Ignora arquivos de bloqueio do Excel (nome comecando com "~$"), que o Inep
    as vezes deixa dentro do ZIP; havendo mais de um candidato, fica com o maior.
    """
    candidatos = [
        (nome, tam) for nome, tam in arquivos
        if nome.lower().endswith(".xlsx")
        and not nome.rsplit("/", 1)[-1].startswith("~$")
        and "dicion" in _norm(nome)
    ]
    return max(candidatos, key=lambda c: c[1])[0] if candidatos else None


def ler_dicionario(conteudo: bytes) -> dict[str, tuple[str | None, str | None]]:
    """Retorna {NOME_VARIAVEL: (descricao, categorias)}."""
    resultado: dict[str, tuple[str | None, str | None]] = {}
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    for ws in wb.worksheets:
        cab = None
        i_nome = i_desc = i_cat = None
        for linha in ws.iter_rows(values_only=True):
            if cab is None:
                celulas = [_norm(c) for c in linha]
                nome = next((i for i, c in enumerate(celulas) if c.startswith("nome")), None)
                desc = next((i for i, c in enumerate(celulas) if c.startswith("descri")), None)
                if nome is not None and desc is not None:
                    cab = True
                    i_nome, i_desc = nome, desc
                    i_cat = next(
                        (i for i, c in enumerate(celulas) if c.startswith("categoria")), None
                    )
                continue
            if i_nome is None or i_nome >= len(linha) or not linha[i_nome]:
                continue
            nome_var = str(linha[i_nome]).strip().upper()
            descricao = linha[i_desc] if i_desc < len(linha) else None
            categorias = linha[i_cat] if i_cat is not None and i_cat < len(linha) else None
            resultado[nome_var] = (
                str(descricao).strip() if descricao else None,
                str(categorias).strip() if categorias else None,
            )
    return resultado
