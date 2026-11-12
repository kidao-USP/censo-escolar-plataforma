"""API de consulta aos microdados do Censo Escolar (somente leitura)."""
from __future__ import annotations

import csv
import io
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROTULOS = {
    "tp_dependencia": {1: "Federal", 2: "Estadual", 3: "Municipal", 4: "Privada"},
    "tp_localizacao": {1: "Urbana", 2: "Rural"},
    "tp_situacao_funcionamento": {
        1: "Em atividade", 2: "Paralisada", 3: "Extinta (ano do Censo)",
        4: "Extinta em anos anteriores",
    },
}
ALIAS_REDE = {"federal": 1, "estadual": 2, "municipal": 3, "privada": 4}
ALIAS_LOCALIZACAO = {"urbana": 1, "rural": 2}
# Variavel "total da educacao basica" usada quando nenhuma variavel e pedida.
VARIAVEL_PADRAO = {"matricula": "QT_MAT_BAS", "docente": "QT_DOC_BAS", "turma": "QT_TUR_BAS"}
# Dimensoes de agrupamento -> (expressoes SQL, nomes das colunas de saida)
AGRUPAMENTOS = {
    "uf": ["e.sg_uf"],
    "municipio": ["e.sg_uf", "e.co_municipio", "e.no_municipio"],
    "rede": ["e.tp_dependencia"],
    "localizacao": ["e.tp_localizacao"],
    "escola": ["e.co_entidade", "e.no_entidade", "e.sg_uf", "e.no_municipio"],
}
LIMITE_MAXIMO = 100_000   # linhas por consulta em CSV
LIMITE_JSON = 10_000      # linhas por consulta em JSON
TAMANHO_MAX_TEXTO = 100   # caracteres por filtro de texto
MAX_VARIAVEIS = 50

pool: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = ConnectionPool(
        conninfo=(
            f"host={os.environ['DB_HOST']} port={os.environ.get('DB_PORT', '5432')} "
            f"dbname={os.environ['DB_NAME']} user={os.environ['DB_USER']} "
            f"password={os.environ['DB_PASSWORD']}"
        ),
        min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True,
    )
    yield
    pool.close()


app = FastAPI(
    title="API do Censo Escolar - OIPP/EACH-USP",
    description="Consulta aos microdados do Censo Escolar (Inep) carregados em base local. "
                "Somente leitura; dados publicos agregados por escola.",
    version="1.0.0", lifespan=lifespan,
)


@app.exception_handler(Exception)
async def erro_interno(request, exc):
    """Nao vaza detalhes internos (SQL, host, etc.) em respostas publicas."""
    import logging
    logging.getLogger("uvicorn.error").exception("Erro nao tratado em %s", request.url.path)
    return JSONResponse({"detail": "Erro interno ao processar a consulta."}, status_code=500)


# ---------------------------------------------------------------- utilitarios
def consultar(sql: str, params: list) -> list[dict]:
    assert pool is not None
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def parse_codigos(valor: Optional[str], alias: dict[str, int], campo: str) -> list[int]:
    if not valor:
        return []
    saida = []
    for parte in valor.split(","):
        parte = parte.strip().lower()
        if not parte:
            continue
        if parte.isdigit():
            saida.append(int(parte))
        elif parte in alias:
            saida.append(alias[parte])
        else:
            raise HTTPException(422, f"Valor invalido para '{campo}': {parte!r}. "
                                     f"Use codigos ou: {', '.join(alias)}")
    return saida


def validar_ano(ano: int) -> None:
    if not consultar("SELECT 1 FROM ano_censo WHERE nu_ano_censo = %s", [ano]):
        anos = [r["nu_ano_censo"] for r in consultar("SELECT nu_ano_censo FROM ano_censo ORDER BY 1", [])]
        raise HTTPException(404, f"Ano {ano} nao carregado. Anos disponiveis: {anos}")


def checar_entrada(limite: int, formato: str, **textos: Optional[str]) -> None:
    """Limites defensivos para a API publica (tamanho de texto e de resposta)."""
    if formato == "json" and limite > LIMITE_JSON:
        raise HTTPException(422, f"limite maximo em JSON e {LIMITE_JSON}; use formato=csv para ate {LIMITE_MAXIMO}")
    for nome, valor in textos.items():
        if valor and len(valor) > (TAMANHO_MAX_TEXTO if nome != "variaveis" else 1000):
            raise HTTPException(422, f"parametro '{nome}' muito longo")


