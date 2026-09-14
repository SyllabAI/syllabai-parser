# Real-Corpus Content Package v0.1 Proof

**Status:** IMPLEMENTED / VERIFIED — bounded real-corpus v0.1 reconstruction proof
**Scope:** one real Revision Note + one real production-VALIDATED QP/MS pair + five negative gates
**Not claimed:** byte-for-byte package determinism (an observation is printed, not asserted as a contract); any architecture claim beyond the bounded v0.1 compiler.

## Why this exists

`../test_proof.py` proves the package mechanics over a synthetic fixture. The V20
production reconciliation (`syllabai` central repo, §4) requires the next proof to
use **real, already validated canonical content** instead of expanding the synthetic
fixture set. This directory is that proof. The synthetic fixture suite is unchanged.

## The real material (committed under `source/`)

### Revision Note (positive case, resource side)

- `source/revision-note.md` — verbatim from `SyllabAI/syllabai-resources`
  (`Chemistry IGCSE Revision Notes/1. Principles of Chemistry/c. Atomic Structure/
  Relative atomic mass - IGCSE Chemistry Revision Notes.md`),
  sha256 `88d99b91f0f7cbf4cb399cc0f5cb7be164af55367ba415c2551eabd918058e1a`.
- Specification-point mappings **4CH1-1.16** and **4CH1-1.17** are `HUMAN_VALIDATED`
  by the operator (2026-09-11) in the note's frontmatter. Per
  `CONTENT_CORPUS_ARCHITECTURE.md` §7, `HUMAN_VALIDATED` is the authoritative
  trust tier — the inventory represents it as the platform lifecycle `VALIDATED`.

### QP/MS pair (positive case, assessment side)

Production paper `cfccc663-8aef-4a20-90b4-1205b3e740b5` — Edexcel International
GCSE Chemistry, session "Summer 2019" — `VALIDATED` with a **complete marking
contract** (all 7 question versions carry a VALIDATED mark scheme; verified at
export time; refusal to export anything else is enforced in the exporter).

Provenance chain (full detail in `source/SOURCE_PROVENANCE.json`):

1. **Original PDFs** (`SyllabAI/syllabai-pastpapers`, manifest `2019-06/4CH1-2CR`,
   qp.pdf `4e0bd25c…`, ms.pdf `b9bf54a2…`) — link status **IDENTITY_INFERRED**
   (sitting/variant naming + reconciliation mark structure; no PDF digest inside
   the OCR bundle).
2. **OCR canonical documents** (workbench protective snapshot
   `corpus-bundles/igcse-chemistry-4ch0-2c-2019junr/{qp,ms}-canonical.json`,
   engine `glm-ocr-markdown 1.0.0`, canonical source checksums `b5524ad3…` /
   `bd1bc885…`) — link status **DETERMINISTIC**: both documentIds equal the
   production paper's `question_paper_document_id` / `mark_scheme_document_id`
   (documentId = CanonicalIdentity(checksum|engine|version), enforced by
   `CanonicalDocumentValidator` at ingestion). All 5 bundle files verify against
   the snapshot's `SHA256SUMS` ledger.
3. **Production validated records** (exported through the sanctioned teacher API,
   workflow run `SyllabAI/syllabai-web` **34899656801**, artifact
   `content-package-export.json`) — link status **DETERMINISTIC**.

### Negative-case material

`content-package-export.json` also carries one **SUGGESTED scheme-less paper**
(`118e7ed4…`, "4CH0/2CR June 2014", 6 real scheme-less versions). Negative case
N4 injects one of those REAL versions (with its real parts, zero mark points,
promoted to VALIDATED) — the exact pre-guard shape the production marking-contract
guard refuses with 409.

## What the proof does (`run_proof.py`)

- **R1** builds `inventory.json` + `generated/{qp,ms}.md` deterministically from the
  committed sources (the Markdown artifacts are rendered from the canonical
  textBlocks; the ORIGINAL canonical checksums are preserved in the inventory's
  `canonicalIdentity` block, so artifact hashes never overwrite source hashes).
- **R2** compiles with the SAME compiler as the bounded fixture
  (`../compile_proof.py`); **R2a** re-verifies every MANIFEST artifact hash;
  **R2b** prints a consecutive-compile byte-equality **observation**.
- **R3** copies the package alone into a clean room and reconstructs the domain
  records from SQLite: identities, provenance, lifecycle, note↔spec and
  QP/MS/part/mark-point relationships, the complete marking contract (including
  question-level points with NULL part linkage, mirroring production
  `mark_points.question_part_id`), and semantic equivalence against the
  production export records.
- **R4** negative gates — each must be rejected **for the expected reason** and
  must create **no package directory**:

| Case | Material | Expected rejection |
|---|---|---|
| N1 bad source checksum | tampered note hash | `sourceSha256 does not match` |
| N2 missing provenance | provenance dropped | `missing required field provenance` |
| N3 incomplete QP/MS pairing | MS artifact absent | `QP/MS source file missing` |
| N4 scheme-less version | REAL version promoted | `missing mark points (scheme-less)` |
| N5 invalid lifecycle | paper `SUGGESTED` | `requires VALIDATED, got SUGGESTED` |

## Architectural boundary (unchanged)

The SQLite package is a DERIVED portable artifact: not canonical learner state,
not the authoritative KG, not a production database, not a validation authority.
PostgreSQL/domain state remains canonical; Markdown remains durable
content/interchange. A learner-servable package requires a complete deterministic
marking contract — the compiler refuses incomplete contracts regardless of what
could be represented in SQLite.

## Known gaps (recorded, not hidden)

- The production `documents` table has no rows for campaign-imported papers (the
  campaign importer carried provenance strings but not content-store rows), so the
  teacher provenance endpoint fail-closed 404s for them; source identity is served
  by the snapshot bundle (link 2). The exporter refuses to export a positive case
  whose provenance cannot be established.
- Link 1 (PDF ↔ bundle) is identity-inferred; it is recorded as such and is not
  promoted to a cryptographic claim.
- The corpus directory naming (`4ch0-…`) reflects the collector's legacy-spec
  label; the production paper identity and the pastpapers manifest
  (`4CH1/2CR`, 2017-spec naming) are authoritative here.
