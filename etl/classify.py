"""Funcoes puras (sem banco) para interpretar o CSV de microdados do Censo Escolar.

O arquivo do Inep tem uma linha por escola e centenas de colunas. As colunas
sao separadas em:
  * atributos da escola (ESCOLA_COLS)     -> tabelas escola / escola_ano
  * QT_MAT_*  (matriculas)                -> tabela matricula (formato longo)
  * QT_DOC_*  (docentes)                  -> tabela docente   (formato longo)
  * QT_TUR_*  (turmas)                    -> tabela turma     (formato longo)
As demais colunas (IN_*, TP_* de infraestrutura etc.) ficam fora do escopo atual.
"""
from __future__ import annotations

import pandas as pd

# Colunas descritivas da escola, na ordem da tabela escola_ano (apos ano e entidade).
ESCOLA_COLS = [
    "NO_ENTIDADE",
    "CO_REGIAO", "NO_REGIAO",
    "CO_UF", "SG_UF", "NO_UF",
    "CO_MUNICIPIO", "NO_MUNICIPIO",
    "TP_DEPENDENCIA", "TP_LOCALIZACAO", "TP_LOCALIZACAO_DIFERENCIADA",
    "TP_SITUACAO_FUNCIONAMENTO", "TP_CATEGORIA_ESCOLA_PRIVADA",
]
INT_COLS = {
    "CO_REGIAO", "CO_UF", "CO_MUNICIPIO", "TP_DEPENDENCIA", "TP_LOCALIZACAO",
    "TP_LOCALIZACAO_DIFERENCIADA", "TP_SITUACAO_FUNCIONAMENTO",
    "TP_CATEGORIA_ESCOLA_PRIVADA",
}
PREFIXOS = {"QT_MAT_": "matricula", "QT_DOC_": "docente", "QT_TUR_": "turma"}
OBRIGATORIAS = ["NU_ANO_CENSO", "CO_ENTIDADE", "NO_ENTIDADE"]


def normalizar_colunas(colunas) -> list[str]:
    """Maiusculas, sem BOM e sem espacos nas pontas."""
    # "ï»¿" e o BOM UTF-8 lido como latin-1
    return [str(c).replace("﻿", "").replace("ï»¿", "").strip().upper() for c in colunas]


def classificar_colunas(colunas) -> dict[str, list[str]]:
    """Agrupa as colunas quantitativas por categoria."""
    out: dict[str, list[str]] = {"matricula": [], "docente": [], "turma": []}
    for c in colunas:
        for prefixo, categoria in PREFIXOS.items():
            if c.startswith(prefixo):
                out[categoria].append(c)
    return out


def validar_colunas(colunas) -> None:
    faltando = [c for c in OBRIGATORIAS if c not in colunas]
    if faltando:
        raise ValueError(
            f"CSV nao parece ser o microdado do Censo Escolar; colunas ausentes: {faltando}"
        )


def escolas_do_chunk(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """DataFrame no formato da tabela escola_ano (colunas ausentes viram nulas)."""
    out = pd.DataFrame({
        "nu_ano_censo": ano,
        "co_entidade": pd.to_numeric(df["CO_ENTIDADE"], errors="coerce").astype("Int64"),
    })
    for col in ESCOLA_COLS:
        if col in df.columns:
            serie = df[col]
            if col in INT_COLS:
                serie = pd.to_numeric(serie, errors="coerce").astype("Int64")
            else:
                serie = serie.str.strip()
        else:
            serie = pd.Series([pd.NA] * len(df), index=df.index)
        out[col.lower()] = serie
    return out.dropna(subset=["co_entidade"])


def fatos_do_chunk(
    df: pd.DataFrame, ano: int, colunas: list[str], ids: dict[str, int]
) -> pd.DataFrame:
    """Converte colunas QT_* de uma categoria para o formato longo.

    Mantem apenas valores > 0. Retorna colunas
    nu_ano_censo, co_entidade, co_variavel, valor.
    """
    vazio = pd.DataFrame(columns=["nu_ano_censo", "co_entidade", "co_variavel", "valor"])
    colunas = [c for c in colunas if c in df.columns]
    if not colunas:
        return vazio
    base = df[["CO_ENTIDADE"] + colunas].copy()
    base["CO_ENTIDADE"] = pd.to_numeric(base["CO_ENTIDADE"], errors="coerce")
    base = base.dropna(subset=["CO_ENTIDADE"])
    longo = base.melt(id_vars="CO_ENTIDADE", var_name="no_variavel", value_name="valor")
    longo["valor"] = pd.to_numeric(longo["valor"], errors="coerce")
    longo = longo[longo["valor"] > 0]
    if longo.empty:
        return vazio
    return pd.DataFrame({
        "nu_ano_censo": ano,
        "co_entidade": longo["CO_ENTIDADE"].astype("int64"),
        "co_variavel": longo["no_variavel"].map(ids).astype("int64"),
        "valor": longo["valor"].round().astype("int64"),
    })
