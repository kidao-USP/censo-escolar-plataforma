"""Validacao ponta a ponta (schema + ETL + API) com PostgreSQL embutido e dados sinteticos.

Requisitos (venv descartavel): pip install pixeltable-pgserver "psycopg[binary]" psycopg_pool fastapi httpx pandas openpyxl requests
No PostgreSQL embutido nao existem unaccent/pg_trgm; o teste usa um stub de unaccent e ignora o indice trigram.
Executar: python tests/validate_e2e.py
"""
import io, os, re, subprocess, sys, zipfile, shutil
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import pixeltable_pgserver as pgserver
from openpyxl import Workbook

PROJ = Path(__file__).resolve().parent.parent
SP = Path(__import__("tempfile").gettempdir()) / "censo_e2e"
WORK = SP
if WORK.exists():
    shutil.rmtree(WORK, ignore_errors=True)
(WORK / "data").mkdir(parents=True)

# ----------------------------------------------------------- dados sinteticos
rng = np.random.default_rng(42)
MUN = {"SP": [(3548906, "São Carlos"), (3550308, "São Paulo")],
       "MG": [(3151800, "Poços de Caldas"), (3106200, "Belo Horizonte")],
       "RO": [(1100015, "Alta Floresta D'Oeste")]}


def gerar(ano, n=200, extra=False):
    linhas = []
    for i in range(n):
        uf = ["SP", "MG", "RO"][i % 3]
        cod, nome = MUN[uf][i % len(MUN[uf])]
        inf, fund = int(rng.integers(0, 80)), int(rng.integers(0, 300))
        if i % 17 == 0:
            inf = fund = 0
        linhas.append({
            "NU_ANO_CENSO": ano, "NO_REGIAO": "Sudeste", "CO_REGIAO": 3, "NO_UF": uf + "-nome",
            "SG_UF": uf, "CO_UF": 35, "NO_MUNICIPIO": nome, "CO_MUNICIPIO": cod,
            "NO_ENTIDADE": f"ESCOLA {i} Ação", "CO_ENTIDADE": 31000000 + i,
            "TP_DEPENDENCIA": 1 + i % 4, "TP_LOCALIZACAO": 1 + i % 2,
            "TP_LOCALIZACAO_DIFERENCIADA": 0, "TP_SITUACAO_FUNCIONAMENTO": 1,
            "IN_AGUA": 1,
            "QT_MAT_BAS": inf + fund if (inf + fund) else np.nan,
            "QT_MAT_INF": inf if inf else np.nan, "QT_MAT_FUND": fund,
            "QT_DOC_BAS": int(rng.integers(0, 40)), "QT_DOC_FUND": int(rng.integers(0, 30)),
            "QT_TUR_BAS": int(rng.integers(0, 15)),
        })
    df = pd.DataFrame(linhas)
    if extra:
        df["QT_MAT_NOVA"] = rng.integers(0, 5, len(df))
    return df


def dicionario_xlsx():
    wb = Workbook(); ws = wb.active
    ws.append(["Dicionário de variáveis – Censo Escolar"])
    ws.append(["Nº", "Nome da Variável", "Descrição", "Categoria"])
    ws.append([1, "QT_MAT_BAS", "Número de matrículas da educação básica", None])
    ws.append([2, "QT_MAT_FUND", "Número de matrículas do ensino fundamental", None])
    ws.append([3, "TP_DEPENDENCIA", "Dependência administrativa", "1 - Federal; 2 - Estadual"])
    b = io.BytesIO(); wb.save(b); return b.getvalue()


dfs = {2024: gerar(2024), 2025: gerar(2025, extra=True).iloc[:-5]}
for ano, df in dfs.items():
    buf = df.to_csv(sep=";", index=False)
    z = zipfile.ZipFile(WORK / "data" / f"microdados_censo_escolar_{ano}.zip", "w")
    z.writestr(f"microdados_censo_escolar_{ano}/dados/microdados_ed_basica_{ano}.csv",
               buf.encode("latin-1") if ano == 2024 else ("\ufeff" + buf).encode("utf-8"))
    z.writestr(f"microdados_censo_escolar_{ano}/anexos/ANEXO I - Dicionário de Dados.xlsx",
               dicionario_xlsx())
    z.writestr(f"microdados_censo_escolar_{ano}/leia-me/LEIA-ME.pdf", b"x")
    z.close()

# ------------------------------------------------------------------- Postgres
srv = pgserver.get_server(WORK / "pg", cleanup_mode="stop")
uri = srv.get_uri()
port = int(re.search(r":(\d+)/", uri).group(1))
print("Postgres temporario em porta", port)
adm = psycopg.connect(uri, autocommit=True)
adm.execute("CREATE DATABASE censo")
cdsn = f"postgresql://postgres:@127.0.0.1:{port}/censo"

