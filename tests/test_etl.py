"""Testes da logica do ETL que nao dependem do banco.

Executar:  python -I tests/test_etl.py   (requer pandas e openpyxl)
"""
import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "etl"))
from classify import (  # noqa: E402
    classificar_colunas, escolas_do_chunk, fatos_do_chunk, normalizar_colunas, validar_colunas,
)
from dicionario import ler_dicionario  # noqa: E402

CSV = (
    "﻿NU_ANO_CENSO;NO_ENTIDADE;CO_ENTIDADE;SG_UF;CO_MUNICIPIO;NO_MUNICIPIO;TP_DEPENDENCIA;"
    "TP_LOCALIZACAO;QT_MAT_BAS;QT_MAT_FUND;QT_DOC_BAS;QT_TUR_BAS;IN_AGUA\n"
    "2024;ESCOLA A;11000001;RO;1100015;Alta Floresta;3;1;120;80;9;5;1\n"
    "2024;ESCOLA SÃO JOSÉ;11000002;RO;1100015;Alta Floresta;4;2;;0;3;;0\n"
)


def carregar():
    df = pd.read_csv(io.StringIO(CSV), sep=";", dtype=str)
    df.columns = normalizar_colunas(df.columns)
    return df


def test_colunas():
    df = carregar()
    assert df.columns[0] == "NU_ANO_CENSO"  # BOM removido
    validar_colunas(list(df.columns))
    cat = classificar_colunas(df.columns)
    assert cat == {"matricula": ["QT_MAT_BAS", "QT_MAT_FUND"],
                   "docente": ["QT_DOC_BAS"], "turma": ["QT_TUR_BAS"]}


def test_colunas_invalidas():
    try:
        validar_colunas(["A", "B"])
    except ValueError:
        return
    raise AssertionError("deveria falhar")


def test_escolas():
    esc = escolas_do_chunk(carregar(), 2024)
    assert list(esc["co_entidade"]) == [11000001, 11000002]
    assert list(esc["sg_uf"]) == ["RO", "RO"]
    assert list(esc["tp_dependencia"]) == [3, 4]
    assert esc["no_regiao"].isna().all()  # coluna ausente no CSV -> nula
    assert list(esc.columns)[:2] == ["nu_ano_censo", "co_entidade"]


def test_fatos():
    df = carregar()
    ids = {"QT_MAT_BAS": 1, "QT_MAT_FUND": 2}
    f = fatos_do_chunk(df, 2024, ["QT_MAT_BAS", "QT_MAT_FUND"], ids)
    # escola 2 tem vazio/0 -> nao gera linhas
    assert len(f) == 2
    assert sorted(zip(f["co_entidade"], f["co_variavel"], f["valor"])) == [
        (11000001, 1, 120), (11000001, 2, 80)]
    vazio = fatos_do_chunk(df, 2024, [], ids)
    assert vazio.empty


def test_dicionario():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Dicionário de dados – Censo Escolar 2024"])
    ws.append(["Nº", "Nome da Variável", "Descrição", "Categoria", "Tipo"])
    ws.append([1, "QT_MAT_BAS", "Número de matrículas da educação básica", None, "Num"])
    ws.append([2, "TP_DEPENDENCIA", "Dependência administrativa", "1 - Federal; 2 - Estadual", "Num"])
    buf = io.BytesIO()
    wb.save(buf)
    d = ler_dicionario(buf.getvalue())
    assert d["QT_MAT_BAS"] == ("Número de matrículas da educação básica", None)
    assert d["TP_DEPENDENCIA"][1] == "1 - Federal; 2 - Estadual"


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
