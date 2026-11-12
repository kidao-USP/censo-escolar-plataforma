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
docker compose run --rm etl # baixa e carrega os anos de CENSO_ANOS (padrao: 2023 2024)
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

Nunca versionar `.env`. Vulnerabilidades: nao abra *issue* publica; fale diretamente com os
mantenedores.

### Endurecimento do servidor (Docker no Ubuntu)

Configuracao do host, fora do repositorio:

1. **Portas e firewall.** O Docker publica portas direto no iptables e **ignora o UFW**. Por isso o
   `docker-compose.yml` publica somente 80 e 443 (servico `caddy`) e o banco nao tem porta. Nao
   adicione `ports:` a outros servicos. Confira com `docker ps --format '{{.Names}} {{.Ports}}'` e,
   de outra maquina, com `nmap <servidor>`: so devem responder 22, 80 e 443.
   **A porta 22 (OpenSSH) precisa continuar aberta**, senao voce perde o acesso ao servidor. O sshd roda
   no host (nao e container), entao quem o controla e o UFW. Libere a 22 **antes** de ativar o UFW:
   ```bash
   sudo ufw allow OpenSSH      # ou: sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 443/udp      # HTTP/3 do Caddy (opcional)
   sudo ufw enable             # so depois das regras acima
   sudo ufw status verbose
   ```
   Se o servidor ficar atras de firewall da USP/EACH, peca a liberacao de 22 (restrita aos IPs de
   administracao, se possivel), 80 e 443.
2. **Daemon do Docker** (`/etc/docker/daemon.json`, depois `sudo systemctl restart docker`):
   ```json
   {
     "log-driver": "local",
     "log-opts": { "max-size": "10m", "max-file": "5" },
     "live-restore": true,
     "no-new-privileges": true
   }
   ```
   Rotaciona logs (evita encher o disco) e nega elevacao de privilegios por padrao.
3. **Root do container nao e root do host (opcional, testar).** `"userns-remap": "default"` no mesmo
   arquivo, ou Docker *rootless*. Ressalvas: com `userns-remap` a pasta `./data` precisa ser gravavel
   pelo usuario remapeado; no modo rootless as portas 80/443 exigem
   `net.ipv4.ip_unprivileged_port_start=80`. Se quebrar a pilha, mantenha o daemon padrao: as demais
   medidas (containers sem privilegios, `cap_drop`, rede interna) ja reduzem o risco.
4. **Acesso ao Docker.** O grupo `docker` equivale a root: so o administrador nele
   (`getent group docker`). Nenhum container monta `/var/run/docker.sock` (o compose nao monta).
5. **SSH.** Apenas chave: `PasswordAuthentication no` e `PermitRootLogin no` em
   `/etc/ssh/sshd_config.d/`; considere `fail2ban`. Antes de aplicar, confirme que sua chave ja funciona
   e valide com `sudo sshd -t`; depois de `sudo systemctl reload ssh`, teste o login numa **segunda
   sessao** antes de fechar a atual. Nao feche a porta 22 nem troque a porta do SSH sem ter outro acesso
   (console do provedor/VM).
6. **Atualizacoes.** `unattended-upgrades` para o sistema operacional e, periodicamente,
   `docker compose pull && docker compose up -d --build` para atualizar as imagens base.

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
/api/matriculas?ano=2024&agrupar_por=municipio&uf=SP&rede=municipal
/api/matriculas?ano=2024&variaveis=QT_MAT_FUND*&agrupar_por=uf
/api/escolas?ano=2024&municipio=sao carlos&rede=municipal,estadual
```

Filtro `municipio`: aceita o codigo IBGE ou o nome. O **nome exato** (sem acento e sem diferenciar
maiusculas) tem prioridade: `municipio=sao carlos` devolve so Sao Carlos (SP), nao Sao Carlos do Ivai (PR).
Se nao existir municipio com esse nome (na UF filtrada, se houver), busca por parte do nome
(`municipio=carlos`). Para nomes que se repetem entre estados, informe tambem `uf` ou use o codigo IBGE.

Observacao: sem `variaveis`, usa-se o total da educacao basica (`QT_*_BAS`). Variaveis
sobrepostas (total e recortes do mesmo total) nao devem ser somadas (`somar=true`).

## Anos e limitacoes

* **Anos carregados:** 2023 (217.625 escolas) e 2024 (215.545 escolas). Os totais de matriculas da
  educacao basica (`QT_MAT_BAS`) conferem com os divulgados pelo Inep. Resultados da carga em
  `docs/evidencias_deploy.md`.
* **Dados agregados por escola:** o CSV do Inep (2023 e 2024) traz uma linha por escola com contagens
  (`QT_MAT_*`, `QT_DOC_*`, `QT_TUR_*`). Por isso `/api/matriculas`, `/api/docentes` e `/api/turmas`
  devolvem **contagens agregadas**; a plataforma nao guarda nem expoe registros individuais de
  alunos ou docentes.
* **2025 ainda nao esta carregado.** O pacote de microdados de 2025 deixou de trazer o CSV unico por
  escola e passou a trazer tabelas separadas (escola, matricula, docente, turma, gestor), possivelmente em
  nivel individual. Incluir esse ano exige um ETL proprio que agregue por escola antes de gravar,
  para manter o banco publico sem dados pessoais.
* **Download dos ZIPs:** o servidor do Inep nao envia o certificado intermediario e o download automatico
  do ETL e recusado (a verificacao TLS nao e desativada). Baixe o ZIP no navegador, no site do Inep, e salve
  em `data/microdados_censo_escolar_<ano>.zip`.

## Testes

```bash
python -I tests/test_etl.py   # logica do ETL (sem banco)
python tests/validate_e2e.py  # esquema + ETL + API contra um PostgreSQL embutido, com dados sinteticos
```
O segundo exige um venv descartavel (dependencias no topo do arquivo). Nele `unaccent` e
`pg_trgm` sao substituidos por um stub, pois nao existem no PostgreSQL embutido; na imagem
oficial `postgres:17` essas extensoes existem.