schema = (PROJ / "db/init/01_schema.sql").read_text(encoding="utf-8")
# contrib (unaccent / pg_trgm) nao vem no Postgres embutido: stub so para este teste
schema = schema.replace("CREATE EXTENSION IF NOT EXISTS unaccent;", """
CREATE FUNCTION unaccent(text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT translate($1, 'áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ',
                         'aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN') $$;""")
schema = schema.replace("CREATE EXTENSION IF NOT EXISTS pg_trgm;", "")
schema = re.sub(r"CREATE INDEX escola_nome_trgm_idx[^;]*;", "", schema)
with psycopg.connect(cdsn, autocommit=True) as c:
    c.execute(schema)
    c.execute("CREATE ROLE censo_api LOGIN PASSWORD 'x'")
    c.execute("GRANT USAGE ON SCHEMA public TO censo_api")
    c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO censo_api")
print("Esquema aplicado")

# ------------------------------------------------------------------------ ETL
env = dict(os.environ, DB_HOST="127.0.0.1", DB_PORT=str(port), DB_NAME="censo",
           DB_USER="postgres", DB_PASSWORD="", DATA_DIR=str(WORK / "data"), PYTHONIOENCODING="utf-8")
def etl(*anos):
    r = subprocess.run([sys.executable, "load.py", "--anos", *map(str, anos), "--chunk", "70"],
                       cwd=PROJ / "etl", env=env, capture_output=True, text=True, encoding="utf-8")
    print(r.stdout[-1500:]); print(r.stderr[-3000:])
    assert r.returncode == 0, "ETL falhou"
etl(2024, 2025)
etl(2024)  # idempotencia

def q(sql, *p):
    with psycopg.connect(cdsn) as c:
        return c.execute(sql, p).fetchall()

# ----------------------------------------------------------- checagens de carga
assert q("select nu_ano_censo, linhas from ano_censo order by 1") == [(2024, 200), (2025, 195)]
assert q("select count(*) from escola")[0][0] == 200
assert q("select count(*) from escola_ano")[0][0] == 395
for ano, df in dfs.items():
    esperado = int((pd.to_numeric(df["QT_MAT_BAS"]).fillna(0) > 0).sum())
    obtido = q("select count(*) from matricula m join variavel v using(co_variavel) "
               "where nu_ano_censo=%s and no_variavel='QT_MAT_BAS'", ano)[0][0]
    assert obtido == esperado, (ano, obtido, esperado)
assert q("select descricao from variavel where no_variavel='QT_MAT_BAS'")[0][0].startswith("Número de matrículas")
assert q("select count(*) from variavel where no_variavel='QT_MAT_NOVA'")[0][0] == 1
assert q("select no_entidade from escola_ano where co_entidade=31000001 and nu_ano_censo=2024")[0][0] == "ESCOLA 1 Ação"
print("CARGA OK")

# -------------------------------------------------------------------------- API
os.environ.update(DB_HOST="127.0.0.1", DB_PORT=str(port), DB_NAME="censo", DB_USER="censo_api", DB_PASSWORD="x")
sys.path.insert(0, str(PROJ / "api"))
from fastapi.testclient import TestClient
from app.main import app

def esperado_total(df, col, **filtros):
    d = df.copy()
    for k, v in filtros.items():
        d = d[d[k].isin(v if isinstance(v, list) else [v])]
    return pd.to_numeric(d[col]).fillna(0)