def escapar_like(texto: str) -> str:
    """Escapa curingas do LIKE: '%' e '_' digitados pelo usuario valem como texto comum."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def existe_municipio_exato(ano: int, ufs: list[str], nome: str) -> bool:
    """Ha municipio com exatamente este nome (sem acento, sem diferenciar maiusculas)?

    Considera o ano e, se informadas, as UFs do filtro."""
    sql = ("SELECT 1 FROM escola_ano e WHERE e.nu_ano_censo = %s "
           "AND lower(unaccent(e.no_municipio)) = lower(unaccent(%s))")
    params: list = [ano, nome]
    if ufs:
        sql += " AND e.sg_uf = ANY(%s::text[])"
        params.append(ufs)
    return bool(consultar(sql + " LIMIT 1", params))


def filtros_escola(ano, uf, municipio, rede, localizacao, situacao) -> tuple[list[str], list]:
    where, params = ["e.nu_ano_censo = %s"], [ano]
    ufs: list[str] = []
    if uf:
        ufs = [u.strip().upper() for u in uf.split(",") if u.strip()]
        where.append("e.sg_uf = ANY(%s::text[])")
        params.append(ufs)
    if municipio and municipio.strip():
        municipio = municipio.strip()
        if municipio.isdigit():
            where.append("e.co_municipio = %s")
            params.append(int(municipio))
        elif existe_municipio_exato(ano, ufs, municipio):
            # "Sao Carlos" nao deve trazer "Sao Carlos do Ivai": nome exato tem prioridade
            where.append("lower(unaccent(e.no_municipio)) = lower(unaccent(%s))")
            params.append(municipio)
        else:
            # sem nome exato, busca por parte do nome
            where.append("unaccent(e.no_municipio) ILIKE unaccent(%s)")
            params.append(f"%{escapar_like(municipio)}%")
    for coluna, valor, alias, campo in (
        ("e.tp_dependencia", rede, ALIAS_REDE, "rede"),
        ("e.tp_localizacao", localizacao, ALIAS_LOCALIZACAO, "localizacao"),
    ):
        codigos = parse_codigos(valor, alias, campo)
        if codigos:
            where.append(f"{coluna} = ANY(%s::int[])")
            params.append(codigos)
    if situacao:
        where.append("e.tp_situacao_funcionamento = ANY(%s::int[])")
        params.append(parse_codigos(situacao, {}, "situacao"))
    return where, params


def rotular(linhas: list[dict]) -> list[dict]:
    for linha in linhas:
        for campo, mapa in ROTULOS.items():
            if campo in linha and linha[campo] is not None:
                linha[campo + "_rotulo"] = mapa.get(linha[campo])
    return linhas


def resposta(linhas: list[dict], formato: str, nome_arquivo: str, extra: dict | None = None):
    linhas = rotular(linhas)
    if formato == "csv":
        buf = io.StringIO()
        if linhas:
            w = csv.DictWriter(buf, fieldnames=list(linhas[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(linhas)
        # BOM para o Excel abrir com acentos corretos
        return Response(
            content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}.csv"'},
        )
    corpo = {"quantidade": len(linhas), "dados": linhas}
    if extra:
        corpo.update(extra)
    return corpo


# ------------------------------------------------------------------ endpoints
@app.get("/api/health", tags=["sistema"])
def health():
    consultar("SELECT 1", [])
    return {"status": "ok"}


@app.get("/api/anos", tags=["metadados"])
def anos():
    """Anos do Censo Escolar carregados na base."""
    return consultar("SELECT nu_ano_censo AS ano, arquivo, linhas AS escolas, carregado_em "
                     "FROM ano_censo ORDER BY nu_ano_censo DESC", [])


@app.get("/api/metadados/variaveis", tags=["metadados"])
def metadados_variaveis(
    categoria: Optional[str] = Query(None, pattern="^(matricula|docente|turma)$"),
    busca: Optional[str] = Query(None, description="Texto no nome ou na descricao"),
):
    """Variaveis quantitativas disponiveis, com a descricao do dicionario de dados do Inep."""
    where, params = ["TRUE"], []
    if categoria:
        where.append("categoria = %s")
        params.append(categoria)
    if busca:
        where.append("(no_variavel ILIKE %s OR unaccent(coalesce(descricao,'')) ILIKE unaccent(%s))")
        params += [f"%{busca}%", f"%{busca}%"]
    return consultar(
        "SELECT no_variavel, categoria, descricao, categorias FROM variavel "
        f"WHERE {' AND '.join(where)} ORDER BY categoria, no_variavel", params)


@app.get("/api/metadados/dominios", tags=["metadados"])
def metadados_dominios():
    """Codigos e rotulos dos filtros categoricos."""
    return {campo: [{"codigo": k, "rotulo": v} for k, v in mapa.items()]
            for campo, mapa in ROTULOS.items()}


@app.get("/api/escolas", tags=["consultas"])
def escolas(
    ano: int = Query(..., description="Ano do Censo Escolar"),
    uf: Optional[str] = Query(None, description="Sigla(s) separadas por virgula, ex.: SP,MG"),
    municipio: Optional[str] = Query(None, description="Codigo IBGE ou nome. Nome exato (sem acento, sem diferenciar maiusculas) tem prioridade; "
                                                           "se nao existir, busca por parte do nome"),
    rede: Optional[str] = Query(None, description="federal, estadual, municipal, privada (ou codigos 1-4)"),
    localizacao: Optional[str] = Query(None, description="urbana, rural (ou 1-2)"),
    situacao: Optional[str] = Query(None, description="codigos de TP_SITUACAO_FUNCIONAMENTO"),
    nome: Optional[str] = Query(None, description="Parte do nome da escola"),
    limite: int = Query(100, ge=1, le=LIMITE_MAXIMO),
    deslocamento: int = Query(0, ge=0),
    formato: str = Query("json", pattern="^(json|csv)$"),
):
    """Listagem e metadados das escolas filtradas por UF, municipio, rede etc."""
    checar_entrada(limite, formato, uf=uf, municipio=municipio, rede=rede,
                   localizacao=localizacao, situacao=situacao, nome=nome)
    validar_ano(ano)
    where, params = filtros_escola(ano, uf, municipio, rede, localizacao, situacao)
    if nome:
        where.append("lower(e.no_entidade) LIKE lower(%s)")
        params.append(f"%{nome}%")
    cond = " AND ".join(where)
    total = consultar(f"SELECT count(*) AS n FROM escola_ano e WHERE {cond}", params)[0]["n"]
    linhas = consultar(
        f"""SELECT e.nu_ano_censo AS ano, e.co_entidade, e.no_entidade, e.sg_uf, e.no_uf,
                   e.co_municipio, e.no_municipio, e.tp_dependencia, e.tp_localizacao,
                   e.tp_localizacao_diferenciada, e.tp_situacao_funcionamento,
                   e.tp_categoria_escola_privada
            FROM escola_ano e WHERE {cond}
            ORDER BY e.sg_uf, e.no_municipio, e.no_entidade
            LIMIT %s OFFSET %s""", params + [limite, deslocamento])
    return resposta(linhas, formato, f"escolas_{ano}",
                    {"total": total, "limite": limite, "deslocamento": deslocamento})


def agregado(categoria: str, tabela: str, ano, uf, municipio, rede, localizacao, situacao,
             variaveis, agrupar_por, somar, limite, formato):
    checar_entrada(limite, formato, uf=uf, municipio=municipio, rede=rede, localizacao=localizacao,
                   situacao=situacao, variaveis=variaveis, agrupar_por=agrupar_por)
    validar_ano(ano)
    dims = []
    for d in (agrupar_por or "").split(","):
        d = d.strip().lower()
        if not d or d == "total":
            continue
        if d not in AGRUPAMENTOS:
            raise HTTPException(422, f"agrupar_por invalido: {d!r}. Use: {', '.join(AGRUPAMENTOS)}")
        dims.append(d)
    colunas_grupo: list[str] = []
    for d in dims:
        for c in AGRUPAMENTOS[d]:
            if c not in colunas_grupo:
                colunas_grupo.append(c)

    where, params = filtros_escola(ano, uf, municipio, rede, localizacao, situacao)
    where.append("v.categoria = %s")
    params.append(categoria)

    pedidas = [v.strip().upper() for v in (variaveis or VARIAVEL_PADRAO[categoria]).split(",") if v.strip()]
    if len(pedidas) > MAX_VARIAVEIS:
        raise HTTPException(422, f"no maximo {MAX_VARIAVEIS} variaveis por consulta")
    exatas = [v for v in pedidas if not v.endswith("*")]
    prefixos = [v[:-1] + "%" for v in pedidas if v.endswith("*")]
    where.append("(v.no_variavel = ANY(%s::text[]) OR v.no_variavel LIKE ANY(%s::text[]))")
    params += [exatas, prefixos]

    selecao = [f"{c} AS {c.split('.')[1]}" for c in colunas_grupo]
    grupo = list(colunas_grupo)
    if not somar:
        selecao.append("v.no_variavel AS variavel")
        grupo.append("v.no_variavel")
    sql = f"""SELECT {', '.join(selecao + ['SUM(f.valor)::bigint AS total'])}
              FROM {tabela} f
              JOIN escola_ano e ON e.nu_ano_censo = f.nu_ano_censo AND e.co_entidade = f.co_entidade
              JOIN variavel v ON v.co_variavel = f.co_variavel
              WHERE {' AND '.join(where)}
              {('GROUP BY ' + ', '.join(grupo)) if grupo else ''}
              ORDER BY total DESC
              LIMIT %s"""
    linhas = consultar(sql, params + [limite])
    aviso = ("Com 'somar=true' e varias variaveis sobrepostas (ex.: total e recortes do mesmo total) "
             "os valores serao contados em duplicidade." if somar and len(pedidas) > 1 else None)
    return resposta(linhas, formato, f"{tabela}_{ano}", {"ano": ano, "aviso": aviso})


@app.get("/api/matriculas", tags=["consultas"])
def matriculas(
    ano: int = Query(..., description="Ano do Censo Escolar"),
    uf: Optional[str] = None, municipio: Optional[str] = None, rede: Optional[str] = None,
    localizacao: Optional[str] = None, situacao: Optional[str] = None,
    variaveis: Optional[str] = Query(None, description="Nomes QT_MAT_* separados por virgula; aceita 'QT_MAT_FUND*'. Padrao: QT_MAT_BAS"),
    agrupar_por: Optional[str] = Query("uf", description="uf, municipio, rede, localizacao, escola (separados por virgula) ou total"),
    somar: bool = Query(False, description="Soma todas as variaveis pedidas em uma so coluna"),
    limite: int = Query(1000, ge=1, le=LIMITE_MAXIMO),
    formato: str = Query("json", pattern="^(json|csv)$"),
):
    """Agrega quantidades de matriculas (QT_MAT_*) aplicando filtros por UF, municipio, rede e localizacao."""
    return agregado("matricula", "matricula", ano, uf, municipio, rede, localizacao, situacao,
                    variaveis, agrupar_por, somar, limite, formato)


@app.get("/api/docentes", tags=["consultas"])
def docentes(
    ano: int = Query(..., description="Ano do Censo Escolar"),
    uf: Optional[str] = None, municipio: Optional[str] = None, rede: Optional[str] = None,
    localizacao: Optional[str] = None, situacao: Optional[str] = None,
    variaveis: Optional[str] = Query(None, description="Nomes QT_DOC_* separados por virgula; aceita 'QT_DOC_FUND*'. Padrao: QT_DOC_BAS"),
    agrupar_por: Optional[str] = Query("uf", description="uf, municipio, rede, localizacao, escola ou vazio"),
    somar: bool = False,
    limite: int = Query(1000, ge=1, le=LIMITE_MAXIMO),
    formato: str = Query("json", pattern="^(json|csv)$"),
):
    """Indicadores do corpo docente (QT_DOC_*) agregados por territorio, rede ou escola."""
    return agregado("docente", "docente", ano, uf, municipio, rede, localizacao, situacao,
                    variaveis, agrupar_por, somar, limite, formato)


@app.get("/api/turmas", tags=["consultas"])
def turmas(
    ano: int = Query(..., description="Ano do Censo Escolar"),
    uf: Optional[str] = None, municipio: Optional[str] = None, rede: Optional[str] = None,
    localizacao: Optional[str] = None, situacao: Optional[str] = None,
    variaveis: Optional[str] = Query(None, description="Nomes QT_TUR_* separados por virgula; aceita 'QT_TUR_FUND*'. Padrao: QT_TUR_BAS"),
    agrupar_por: Optional[str] = Query("uf", description="uf, municipio, rede, localizacao, escola ou vazio"),
    somar: bool = False,
    limite: int = Query(1000, ge=1, le=LIMITE_MAXIMO),
    formato: str = Query("json", pattern="^(json|csv)$"),
):
    """Quantidade de turmas (QT_TUR_*) agregada por territorio, rede ou escola."""
    return agregado("turma", "turma", ano, uf, municipio, rede, localizacao, situacao,
                    variaveis, agrupar_por, somar, limite, formato)
