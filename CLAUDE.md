# CLAUDE.md – Plataforma de dados abertos do Censo Escolar

Projeto Integrador Univesp (PJI240, Grupo 1) para o OIPP/EACH-USP. Banco PostgreSQL + ETL + API
FastAPI + frontend nginx, em `docker compose`. Ver `README.md` para modelo de dados e endpoints.
Responder ao usuario em portugues.

## Onde roda
Servidor do OIPP: DNS `oipp.each.usp.br`. Servico PUBLICO (aberto na internet) com HTTPS via Caddy
(`SITE_ADDRESS` no `.env`). O repositorio e PUBLICO (exigencia da banca): nunca colocar IPs internos,
senhas, tokens ou chaves em arquivos versionados.
O codigo foi escrito e testado fora do servidor; este e o primeiro deploy real.

## Estado atual (leia antes de agir) - atualizado em 12/11/2026
Primeiro deploy FEITO no servidor (repo em `/oipp/censo-escolar-plataforma`). Evidencias para o
relatorio em `docs/evidencias_deploy.md`.

Validado no servidor (11/11/2026):
- Pilha sobe (`db`, `api`, `web`, `caddy`); `censo_api` criado; `unaccent` e `pg_trgm` existem no `postgres:17`.
- Carregados 2023 e 2024 (ZIPs baixados MANUALMENTE em `data/`). Por decisao do usuario, 2025 fica de
  fora por ora. O padrao no repositorio agora e `CENSO_ANOS=2023 2024`; confira o `.env` do servidor
  (se ainda disser `2024 2025`, trocar para `2023 2024`).
- CSV real bate com o esperado: matricula=78, docente=16, turma=26 colunas; totais `QT_MAT_BAS` coerentes
  com o Inep. ETL ~3-4 min/ano; consultas 0,04-0,5 s (sem indices extras: nao foi preciso).
- HTTPS (Let's Encrypt), HTTP->HTTPS 308, cabecalhos, rate limit 429, IP real nos logs, `read_only` +
  `cap_drop` em `web`/`api`, 5432 nao publicada, `nginx -t` ok. nginx devolve 404 para caminho inexistente.
- Host: `/etc/docker/daemon.json` aplicado (logs `local` com rotacao, `live-restore`, `no-new-privileges`).

Pendente:
0. Ano 2025: o ZIP do Inep nao tem `microdados_ed_basica_2025.csv`; traz `Tabela_Escola`, `Tabela_Matricula`,
   `Tabela_Docente`, `Tabela_Turma`, `Tabela_Gestor_Escolar` e `Tabela_Curso_Tecnico`, provavelmente em nivel
   individual. Antes de qualquer ETL: ler SO os cabecalhos (primeira linha) e contar linhas, sem imprimir
   registros. O ETL novo deve AGREGAR por escola e nunca gravar dados individuais no banco publico (LGPD).
   O usuario fornece o ZIP (nao esta no servidor).
1. Download automatico: `download.inep.gov.br` nao envia o certificado intermediario (RNP ICPEdu GR46 OV
   TLS CA 2025); o ETL recusa. NUNCA desativar a verificacao TLS. Opcao proposta: incluir o intermediario
   (com hash fixado) no bundle de CAs da imagem do ETL. Aguarda decisao do usuario.
2. Frontend: abrir no navegador e tirar prints (o usuario faz).
3. Host (12/11/2026; detalhes de IPs/usuarios so com o usuario, NAO neste arquivo publico):
   - Feito: `/etc/ssh/sshd_config.d/10-endurecimento.conf` (root so por chave, sem X11, MaxAuthTries 4,
     LoginGraceTime 30); chaves SSH do `oipp` revisadas (duplicada e antiga removidas); `oipp` fora dos
     grupos `docker` e `lxd`; `lxd-installer.socket` mascarado (pacote mantido: remove-lo removeria o
     `ubuntu-server`); `/etc/docker/daemon.json` aplicado; nginx com 404 e no-cache.
   - UFW ATIVO e testado de fora (12/11): 22, 80/443 tcp+udp e portas especificas do administrador; resto negado.
     Rede de seguranca cancelada apos os testes. Evidencias em `docs/evidencias_deploy.md`.
4. Host (Docker no Ubuntu) - referencia, README secao "Endurecimento do servidor";
   nao alterar o host sem o usuario confirmar:
   - Docker ignora o UFW: `docker ps --format '{{.Names}} {{.Ports}}'` so pode mostrar 80/443 (caddy);
     `sudo ss -tlnp` e `sudo ufw status verbose`; de fora, 5432 deve estar fechada.
   - A porta 22 (OpenSSH) DEVE continuar aberta (UFW: `allow OpenSSH` antes de `ufw enable`). Nunca ativar,
     recarregar ou alterar o UFW/sshd sem confirmar que a 22 esta liberada e sem o usuario ter outra sessao
     aberta; perder o SSH significa perder o servidor.
   - `/etc/docker/daemon.json` com rotacao de logs, `live-restore` e `no-new-privileges`
     (userns-remap/rootless e opcional: testar e, se quebrar a pilha, manter o padrao).
   - Grupo `docker` so com o administrador; nenhum container monta `docker.sock`.
   - SSH: `PermitRootLogin prohibit-password` (root so por chave, decisao do usuario) e `X11Forwarding no`; `unattended-upgrades` e `fail2ban` ativos.
     DECISAO DO USUARIO: o login por SENHA no SSH continua ligado (desativar depende de autorizacao da
     instituicao). NAO mudar `PasswordAuthentication` nem exigir chave sem pedido expresso dele.
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
