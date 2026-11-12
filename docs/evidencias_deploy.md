# Evidencias do primeiro deploy (11/11/2026)

Servidor do OIPP (Ubuntu 24.04.5 LTS, Docker 29.9.3, Compose v5.7.0), acesso publico em
`https://oipp.each.usp.br`. Tudo abaixo foi medido no servidor, com os microdados reais do Inep.

## Carga (ETL)

ZIPs baixados manualmente do site do Inep e salvos em `data/` (o download automatico falha porque
`download.inep.gov.br` nao envia o certificado intermediario da cadeia TLS; ver "Pendencias").

Comando: `docker compose run --rm -e CENSO_ANOS="2023 2024" etl`

```
[etl] 2023: usando ZIP ja existente /data/microdados_censo_escolar_2023.zip
[etl] 2023: CSV = microdados_censo_escolar_2023/dados/microdados_ed_basica_2023.csv | dicionario = microdados_censo_escolar_2023/Anexos/ANEXO I - Dicionário de Dados/dicionário_dados_educaç╞o_básica.xlsx
[etl] 2023: dicionario com 474 variaveis lido
[etl] 2023: 408 colunas; matricula=78, docente=16, turma=26
[etl] 2023: concluido em 191s (217625 escolas)
[etl] 2024: usando ZIP ja existente /data/microdados_censo_escolar_2024.zip
[etl] 2024: CSV = microdados_censo_escolar_2024_defeso/dados/microdados_ed_basica_2024.csv | dicionario = microdados_censo_escolar_2024_defeso/Anexos/ANEXO I - Dicionário de Dados/dicionário_dados_educação_básica.xlsx
[etl] 2024: dicionario com 492 variaveis lido
[etl] 2024: 426 colunas; matricula=78, docente=16, turma=26
[etl] 2024: concluido em 244s (215545 escolas)
[etl] ETL finalizado.
```
(linhas de progresso "N escolas carregadas..." omitidas)

| Ano | Escolas (`/api/anos`) | Tempo de carga | Linhas `matricula` | `docente` | `turma` |
|---|---:|---:|---:|---:|---:|
| 2023 | 217.625 | 191 s | 4.447.155 | 1.118.508 | 1.452.896 |
| 2024 | 215.545 | 244 s | 4.466.821 | 1.133.257 | 1.479.538 |

Tempo total do comando (inclui subir o container): 7 min 26 s.
Escolas com matricula na educacao basica > 0: 178.476 (2023) e 179.286 (2024); as demais linhas
sao escolas paralisadas/extintas, que o arquivo do Inep tambem traz.

Conferencia: soma de `QT_MAT_BAS` = 47.304.632 (2023) e 47.088.922 (2024), coerente com os
totais de matriculas da educacao basica divulgados pelo Inep para esses anos (47,3 mi e 47,1 mi).
As 120 variaveis carregadas (78 matricula, 16 docente, 26 turma) tem descricao vinda do dicionario.

## Banco

Tamanho total: **1.661 MB** (PostgreSQL 17.11).

| Tabela | Linhas | Tamanho (com indices) |
|---|---:|---:|
| matricula | 8.912.778 | 947 MB |
| turma | 2.932.273 | 312 MB |
| docente | 2.251.021 | 238 MB |
| escola_ano | 431.904 | 83 MB |
| escola | 222.589 | 73 MB |
| variavel | 120 | 120 kB |

## Consultas de exemplo (via HTTPS publico, tempo medido no servidor com curl)

1. Matriculas da rede municipal por municipio de SP, 2024 -
   `/api/matriculas?ano=2024&agrupar_por=municipio&uf=SP&rede=municipal` (645 municipios, 0,16 s)

   | Municipio | QT_MAT_BAS |
   |---|---:|
   | Sao Paulo | 710.175 |
   | Guarulhos | 95.315 |
   | Barueri | 76.589 |
   | Sao Bernardo do Campo | 70.452 |
   | Sao Jose dos Campos | 68.027 |

