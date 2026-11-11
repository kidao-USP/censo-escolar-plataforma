# Plataforma de dados abertos do Censo Escolar

Banco de dados local (PostgreSQL) + API (FastAPI) + frontend (nginx) para consulta aos
microdados do Censo Escolar (Inep), pensada para os pesquisadores do OIPP/EACH-USP.
Projeto Integrador Univesp (PJI240, Grupo 1).

```
Inep (ZIP/CSV) --> etl (Python) --> db (PostgreSQL) --> api (FastAPI) --> web (nginx) --> caddy (HTTPS) --> internet
```

## Subir no servidor

```bash
cp .env.example .env        # gere senhas fortes (openssl rand -hex 24) e confira SITE_ADDRESS
docker compose up -d --build
docker compose run --rm etl # baixa e carrega os anos de CENSO_ANOS (padrao: 2024 2025)
```

Depois acesse `https://oipp.each.usp.br` (frontend) e `https://oipp.each.usp.br/docs` (Swagger da API).
Para testar localmente use `SITE_ADDRESS=localhost` (certificado local; o navegador pede confirmacao).

* O HTTPS e automatico (Caddy + Let's Encrypt): o DNS deve apontar para o servidor e as portas
  80 e 443 devem estar acessiveis da internet. Se a EACH/USP fornecer um certificado proprio,
  descomente a linha `tls` em `caddy/Caddyfile` e monte os arquivos (`volumes` do servico `caddy`).
* Se o download automatico do Inep falhar, baixe o ZIP de microdados de cada ano em
  <https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar>
  e salve como `data/microdados_censo_escolar_<ano>.zip`; rode o ETL de novo.
* O ETL e idempotente: rodar de novo substitui os dados do mesmo ano.
* O PostgreSQL nao e publicado em nenhuma porta. Para consultar direto:
  `docker compose exec db psql -U censo_admin censo`.
* Os scripts de `db/init` so rodam na primeira criacao do volume. Para recriar do zero:
  `docker compose down -v` (apaga os dados).

## Seguranca (acesso publico)

Os dados sao publicos e agregados por escola (sem dados pessoais), mas o servico fica aberto na
internet, entao ha defesa em camadas:

| Camada | Medida |
|---|---|
| Transporte | HTTPS obrigatorio, redirecionamento HTTP->HTTPS e HSTS (Caddy) |
| Rede | `db` e `api` em rede Docker interna, sem acesso a internet; so 80/443 publicados; o ETL e o unico com saida |
| Borda (nginx) | apenas GET/HEAD; limite de taxa por IP (5 req/s; exportacao CSV 6/min); limite de conexoes; CSP restritiva e demais cabecalhos de seguranca |
| API | somente leitura; parametros validados e com tamanho maximo; consultas por parametros (sem SQL montado a partir da entrada); limite de 10.000 linhas em JSON e 100.000 em CSV; erros internos sem detalhes |
| Banco | usuario da API sem escrita (`default_transaction_read_only`), `statement_timeout` de 30 s e limite de 20 conexoes; autenticacao SCRAM |
| Containers | usuario sem privilegios, sistema de arquivos somente leitura, `cap_drop: ALL`, `no-new-privileges`; dependencias Python com versao fixa e imagens com tag de versao |

No servidor (fora do repositorio): manter firewall liberando apenas 22, 80 e 443, SSH por chave, e
atualizacoes de seguranca do sistema. Nunca versionar `.env`. Vulnerabilidades: nao abra *issue*
publica; fale diretamente com os mantenedores.

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
