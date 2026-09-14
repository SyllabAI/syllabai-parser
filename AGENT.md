# SyllabAI Parser — Multi-Agent Rules

The project-wide multi-agent operating system is canonical in `SyllabAI/syllabai` (`AGENT.md` + `.syllabai/`).

Parser-specific rules:

1. Parser output is candidate educational representation until downstream validation accepts it.
2. Preserve source identity, provenance, asset references, unresolved references and deterministic output.
3. Parser/core bundle changes are a shared contract: update the contract fixtures and coordinate with core before changing semantics.
4. Educational-content fields must remain fail-loud when the consumer does not understand them; do not silently discard unknown fields.
5. Record task ID, base commit and contract impact before substantial work.
6. Label completion claims VERIFIED / INFERRED / REPORTED / UNVERIFIED and retain durable evidence for material milestones.
7. If main advances and touched parser/core contract files overlap, reconcile before completion and rerun parser + contract tests.
8. The OCR step that produces GLM-OCR markdown from official PDFs is an external input boundary, served two ways: the manual ocr.z.ai website workflow (primary, unchanged) and the `tools/ocr_batch/` automation (additive; dual backend api/ollama, `--pair` QP+MS). Markdown bytes are the contract — batch output is never rewritten downstream, referenced images are downloaded at export time (signed URLs expire in ~1 week), and every export carries a md↔asset `manifest.json`.
