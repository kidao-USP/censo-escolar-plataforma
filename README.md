# Plataforma de dados abertos do Censo Escolar

Banco de dados local (PostgreSQL) + API (FastAPI) + frontend (nginx) para consulta aos
microdados do Censo Escolar (Inep), pensada para os pesquisadores do OIPP/EACH-USP.
Projeto Integrador Univesp (PJI240, Grupo 1).

```
Inep (ZIP/CSV) --> etl (Python) --> db (PostgreSQL) --> api (FastAPI) --> web (nginx)
```

## Subir no servidor

```bash
cp .env.example .env        # edite as duas senhas (somente letras e numeros)
docker compose up -d --build
docker compose run --rm etl # baixa e carrega os anos de CENSO_ANOS (padrao: 2024 2025)
```

Depois acesse `http://<servidor>:8080` (frontend) e `http://<servidor>:8080/docs` (Swagger da API).

* Se o download automatico do Inep falhar, baixe o ZIP de microdados de cada ano em
  <https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar>
  e salve como `data/microdados_censo_escolar_<ano>.zip`; rode o ETL de novo.
* O ETL e idempotente: rodar de novo substitui os dados do mesmo ano.
* O `docker-compose` nao expoe o PostgreSQL. Para consultar direto, use tunel SSH ou
  descomente a linha `ports` do servico `db`.
* Os scripts de `db/init` so rodam na primeira criacao do volume. Para recriar do zero:
  `docker compose down -v` (apaga os dados).

## Modelo de dados

| Tabela | Conteudo |
|---|---|
| `escola` | uma linha por escola (`CO_ENTIDADE`), nome mais recente |
| `escola_ano` | atributos da escola em cada ano: UF, municipio, rede (`TP_DEPENDENCIA`), localizacao etc. |
| `variavel` | metadados: nome da variavel `QT_*`, categoria e descricao do dicionario de dados do Inep |
| `matricula`, `docente`, `turma` | fatos em formato longo (ano, escola, variavel, valor) a partir de `QT_MAT_*`, `QT_DOC_*`, `QT_TUR_*`; so valores > 0 |
| `ano_censo` | controle das cargas |

Chaves primarias e estrangeiras ligam fatos -> `escola_ano` -> `escola` e fatos -> `variavel`.
Escolha do formato longo: as colunas `QT_*` mudam entre edicoes do Censo; assim novos anos
entram sem alterar o esquema. A API usa um usuario PostgreSQL somente leitura (`censo_api`).

## API

| Endpoint | Descricao |
|---|---|
| `GET /api/escolas` | lista escolas filtrando por `ano`, `uf`, `municipio`, `rede`, `localizacao`, `nome` |
| `GET /api/matriculas` | agrega `QT_MAT_*` (`variaveis`, `agrupar_por`, filtros) |
| `GET /api/docentes` | agrega `QT_DOC_*` |
| `GET /api/turmas` | agrega `QT_TUR_*` |
| `GET /api/anos`, `/api/metadados/variaveis`, `/api/metadados/dominios` | metadados |

`formato=csv` em qualquer consulta devolve CSV (separador `;`, UTF-8 com BOM, abre no Excel).
Exemplos:

```
/api/matriculas?ano=2025&agrupar_por=municipio&uf=SP&rede=municipal
/api/matriculas?ano=2025&variaveis=QT_MAT_FUND*&agrupar_por=uf
/api/escolas?ano=2025&municipio=sao carlos&rede=municipal,estadual
```

Observacao: sem `variaveis`, usa-se o total da educacao basica (`QT_*_BAS`). Variaveis
sobrepostas (total e recortes do mesmo total) nao devem ser somadas (`somar=true`).

## Testes

```bash
python -I tests/test_etl.py   # logica do ETL (sem banco)
python tests/validate_e2e.py  # esquema + ETL + API contra um PostgreSQL embutido, com dados sinteticos
```
O segundo exige um venv descartavel (dependencias no topo do arquivo). Nele `unaccent` e
`pg_trgm` sao substituidos por um stub, pois nao existem no PostgreSQL embutido; na imagem
oficial `postgres:17` essas extensoes existem.
