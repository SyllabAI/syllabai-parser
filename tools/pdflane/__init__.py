"""pdflane — failsafe deterministic PDF parsing lane for past papers.

Stage 0 intake/normalization + text-layer probe, Stage 1 deterministic
extraction (pdftotext base layer, PyMuPDF structure/figures with the
total-row span patch, OpenDataLoader second opinion), deterministic
QP/MS structuring (parse_qp / parse_ms), gates G1-G5, and the parsed/
output-tree orchestrator (run_paper).

Phase 1 scope: deterministic only — no LLM calls. Every output records
provenance ("pdf-parsed"); any deficit lands in the review queue, never
silently dropped. See download/FAILSAFE_PARSE_ENGINE_PLAN.md.
"""

__version__ = "0.1.0"