2. Docentes da educacao basica por rede, 2023 - `/api/docentes?ano=2023&agrupar_por=rede` (0,38 s)

   | Rede | QT_DOC_BAS |
   |---|---:|
   | Municipal | 1.448.837 |
   | Estadual | 804.447 |
   | Privada | 643.133 |
   | Federal | 38.141 |

   Observacao: `QT_DOC_*` conta docentes por escola; quem leciona em mais de uma escola e contado
   em cada uma (nao e o numero de pessoas distintas).

3. Matriculas por etapa em SP, 2023 x 2024 -
   `/api/matriculas?variaveis=QT_MAT_INF,QT_MAT_FUND,QT_MAT_MED&agrupar_por=uf&uf=SP&ano=<ano>` (0,35 s cada)

   | Variavel | 2023 | 2024 |
   |---|---:|---:|
   | QT_MAT_INF (infantil) | 2.309.017 | 2.289.004 |
   | QT_MAT_FUND (fundamental) | 5.343.271 | 5.329.100 |
   | QT_MAT_MED (medio) | 1.832.726 | 1.853.141 |

Outras verificadas: `/api/turmas?ano=2024&agrupar_por=localizacao` (1.903.558 urbanas, 320.496 rurais),
`/api/escolas?ano=2024&uf=SP&municipio=sao%20carlos&rede=municipal,estadual` (102 escolas; 100 por pagina),
`formato=csv` (separador `;`, BOM UTF-8). Erros: ano nao carregado -> 404 com anos disponiveis;
`agrupar_por` invalido -> 422.

## Filtro de municipio e lista `/api/municipios` (12/11/2026)

Atualizacao aplicada (commits 35a839b e 60cf065): `docker compose up -d --build api web`, sem reiniciar
`db` nem `caddy`; os quatro servicos no ar e logs sem erros.

O filtro `municipio` por nome agora casa o nome exato primeiro: "sao carlos" nao traz mais
"Sao Carlos do Ivai" (PR). Mas **existem dois municipios chamados exatamente "Sao Carlos"**: em SP
(codigo 3548906) e em SC (codigo 4216008). Por isso o nome sozinho soma os dois; para um so municipio
use `uf` ou o codigo IBGE. O frontend envia o codigo quando o usuario escolhe uma sugestao da lista.

| Consulta (`/api/escolas?ano=2024&rede=municipal&limite=1&...`) | `total` |
|---|---:|
| `municipio=sao carlos` (sem UF: SP + SC) | 73 |
| `municipio=sao carlos&uf=SP` | 63 |
| `municipio=sao carlos&uf=SC` | 10 |
| `municipio=3548906` (codigo, como o frontend envia) | 63 |

Antes da correcao, `municipio=sao carlos` dava 76 (os 73 + 3 escolas de Sao Carlos do Ivai/PR).

`/api/municipios?busca=sao%20carlos&ano=2024` -> 200, nesta ordem: Sao Carlos (SC), Sao Carlos (SP),
Sao Carlos do Ivai (PR). Os homonimos exatos vem antes, em ordem de UF.

Outras verificacoes: `/api/health` -> 200; `/` -> 200; `/nao-existe` -> 404.

Tempo de `/api/municipios?ano=2024` (5 execucoes de `curl -w '%{time_total}'` via HTTPS, sem indice novo):

| `busca` | itens | tempos (s) |
|---|---:|---|
| `sao` | 20 | 0,121 0,120 0,121 0,120 0,120 |
| `carlos` | 8 | 0,122 0,122 0,121 0,121 0,122 |
| `a` | - | 0,033 0,034 0,033 0,033 0,033 (422: `busca` exige ao menos 2 caracteres; nao consulta o banco) |

Todos abaixo de 0,5 s; nao foi preciso criar indice nem tabela de municipios.

## HTTPS e seguranca (verificado)

