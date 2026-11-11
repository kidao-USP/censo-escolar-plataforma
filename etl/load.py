"""ETL: baixa o ZIP de microdados do Censo Escolar (Inep) e carrega no PostgreSQL.

Uso (dentro do container):  python load.py --anos 2024 2025
A carga de cada ano e idempotente: dados anteriores do mesmo ano sao substituidos,
tudo dentro de uma unica transacao.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import psycopg
import requests

from classify import (
    ESCOLA_COLS, escolas_do_chunk, fatos_do_chunk, classificar_colunas,
    normalizar_colunas, validar_colunas,
)
from dicionario import escolher_dicionario, ler_dicionario

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
URL_TEMPLATE = os.environ.get(
    "CENSO_URL_TEMPLATE",
    "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip",
)
TABELA_FATO = {"matricula": "matricula", "docente": "docente", "turma": "turma"}
COLS_ESCOLA_ANO = ["nu_ano_censo", "co_entidade"] + [c.lower() for c in ESCOLA_COLS]
COLS_FATO = ["nu_ano_censo", "co_entidade", "co_variavel", "valor"]


def log(msg: str) -> None:
    print(f"[etl] {msg}", flush=True)


def conectar() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def obter_zip(ano: int) -> Path:
    destino = DATA_DIR / f"microdados_censo_escolar_{ano}.zip"
    if destino.exists():
        log(f"{ano}: usando ZIP ja existente {destino}")
        return destino
    url = URL_TEMPLATE.format(ano=ano)
    log(f"{ano}: baixando {url}")
    parcial = destino.with_suffix(".part")
    try:
        with requests.get(url, stream=True, timeout=60,
                          headers={"User-Agent": "Mozilla/5.0 (censo-escolar-etl)"}) as r:
            r.raise_for_status()
            with open(parcial, "wb") as f:
                for bloco in r.iter_content(1 << 20):
                    f.write(bloco)
    except requests.RequestException as exc:
        parcial.unlink(missing_ok=True)
        raise SystemExit(
            f"Falha ao baixar {url}: {exc}\n"
            f"Baixe o ZIP manualmente no site do Inep e salve em {destino}, depois rode de novo."
        )
    parcial.rename(destino)
    return destino


def localizar_arquivos(zf: zipfile.ZipFile) -> tuple[str, str | None]:
    csvs = [i for i in zf.infolist() if i.filename.lower().endswith(".csv")]
    if not csvs:
        raise SystemExit("Nenhum .csv encontrado dentro do ZIP.")
    preferidos = [i for i in csvs if "microdados_ed_basica" in i.filename.lower()]
    csv = max(preferidos or csvs, key=lambda i: i.file_size)
    dic = escolher_dicionario([(i.filename, i.file_size) for i in zf.infolist()])
    return csv.filename, dic


def detectar_encoding(zf: zipfile.ZipFile, nome: str) -> str:
    with zf.open(nome) as f:
        amostra = f.read(1 << 16)
    try:
        amostra.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as exc:
        # corte no meio de um caractere multibyte nao conta como erro
        if exc.start >= len(amostra) - 4:
            return "utf-8"
        return "latin-1"


def copiar(cur: psycopg.Cursor, tabela: str, colunas: list[str], df: pd.DataFrame) -> None:
    if df.empty:
        return
    csv = df[colunas].to_csv(index=False, header=False, na_rep="")
    with cur.copy(f"COPY {tabela} ({', '.join(colunas)}) FROM STDIN WITH (FORMAT csv)") as cp:
        cp.write(csv)


def preparar_variaveis(cur, categorias: dict[str, list[str]], dic: dict) -> dict[str, int]:
    for categoria, nomes in categorias.items():
        for nome in nomes:
            descricao, cats = dic.get(nome, (None, None))
            cur.execute(
                """INSERT INTO variavel (no_variavel, categoria, descricao, categorias)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (no_variavel) DO UPDATE SET
                     descricao = COALESCE(EXCLUDED.descricao, variavel.descricao),
                     categorias = COALESCE(EXCLUDED.categorias, variavel.categorias)""",
                (nome, categoria, descricao, cats),
            )
    cur.execute("SELECT no_variavel, co_variavel FROM variavel")
    return dict(cur.fetchall())


def carregar_ano(conn: psycopg.Connection, ano: int, caminho_zip: Path, chunk: int) -> None:
    inicio = time.time()
    with zipfile.ZipFile(caminho_zip) as zf:
        nome_csv, nome_dic = localizar_arquivos(zf)
        log(f"{ano}: CSV = {nome_csv} | dicionario = {nome_dic or 'nao encontrado'}")
        encoding = detectar_encoding(zf, nome_csv)

        dic: dict = {}
        if nome_dic:
            try:
                dic = ler_dicionario(zf.read(nome_dic))
                log(f"{ano}: dicionario com {len(dic)} variaveis lido")
            except Exception as exc:  # melhor esforco
                log(f"{ano}: AVISO - nao foi possivel ler o dicionario ({exc})")

        with zf.open(nome_csv) as f:
            cab = pd.read_csv(f, sep=";", encoding=encoding, dtype=str, nrows=0)
        colunas = normalizar_colunas(cab.columns)
        validar_colunas(colunas)
        categorias = classificar_colunas(colunas)
        log(f"{ano}: {len(colunas)} colunas; " + ", ".join(
            f"{k}={len(v)}" for k, v in categorias.items()))

        with conn.cursor() as cur:
            ids = preparar_variaveis(cur, categorias, dic)
            cur.execute("DELETE FROM escola_ano WHERE nu_ano_censo = %s", (ano,))  # cascata nos fatos
            cur.execute("DELETE FROM ano_censo WHERE nu_ano_censo = %s", (ano,))
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_escola "
                        "(co_entidade bigint, no_entidade text) ON COMMIT DROP")

            total = 0
            with zf.open(nome_csv) as f:
                for df in pd.read_csv(f, sep=";", encoding=encoding, dtype=str, chunksize=chunk):
                    df.columns = colunas
                    esc = escolas_do_chunk(df, ano)
                    esc = esc.drop_duplicates(subset=["co_entidade"])
                    esc["no_entidade"] = esc["no_entidade"].fillna("(sem nome)")
                    # 1) escola (dimensao estavel) via tabela temporaria
                    cur.execute("TRUNCATE stg_escola")
                    copiar(cur, "stg_escola", ["co_entidade", "no_entidade"], esc)
                    cur.execute(
                        """INSERT INTO escola (co_entidade, no_entidade, ultimo_ano)
                           SELECT co_entidade, no_entidade, %s FROM stg_escola
                           ON CONFLICT (co_entidade) DO UPDATE SET
                             no_entidade = EXCLUDED.no_entidade, ultimo_ano = EXCLUDED.ultimo_ano
                           WHERE escola.ultimo_ano <= EXCLUDED.ultimo_ano""",
                        (ano,),
                    )
                    # 2) atributos da escola no ano
                    copiar(cur, "escola_ano", COLS_ESCOLA_ANO, esc)
                    # 3) fatos quantitativos
                    validos = set(esc["co_entidade"].astype("int64"))
                    for categoria, tabela in TABELA_FATO.items():
                        fatos = fatos_do_chunk(df, ano, categorias[categoria], ids)
                        fatos = fatos[fatos["co_entidade"].isin(validos)]
                        copiar(cur, tabela, COLS_FATO, fatos)
                    total += len(esc)
                    log(f"{ano}: {total} escolas carregadas...")

            cur.execute(
                "INSERT INTO ano_censo (nu_ano_censo, arquivo, linhas) VALUES (%s, %s, %s)",
                (ano, nome_csv, total),
            )
    conn.commit()
    log(f"{ano}: concluido em {time.time() - inicio:.0f}s ({total} escolas)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anos", nargs="+", type=int,
                   default=[int(a) for a in os.environ.get("CENSO_ANOS", "2024 2025").split()])
    p.add_argument("--chunk", type=int, default=20000, help="linhas por lote")
    args = p.parse_args()

    for ano in args.anos:
        caminho = obter_zip(ano)
        with conectar() as conn:
            carregar_ano(conn, ano, caminho, args.chunk)
    with conectar() as conn:
        conn.autocommit = True
        for tabela in ("escola", "escola_ano", "matricula", "docente", "turma", "variavel"):
            conn.execute(f"ANALYZE {tabela}")
    log("ETL finalizado.")


if __name__ == "__main__":
    sys.exit(main())
