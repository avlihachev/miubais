CREATE TABLE jobs (
    id             TEXT PRIMARY KEY,
    reference      TEXT NOT NULL UNIQUE,
    source_lang    TEXT NOT NULL,
    target_lang    TEXT NOT NULL,
    hours_estimate NUMERIC(10, 3) NOT NULL CHECK (hours_estimate > 0),
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