with TestClient(app) as cl:
    assert cl.get("/api/health").json() == {"status": "ok"}
    anos = cl.get("/api/anos").json(); assert [a["ano"] for a in anos] == [2025, 2024]

    # matriculas por UF (padrao QT_MAT_BAS)
    r = cl.get("/api/matriculas", params={"ano": 2024}).json()
    got = {x["sg_uf"]: x["total"] for x in r["dados"]}
    exp = dfs[2024].assign(v=pd.to_numeric(dfs[2024]["QT_MAT_BAS"]).fillna(0)).groupby("SG_UF")["v"].sum().astype(int).to_dict()
    assert got == exp, (got, exp)

    # filtros: rede municipal + urbana + municipio com nome sem acento
    r = cl.get("/api/matriculas", params={"ano": 2025, "municipio": "sao carlos", "rede": "municipal",
                                          "localizacao": "urbana", "agrupar_por": "municipio"}).json()
    d = dfs[2025]; d = d[(d.CO_MUNICIPIO == 3548906) & (d.TP_DEPENDENCIA == 3) & (d.TP_LOCALIZACAO == 1)]
    exp = int(pd.to_numeric(d.QT_MAT_BAS).fillna(0).sum())
    assert len(r["dados"]) <= 1 and (r["dados"][0]["total"] if r["dados"] else 0) == exp, (r, exp)

    # prefixo + rede com rotulo
    r = cl.get("/api/matriculas", params={"ano": 2024, "variaveis": "QT_MAT_FUND*", "agrupar_por": "rede"}).json()
    exp = dfs[2024].groupby("TP_DEPENDENCIA")["QT_MAT_FUND"].sum().to_dict()
    assert {x["tp_dependencia"]: x["total"] for x in r["dados"]} == exp
    assert {x["tp_dependencia_rotulo"] for x in r["dados"]} == {"Federal", "Estadual", "Municipal", "Privada"}

    # varias variaveis: separadas e somadas
    r = cl.get("/api/matriculas", params={"ano": 2024, "variaveis": "QT_MAT_INF,QT_MAT_FUND", "agrupar_por": "total"}).json()
    assert {x["variavel"] for x in r["dados"]} == {"QT_MAT_INF", "QT_MAT_FUND"}
    r = cl.get("/api/matriculas", params={"ano": 2024, "variaveis": "QT_MAT_INF,QT_MAT_FUND", "agrupar_por": "total", "somar": "true"}).json()
    exp = int(pd.to_numeric(dfs[2024].QT_MAT_INF).fillna(0).sum() + dfs[2024].QT_MAT_FUND.sum())
    assert r["dados"][0]["total"] == exp and r["aviso"], r

    # docentes e turmas
    r = cl.get("/api/docentes", params={"ano": 2025, "agrupar_por": "uf,rede"}).json()
    assert sum(x["total"] for x in r["dados"]) == int(dfs[2025].QT_DOC_BAS.sum())
    r = cl.get("/api/turmas", params={"ano": 2025, "agrupar_por": "total"}).json()
    assert r["dados"][0]["total"] == int(dfs[2025].QT_TUR_BAS.sum())

    # agrupamento por escola e municipio
    assert cl.get("/api/matriculas", params={"ano": 2024, "agrupar_por": "escola", "limite": 5}).json()["quantidade"] == 5
    assert cl.get("/api/matriculas", params={"ano": 2024, "agrupar_por": "municipio"}).status_code == 200

    # escolas
    r = cl.get("/api/escolas", params={"ano": 2025, "uf": "SP,MG", "limite": 10}).json()
    assert r["total"] == int(dfs[2025].SG_UF.isin(["SP", "MG"]).sum()) and r["quantidade"] == 10
    r = cl.get("/api/escolas", params={"ano": 2024, "nome": "escola 17 "}).json()
    assert r["total"] == 1 and r["dados"][0]["tp_dependencia_rotulo"]
    csv = cl.get("/api/escolas", params={"ano": 2024, "uf": "RO", "formato": "csv"})
    assert csv.text.startswith("\ufeffano;co_entidade;") and "Alta Floresta D'Oeste" in csv.text
    csv = cl.get("/api/matriculas", params={"ano": 2024, "formato": "csv"})
    assert csv.headers["content-disposition"].endswith('matricula_2024.csv"'), csv.headers

    # metadados
    v = cl.get("/api/metadados/variaveis", params={"categoria": "matricula", "busca": "fundamental"}).json()
    assert [x["no_variavel"] for x in v] == ["QT_MAT_FUND"]
    assert len(cl.get("/api/metadados/variaveis").json()) == 7
    assert cl.get("/api/metadados/dominios").json()["tp_dependencia"][0] == {"codigo": 1, "rotulo": "Federal"}

    # erros esperados
    assert cl.get("/api/matriculas", params={"ano": 2020}).status_code == 404
    assert cl.get("/api/matriculas", params={"ano": 2024, "rede": "xyz"}).status_code == 422
    assert cl.get("/api/matriculas", params={"ano": 2024, "agrupar_por": "xyz"}).status_code == 422
    assert cl.get("/api/matriculas", params={"ano": 2024, "variaveis": "NAO_EXISTE"}).json()["dados"] == []
    # limites defensivos da API publica
    assert cl.get("/api/escolas", params={"ano": 2024, "limite": 20000}).status_code == 422
    assert cl.get("/api/escolas", params={"ano": 2024, "limite": 20000, "formato": "csv"}).status_code == 200
    assert cl.get("/api/escolas", params={"ano": 2024, "municipio": "x" * 101}).status_code == 422
    assert cl.get("/api/matriculas", params={"ano": 2024, "variaveis": ",".join(f"V{i}" for i in range(51))}).status_code == 422
    # injecao: valor malicioso e apenas dado
    assert cl.get("/api/escolas", params={"ano": 2024, "municipio": "x'; drop table escola;--"}).json()["total"] == 0
print("API OK")

# usuario da API e somente leitura
try:
    psycopg.connect(f"postgresql://censo_api:x@127.0.0.1:{port}/censo", autocommit=True).execute("DELETE FROM escola")
    raise SystemExit("ERRO: censo_api conseguiu escrever")
except psycopg.errors.InsufficientPrivilege:
    print("Somente leitura OK")
print("TUDO OK")
