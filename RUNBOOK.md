# Runbook – Plataforma de dados abertos do Censo Escolar

Guia de operacao da plataforma do Projeto Integrador Univesp (PJI240, Grupo 1) para o OIPP/EACH-USP:
banco PostgreSQL + ETL + API FastAPI + frontend nginx + HTTPS (Caddy), em `docker compose`.
Modelo de dados, endpoints e testes estao no `README.md`; as evidencias de deploy, em
`docs/evidencias_deploy.md`. Ultima atualizacao: 12/11/2026.

## 1. Onde roda

- Servidor do OIPP, DNS `oipp.each.usp.br`. Servico **publico** (aberto na internet), com HTTPS via
  Caddy (`SITE_ADDRESS` no `.env`).
- Repositorio no servidor: `/oipp/censo-escolar-plataforma`.
- Repositorio no GitHub: **publico** (exigencia da banca). Veja as regras abaixo.

## 2. Regras de ouro

1. **Nada sensivel no repositorio.** Nunca versionar IPs internos, senhas, tokens, chaves, `.env`, ZIPs
   nem nada de `data/`. As senhas ficam so no `.env` do servidor.
2. **A porta 22 (OpenSSH) precisa continuar aberta.** Nao ative, recarregue nem altere o UFW ou o sshd
   sem confirmar que a 22 esta liberada e sem ter outra sessao aberta. Perder o SSH e perder o servidor.
3. **Nunca desativar a verificacao TLS** (por exemplo, no download do Inep).
4. **O PostgreSQL nao e exposto na rede.** A API usa o usuario somente leitura `censo_api`.
5. **Nao adicionar `ports:` a outros servicos do compose.** O Docker publica portas direto no iptables
   e ignora o UFW; so o `caddy` publica 80 e 443.
6. **Nao alterar o host** (SSH, UFW, Docker daemon) sem o responsavel pelo projeto confirmar.
7. **Nao inventar resultados.** O relatorio so pode afirmar o que a plataforma realmente faz;
   registre evidencias (saida do ETL, tempos, consultas de exemplo, prints).

## 3. Estado atual

Validado no servidor em 11/11/2026 e 12/11/2026:

- Pilha no ar (`db`, `api`, `web`, `caddy`); usuario `censo_api` criado; extensoes `unaccent` e
  `pg_trgm` disponiveis no `postgres:17`.
- **Anos carregados: 2023 e 2024** (217.625 e 215.545 escolas; soma de `QT_MAT_BAS` de 47,30 e 47,09
  milhoes, coerente com o Inep). Banco com cerca de 1,6 GB. ETL de ~3 a 4 min por ano.
- CSV real confere com o esperado: 78 variaveis de matricula, 16 de docente e 26 de turma.
- Consultas de 0,04 a 0,5 s, sem indices extras. Busca de municipios (`/api/municipios`) em ~0,12 s.
- HTTPS com Let's Encrypt, redirecionamento HTTP->HTTPS (308), cabecalhos de seguranca, limite de
  requisicoes (429), IP real nos logs, `read_only` + `cap_drop` em `web` e `api`, 5432 nao publicada.
- nginx devolve 404 para caminho inexistente e `Cache-Control: no-cache` no frontend.
- Host: `/etc/docker/daemon.json` aplicado; SSH endurecido; usuario administrador fora do grupo
  `docker`; UFW ativo (secao 5).

## 4. Procedimentos

### 4.1 Deploy inicial

```bash
cp .env.example .env        # gere senhas fortes (openssl rand -hex 24) e confira SITE_ADDRESS
docker compose up -d --build
docker compose run --rm etl # carrega os anos de CENSO_ANOS (padrao: 2023 2024)
```

O DNS deve apontar para o servidor e as portas 80 e 443 devem estar acessiveis da internet (Let's
Encrypt). Para teste local, `SITE_ADDRESS=localhost`.

### 4.2 Atualizar o codigo no servidor

```bash
cd /oipp/censo-escolar-plataforma
git pull
docker compose up -d --build api web   # ou apenas o servico que mudou
docker compose ps
```

Depois de mudar `api/` ou `web/`, recrie so esses servicos. Os scripts de `db/init` rodam apenas na
primeira criacao do volume.

### 4.3 Carregar ou recarregar um ano

1. Confira `CENSO_ANOS` no `.env` do servidor (deve ser `2023 2024`).
2. O download automatico do Inep falha (o servidor do Inep nao envia o certificado intermediario).
   Baixe o ZIP de cada ano no navegador, em
   <https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar>, envie-o
   ao servidor e salve como `data/microdados_censo_escolar_<ano>.zip`.
3. `docker compose run --rm etl`. O ETL e idempotente: rodar de novo substitui os dados do mesmo ano.

### 4.4 Verificacao apos mudancas

