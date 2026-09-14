-- SyllabAI Content Package v0.1
-- Derived portable representation only. PostgreSQL remains canonical operational/domain storage.
-- Do not use this schema as the learner model, authoritative KG, or serving authorization source.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA user_version = 1;

CREATE TABLE package_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE resource (
    resource_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    status TEXT NOT NULL,
    subject TEXT,
    qualification TEXT,
    curriculum_version TEXT,
    source_provenance_id TEXT
);

CREATE TABLE resource_version (
    resource_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_path TEXT,
    content_sha256 TEXT,
    status TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (resource_id, version),
    FOREIGN KEY (resource_id) REFERENCES resource(resource_id)
);

CREATE TABLE resource_provenance (
    provenance_id TEXT PRIMARY KEY,
    source_uri TEXT,
    source_sha256 TEXT,
    source_type TEXT NOT NULL,
    parser TEXT,
    parser_version TEXT,
    imported_at TEXT
);

CREATE TABLE specification_point (
    specification_point_id TEXT PRIMARY KEY,
    specification_id TEXT NOT NULL,
    external_ref TEXT,
    title TEXT
);

CREATE TABLE revision_note (
    revision_note_id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    content_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (resource_id, version) REFERENCES resource_version(resource_id, version)
);

CREATE TABLE revision_note_specification_point (
    revision_note_id TEXT NOT NULL,
    specification_point_id TEXT NOT NULL,
    mapping_status TEXT NOT NULL,
    PRIMARY KEY (revision_note_id, specification_point_id),
    FOREIGN KEY (revision_note_id) REFERENCES revision_note(revision_note_id),
    FOREIGN KEY (specification_point_id) REFERENCES specification_point(specification_point_id)
);

CREATE TABLE paper (
    paper_id TEXT PRIMARY KEY,
    qualification TEXT,
    subject TEXT,
    session TEXT,
    status TEXT NOT NULL,
    question_paper_sha256 TEXT,
    mark_scheme_sha256 TEXT
);

CREATE TABLE paper_question (
    question_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    anchor TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id),
    UNIQUE (paper_id, ordinal)
);

CREATE TABLE question_part (
    question_part_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    anchor TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (question_id) REFERENCES paper_question(question_id),
    UNIQUE (question_id, ordinal)
);

CREATE TABLE mark_scheme (
    mark_scheme_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    content_path TEXT,
    content_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES paper(paper_id)
);

CREATE TABLE mark_point (
    mark_point_id TEXT PRIMARY KEY,
    mark_scheme_id TEXT NOT NULL,
    -- nullable: a question-level mark point (ref without a part suffix, e.g.
    -- "1") belongs to the question, not any single part — mirrors the
    -- production mark_points.question_part_id NULL case
    question_part_id TEXT,
    anchor TEXT NOT NULL,
    marks INTEGER,
    text TEXT,
    status TEXT NOT NULL,
    FOREIGN KEY (mark_scheme_id) REFERENCES mark_scheme(mark_scheme_id),
    FOREIGN KEY (question_part_id) REFERENCES question_part(question_part_id)
);

CREATE TABLE parser_run (
    parser_run_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    parser TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL
);

CREATE TABLE validation_finding (
    finding_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE INDEX idx_resource_version_status ON resource_version(status);
CREATE INDEX idx_revision_note_status ON revision_note(status);
CREATE INDEX idx_paper_status ON paper(status);
CREATE INDEX idx_validation_finding_entity ON validation_finding(entity_type, entity_id);
