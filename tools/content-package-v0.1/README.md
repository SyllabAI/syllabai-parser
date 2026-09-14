# Content Package v0.1 proof harness

**Status: IMPLEMENTED / UNVERIFIED**

This directory contains the first bounded implementation artifacts for the Content Package v0.1 proposal.

## Purpose

Prove that a small, known-good corpus can be represented as:

1. durable Markdown/content artifacts;
2. a SyllabAI-specific SQLite derived package; and
3. a manifest containing compiler/schema versions, artifact hashes, provenance and lifecycle state.

This is a proof harness, not a production serving store and not a replacement for PostgreSQL.

## Current artifacts

- `schema.sql` — SQLite v0.1 relational schema.
- `MANIFEST.example.json` — minimum package manifest contract.

## Required proof gates

The implementation must not be considered **VERIFIED** until a clean environment demonstrates all of the following:

- schema creates successfully with foreign keys enabled;
- all package artifacts have SHA-256 entries in the manifest;
- source identities and provenance survive compilation;
- Revision Note SpecificationPoint mappings survive round-trip;
- QP/MS pairing and question/part/mark-point identity survive round-trip;
- `SUGGESTED`, `REVIEW_REQUIRED`, quarantined or otherwise non-serving assessment state cannot be promoted by package construction;
- ambiguous identity or required relationship failures fail closed;
- rebuilding from the same source identities and compiler/schema versions produces equivalent domain/package state;
- the package cannot be used to bypass application authorization or learner-serving validation gates.

Byte-for-byte package determinism is intentionally **not yet claimed**. It should be tested separately after semantic reconstruction is green.

## Boundaries

- PostgreSQL remains canonical operational/domain storage.
- The authoritative educational KG remains canonical educational truth.
- Learner state is not stored here as authoritative state.
- Package existence does not imply learner-serving eligibility.
- MarkdownDB is not a dependency.
