CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE spaces (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name     text NOT NULL,
    kind     text NOT NULL CHECK (kind IN ('local', 'cloud')),
    owner_id text
);

CREATE TABLE documents (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    space_id       bigint NOT NULL REFERENCES spaces (id),
    title          text NOT NULL,
    source_label   text,
    source_url     text,
    normalized_url text,
    source_type    text NOT NULL
                   CHECK (source_type IN ('web', 'pdf', 'text', 'markdown', 'video')),
    identity_key   text NOT NULL,
    content_hash   text NOT NULL,
    status         text NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'archived', 'superseded')),
    visibility     text NOT NULL DEFAULT 'anywhere'
                   CHECK (visibility IN ('anywhere', 'laptop_only')),
    supersedes_id  bigint REFERENCES documents (id) ON DELETE SET NULL,
    saved_at       timestamptz NOT NULL DEFAULT now(),
    last_asked_at  timestamptz,
    page_count     integer
);

-- FR7: only one active document per identity in a space
CREATE UNIQUE INDEX documents_active_identity
    ON documents (space_id, identity_key) WHERE status = 'active';

CREATE TABLE chunks (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id   bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    position      integer NOT NULL,
    heading       text,
    page          integer,
    start_seconds double precision,
    text          text NOT NULL,
    embedding     vector(384) NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, position)
);

-- chunk_ids has no foreign key: deleting a document must not break the log
CREATE TABLE query_log (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asked_at  timestamptz NOT NULL DEFAULT now(),
    channel   text NOT NULL CHECK (channel IN ('cli', 'web', 'discord')),
    chunk_ids bigint[] NOT NULL DEFAULT '{}',
    status    text NOT NULL CHECK (status IN ('answered', 'refused', 'fallback')),
    seconds   double precision NOT NULL
);

CREATE TABLE settings (
    key   text PRIMARY KEY,
    value text NOT NULL
);

INSERT INTO spaces (name, kind) VALUES ('default', 'local');

INSERT INTO settings (key, value) VALUES
    ('embedding_model', 'BAAI/bge-small-en-v1.5'),
    ('embedding_dim', '384');
