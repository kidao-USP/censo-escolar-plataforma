# CLAUDE.md – Plataforma de dados abertos do Censo Escolar

Projeto Integrador Univesp (PJI240, Grupo 1) para o OIPP/EACH-USP. Banco PostgreSQL + ETL + API
FastAPI + frontend nginx, em `docker compose`. Ver `README.md` para modelo de dados e endpoints.
Responder ao usuario em portugues.

## Onde roda
Servidor do OIPP: DNS `oipp.each.usp.br`. Servico PUBLICO (aberto na internet) com HTTPS via Caddy
(`SITE_ADDRESS` no `.env`). O repositorio e PUBLICO (exigencia da banca): nunca colocar IPs internos,
senhas, tokens ou chaves em arquivos versionados.
O codigo foi escrito e testado fora do servidor; este e o primeiro deploy real.

## Estado atual (leia antes de agir)
Validado: esquema SQL, ETL e API contra PostgreSQL 16 embutido com dados SINTETICOS
(`tests/validate_e2e.py`) e logica do ETL (`tests/test_etl.py`).

NAO validado (confirmar no servidor, nesta ordem):
1. `docker compose up -d --build` sobe `db`, `api`, `web` sem erro; `02_roles.sh` criou o usuario `censo_api`.
2. Extensoes `unaccent` e `pg_trgm` existem na imagem `postgres:17` (nos testes foram substituidas por stub).
3. Download do ZIP: a URL padrao (`CENSO_URL_TEMPLATE`) e uma suposicao. Se falhar, baixar o ZIP no site do
   Inep e salvar em `data/microdados_censo_escolar_<ano>.zip`.
4. Estrutura real do CSV do Inep (anos 2024 e 2025): o ETL assume uma linha por escola com colunas
   `QT_MAT_*`, `QT_DOC_*`, `QT_TUR_*` e os atributos listados em `etl/classify.py` (`ESCOLA_COLS`).
   O log do ETL imprime a contagem de colunas por grupo; se vier 0 ou o CSV for diferente, ajustar
   `etl/classify.py` (nao inventar colunas) e rodar `python -I tests/test_etl.py`.
5. Desempenho com o volume real (~200 mil escolas/ano): medir tempo do ETL e das consultas; criar indices
   apenas se houver necessidade comprovada.
6. Frontend nunca foi aberto contra a API real: testar no navegador (filtros, variaveis, tabela, CSV).
7. Endurecimento (nunca executado em Docker): conferir que o Caddy obtem o certificado e redireciona
   HTTP->HTTPS; que `web` e `api` sobem com `read_only` + `cap_drop: ALL` (se algum falhar por escrita
   em disco, ajustar `tmpfs`, sem remover o endurecimento); que o rate limit responde 429
   (ex.: `for i in $(seq 40); do curl -s -o /dev/null -w "%{http_code} " https://oipp.each.usp.br/api/anos; done`);
   que o nginx le o IP real do cliente (X-Forwarded-For); que a porta 5432 nao esta acessivel de fora;
   `docker compose config` valida o YAML e `nginx -t` (dentro do container web) valida a configuracao.
8. Host (Docker no Ubuntu) - conferir cada item do README, secao "Endurecimento do servidor", e
   relatar ao usuario o que esta OK e o que falta; nao alterar o host sem o usuario confirmar:
   - Docker ignora o UFW: `docker ps --format '{{.Names}} {{.Ports}}'` so pode mostrar 80/443 (caddy);
     `sudo ss -tlnp` e `sudo ufw status verbose`; de fora, 5432 deve estar fechada.
   - `/etc/docker/daemon.json` com rotacao de logs, `live-restore` e `no-new-privileges`
     (userns-remap/rootless e opcional: testar e, se quebrar a pilha, manter o padrao).
   - Grupo `docker` so com o administrador; nenhum container monta `docker.sock`.
   - SSH so por chave (`PasswordAuthentication no`, `PermitRootLogin no`); `unattended-upgrades` ativo.
   Decisao do usuario: ficar com Docker Compose (k3s/Podman nao trazem ganho de seguranca por si so).

## Regras
- Nunca commitar `.env`, ZIPs ou qualquer coisa de `data/`. Senhas so no `.env` do servidor.
- O PostgreSQL nao deve ser exposto na rede; a API usa o usuario somente leitura `censo_api`.
- Nao inventar resultados: o Relatorio Final do grupo so pode afirmar o que a plataforma realmente faz.
  Guarde evidencias (saida do ETL com contagens, tempos, exemplos de consultas, prints do frontend).
- Commits pequenos, em portugues; identidade git local: Rogerio M B Pascual <rmbp@usp.br>.

## Decisoes ja tomadas pelo usuario
- HTTPS obrigatorio. Acesso ABERTO ao publico (nao restringir a rede USP), por isso a camada de seguranca
  descrita no README ("Seguranca"). Repositorio publico para a correcao pela banca.

## Em aberto (perguntar ao usuario)
- Se a EACH/USP ja tiver proxy/certificado proprios, adaptar o `caddy/Caddyfile` (linha `tls`).
- Rotina de atualizacao: o ETL e manual (`docker compose run --rm etl`); automatizar so se o OIPP pedir.

## Ao terminar o deploy, registrar para o relatorio
Anos carregados e total de escolas por ano (`/api/anos`), tempo de carga, tamanho do banco,
3 consultas de exemplo com resultado, e prints do frontend.