```bash
docker compose ps
docker ps --format '{{.Names}} {{.Ports}}'   # so o caddy deve mostrar 80/443
curl -s https://oipp.each.usp.br/api/anos     # anos e total de escolas
sudo ss -tlnp
sudo ufw status verbose
```

De outra maquina, a 5432 deve estar fechada (`nmap <servidor>`).

### 4.5 Consultar o banco direto

```bash
docker compose exec db psql -U censo_admin censo
```

### 4.6 Recriar do zero

`docker compose down -v` **apaga os dados**; depois, repita a secao 4.1 e recarregue os anos.

### 4.7 Registrar evidencias para o relatorio

Anos carregados e total de escolas por ano (`/api/anos`), tempo de carga, tamanho do banco, consultas
de exemplo com resultado e prints do frontend. Guarde em `docs/evidencias_deploy.md`.

## 5. Host (Ubuntu com Docker)

Detalhes de IPs e usuarios ficam so com o responsavel pelo projeto, **nao neste arquivo publico**.
Procedimentos genericos estao no `README.md` (secao "Endurecimento do servidor").

- **SSH:** `/etc/ssh/sshd_config.d/10-endurecimento.conf` (root so por chave, sem X11, `MaxAuthTries 4`);
  `fail2ban` e `unattended-upgrades` ativos. **Decisao do grupo: o login por senha continua ligado**
  (desativar depende de autorizacao da instituicao). Nao mudar `PasswordAuthentication` nem exigir
  chave sem pedido expresso. Antes de aplicar mudancas: `sudo sshd -t` e, apos o reload, testar o login
  numa **segunda sessao** antes de fechar a atual.
- **UFW:** ativo e validado em 12/11/2026, sem temporizador de seguranca. Libera 22 e 80/443 (tcp e udp),
  alem de portas especificas do administrador que nao sao listadas neste arquivo publico; o resto e
  negado. Libere a 22 **antes** de `ufw enable`. Confirme com `ufw status verbose` e teste de fora (SSH
  numa nova sessao e site) depois de qualquer mudanca.
- **LXD:** nao instalado (so o pacote `lxd-installer`). O usuario administrador esta fora do grupo `lxd`
  e o `lxd-installer.socket` esta mascarado; o pacote foi mantido porque remove-lo removeria o
  metapacote `ubuntu-server`. As chaves SSH autorizadas foram revisadas (duplicada e antiga removidas).
- **Docker daemon:** `/etc/docker/daemon.json` com logs `local` rotacionados, `live-restore` e
  `no-new-privileges`. `userns-remap` ou rootless e opcional: teste e, se quebrar a pilha, mantenha o
  padrao.
- **Grupo `docker`:** equivale a root; so o administrador. Nenhum container monta `docker.sock`.
- **Atualizacoes:** `docker compose pull && docker compose up -d --build` periodicamente, para as
  imagens base.

## 6. Decisoes ja tomadas

- HTTPS obrigatorio. Acesso **aberto ao publico** (nao restringir a rede da USP), por isso a camada de
  seguranca do `README.md`.
- Repositorio publico, para a correcao pela banca.
- Ficar com **Docker Compose** (k3s e Podman nao trazem ganho de seguranca por si so).
- Anos **2023 e 2024** apenas; 2025 fica como limitacao documentada.
- Login por senha no SSH continua ligado (secao 5).
- O HSTS do site (`includeSubDomains`) nao deve ser removido.

## 7. Pendencias

1. **Ano 2025.** O ZIP do Inep nao tem `microdados_ed_basica_2025.csv`; traz `Tabela_Escola`,
   `Tabela_Matricula`, `Tabela_Docente`, `Tabela_Turma`, `Tabela_Gestor_Escolar` e
   `Tabela_Curso_Tecnico`, provavelmente em nivel individual. Antes de qualquer ETL, ler **so os
   cabecalhos** (primeira linha) e contar linhas, sem imprimir registros. O ETL novo deve **agregar por
   escola** e nunca gravar dados individuais no banco publico (LGPD). O ZIP nao esta no servidor.
2. **Download automatico do Inep.** `download.inep.gov.br` nao envia o certificado intermediario
   (RNP ICPEdu GR46 OV TLS CA 2025) e o ETL recusa a conexao. Opcao: incluir o intermediario, com hash
   fixado, no bundle de CAs da imagem do ETL. Aguarda decisao.

## 8. Em aberto (perguntar ao responsavel)

- Se a EACH/USP tiver proxy ou certificado proprios, adaptar a linha `tls` do `caddy/Caddyfile`.
- Rotina de atualizacao: o ETL e manual (`docker compose run --rm etl`); automatizar so se o OIPP pedir.

## 9. Convencoes

- Commits pequenos, em portugues.
- Identidade git local: Rogerio M B Pascual <rmbp@usp.br>.
- Vulnerabilidades: nao abrir *issue* publica; falar diretamente com os mantenedores.
