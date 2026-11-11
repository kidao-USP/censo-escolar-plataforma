-- Esquema da plataforma de dados abertos do Censo Escolar (Inep).
-- Executado automaticamente na primeira inicializacao do volume do PostgreSQL.

CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Controle das cargas realizadas -------------------------------------------
CREATE TABLE ano_censo (
    nu_ano_censo  smallint    PRIMARY KEY,
    arquivo       text        NOT NULL,
    linhas        integer     NOT NULL,
    carregado_em  timestamptz NOT NULL DEFAULT now()
);

-- Metadados: uma linha por variavel quantitativa do dicionario do Inep ------
-- categoria: matricula (QT_MAT_*), docente (QT_DOC_*) ou turma (QT_TUR_*).
CREATE TABLE variavel (
    co_variavel  serial PRIMARY KEY,
    no_variavel  text   NOT NULL UNIQUE,
    categoria    text   NOT NULL CHECK (categoria IN ('matricula', 'docente', 'turma')),
    descricao    text,       -- descricao conforme dicionario de dados do Inep
    categorias   text        -- valores/categorias informados no dicionario
);
CREATE INDEX variavel_categoria_idx ON variavel (categoria);

-- Entidade escola (identificador estavel: CO_ENTIDADE) ----------------------
CREATE TABLE escola (
    co_entidade  bigint   PRIMARY KEY,
    no_entidade  text     NOT NULL,   -- nome mais recente
    ultimo_ano   smallint NOT NULL
);
CREATE INDEX escola_nome_trgm_idx ON escola USING gin (lower(no_entidade) gin_trgm_ops);

-- Atributos da escola em cada ano do Censo ---------------------------------
CREATE TABLE escola_ano (
    nu_ano_censo                smallint NOT NULL,
    co_entidade                 bigint   NOT NULL REFERENCES escola (co_entidade),
    no_entidade                 text     NOT NULL,
    co_regiao                   smallint,
    no_regiao                   text,
    co_uf                       smallint,
    sg_uf                       char(2),
    no_uf                       text,
    co_municipio                integer,
    no_municipio                text,
    tp_dependencia              smallint,  -- 1 Federal, 2 Estadual, 3 Municipal, 4 Privada
    tp_localizacao              smallint,  -- 1 Urbana, 2 Rural
    tp_localizacao_diferenciada smallint,
    tp_situacao_funcionamento   smallint,
    tp_categoria_escola_privada smallint,
    PRIMARY KEY (nu_ano_censo, co_entidade)
);
CREATE INDEX escola_ano_uf_idx          ON escola_ano (nu_ano_censo, sg_uf);
CREATE INDEX escola_ano_municipio_idx   ON escola_ano (nu_ano_censo, co_municipio);
CREATE INDEX escola_ano_dependencia_idx ON escola_ano (nu_ano_censo, tp_dependencia);

-- Fatos quantitativos por escola/ano/variavel -------------------------------
-- Apenas valores > 0 sao armazenados (ausencia de linha = zero ou nao informado).
CREATE TABLE matricula (
    nu_ano_censo smallint NOT NULL,
    co_entidade  bigint   NOT NULL,
    co_variavel  integer  NOT NULL REFERENCES variavel (co_variavel),
    valor        integer  NOT NULL,
    PRIMARY KEY (nu_ano_censo, co_entidade, co_variavel),
    FOREIGN KEY (nu_ano_censo, co_entidade)
        REFERENCES escola_ano (nu_ano_censo, co_entidade) ON DELETE CASCADE
);
CREATE INDEX matricula_variavel_idx ON matricula (nu_ano_censo, co_variavel);

CREATE TABLE docente (LIKE matricula INCLUDING ALL);
ALTER TABLE docente
    ADD FOREIGN KEY (co_variavel) REFERENCES variavel (co_variavel),
    ADD FOREIGN KEY (nu_ano_censo, co_entidade)
        REFERENCES escola_ano (nu_ano_censo, co_entidade) ON DELETE CASCADE;

CREATE TABLE turma (LIKE matricula INCLUDING ALL);
ALTER TABLE turma
    ADD FOREIGN KEY (co_variavel) REFERENCES variavel (co_variavel),
    ADD FOREIGN KEY (nu_ano_censo, co_entidade)
        REFERENCES escola_ano (nu_ano_censo, co_entidade) ON DELETE CASCADE;