- Certificado Let's Encrypt para `oipp.each.usp.br` obtido automaticamente pelo Caddy (validade ate 09/02/2027); HTTP/2 e HTTP/3 anunciados.
- `http://` -> `308 Permanent Redirect` para `https://`.
- Cabecalhos: HSTS (1 ano), CSP restritiva, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`.
- Rate limit: 40 requisicoes seguidas a `/api/anos` -> as primeiras ~26 com 200, depois 429;
  exportacao CSV: 4 com 200, depois 429.
- `POST` -> 403. Logs do nginx registram o IP real do cliente (X-Forwarded-For).
- `api` e `web`: `read_only`, `cap_drop: ALL`, `no-new-privileges`, usuario sem privilegios; `api` sem
  acesso a internet (rede `backend` interna). `nginx -t` ok.
- Somente o `caddy` publica portas (80/443); 5432 nao escuta no host.
- Banco: usuario `censo_api` sem superusuario, `default_transaction_read_only=on`, `statement_timeout=30s`,
  limite de 20 conexoes; extensoes `unaccent` 1.1 e `pg_trgm` 1.6 instaladas.

## Endurecimento do host (12/11/2026)

Feito item a item, com confirmacao do responsavel, segunda sessao SSH aberta e porta 22 sempre liberada.

- **nginx**: frontend com `Cache-Control: no-cache` (verificado com `curl -sI`).
- **SSH** (`/etc/ssh/sshd_config.d/10-endurecimento.conf`, validado com `sshd -t` e `sshd -T`, aplicado
  com `systemctl reload ssh`): `PermitRootLogin prohibit-password` (root so por chave),
  `X11Forwarding no`, `MaxAuthTries 4`, `LoginGraceTime 30`. Porta 22 mantida. O login por senha
  continua ligado por decisao do responsavel (desliga-lo depende de autorizacao da instituicao).
  Chaves autorizadas revisadas: removidas uma chave repetida e uma chave sem uso (com backup fora do
  repositorio). Testado login novo por chave e por senha. `fail2ban` ativo na jail `sshd`.
- **Grupo `docker`**: so `root` (o usuario administrativo saiu do grupo; usa `sudo`). Nenhum container
  monta `docker.sock`. Pilha e site seguiram respondendo.
- **LXD**: nao instalado (so o pacote `lxd-installer`, que instala o snap sob demanda). O usuario
  administrativo saiu do grupo `lxd` (grupo vazio) e o `lxd-installer.socket` foi mascarado, para que
  ninguem sem root dispare a instalacao. O pacote foi mantido porque remove-lo removeria tambem o
  metapacote `ubuntu-server`.
- **UFW** ativo (v4 e v6): `deny` entrada, `allow` saida, `deny` roteado. Liberadas apenas
  22/tcp (SSH), 80/tcp e 443/tcp+udp (Caddy) e portas de servicos que ja estavam no host (nao listadas
  aqui). Removida uma regra antiga sem uso. Antes de ativar:
  levantamento com `ss -tlnp` (servicos locais so no loopback), conferencia de que os
  containers nao falam com portas do host, e uma "rede de seguranca" (`systemd-run` com `ufw disable`
  em 20 min), cancelada so depois dos testes externos.
  Observacao: portas publicadas pelo Docker passam pela cadeia FORWARD, nao pelo UFW; por isso so o
  `caddy` publica portas.
- **Validacao apos ativar o UFW**: site 200, `http://` -> 308, `/api/health` 200, `/api/anos` com 2023
  e 2024, `/api/municipios` 200, HTTP/3 anunciado; os 4 containers no ar; o `caddy` continua saindo para
  a internet (`wget --spider` no diretorio ACME do Let's Encrypt: ok); logs do `caddy` sem erros.
  De fora: SSH novo, site e API funcionando.
- Ja feito em 11/11: `/etc/docker/daemon.json` com logs `local` rotacionados, `live-restore` e
  `no-new-privileges`.

## Pendencias

- Download automatico: `download.inep.gov.br` envia so o certificado final (falta o intermediario
  "RNP ICPEdu GR46 OV TLS CA 2025"), e o ETL recusa a conexao. Por ora, ZIPs baixados manualmente.
- Prints do frontend (abrir no navegador e testar filtros, variaveis, tabela e CSV).
