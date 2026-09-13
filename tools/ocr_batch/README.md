# GLM-OCR Batch Automation (`tools/ocr_batch/`)

Automates the one step the parser pipeline deliberately treats as an external
input: turning the official **PDF question papers / mark schemes** into
**GLM-OCR markdown with image assets saved at export time**.

```text
PDF (QP/MS) ──> GLM-OCR ──> <stem>.md + assets/crop_*.png + manifest.json
                                 │
                                 ▼
        existing pipeline (unchanged): GlmOcrMarkdownParser
                                 │ canonical → QP/MS drafts
                                 ▼
                          syllabai-core ingestion
```

Two interchangeable backends, one output convention:

| Backend | Engine | Needs | Figure crops |
|---|---|---|---|
| `api` (default) | the `glm-ocr` **layout-parsing endpoint** that fronts ocr.z.ai — full layout pipeline (PP-DocLayoutV3 + parallel recognition), markdown + crop-image URLs come back from the service | API key (`ZAI_API_KEY` / `ZHIPU_API_KEY` / `GLMOCR_API_KEY`) | **yes** — downloaded at export time into `assets/` |
| `ollama` | local [Ollama](https://ollama.ai) `glm-ocr` model (0.9B params, MIT; tags `latest` 2.2 GB / `q8_0` 1.6 GB / `bf16`, 128K context) | Ollama installed + model pulled | **no** — model-only inference has no layout stage; the manifest records this honestly |

> **The manually-OCRed website workflow is unchanged and remains fully
> valid.** This tool is additive content-operations tooling — it exists so
> the corpus can grow without losing images (the audited
> `GLM-markdown-sample` corpus lost *every* image to signed-URL expiry;
> downloading at export time is the documented mandatory lesson, implemented
> here in code).

---

## Local usage

Requires Python 3.10+. The `api` backend is stdlib-only. The `ollama`
backend (and API page-counting/chunking) additionally uses `pypdfium2`:

```bash
pip install pypdfium2
```

### API backend (same engine as the website)

```bash
export ZAI_API_KEY=sk-...        # or ZHIPU_API_KEY / GLMOCR_API_KEY

# one paper
python3 tools/ocr_batch/ocr_batch.py "January 2012 QP - Unit 4.pdf" -o ocr-out

# a whole directory (or several), two pages only of one paper
python3 tools/ocr_batch/ocr_batch.py papers/ -o ocr-out --limit 5
python3 tools/ocr_batch/ocr_batch.py paper.pdf -o ocr-out --start-page 1 --end-page 4
```

Endpoints: default `https://api.z.ai/api/paas/v4/layout_parsing`
(mainland: `https://open.bigmodel.cn/api/paas/v4/layout_parsing`, pass
`--api-url`). Limits enforced up front: PDF ≤ 50 MB, ≤ 100 pages per
request (larger PDFs are automatically chunked with `start_page_id` /
`end_page_id` and the markdown joined in order). Pricing is token-based —
a full paper is a fraction of a cent.

### Ollama backend (fully local, no account)

```bash
ollama pull glm-ocr:q8_0        # 1.6 GB — smallest official quant
python3 tools/ocr_batch/ocr_batch.py papers/ -o ocr-out \
    --backend ollama --model glm-ocr:q8_0
```

Notes:

* Uses Ollama's **native `/api/generate`** endpoint with the documented
  document-parsing prompt (`Text Recognition:`) — the OpenAI-compatible
  endpoint is not recommended for vision (per the official ollama-deploy
  guide).
* Pages are rasterized locally with `pypdfium2` at `--dpi` (default 200,
  SDK parity) and capped to the SDK vision budget (≈1,003,520 px/page).
* If a dense page returns **empty output**, raise `--num-ctx` (default
  8192; the model supports 128K) — a known Ollama trap.
* Expect CPU-only speeds of roughly 0.5–2 min per page on a 4-core laptop;
  a GPU makes it ~1 s/page.

---

## Output layout (per paper)

```text
ocr-out/<paper-stem>/
├── <paper-stem>.md      markdown exactly as received (byte-faithful)
├── manifest.json        md ↔ asset map, SHA-256s, dims, warnings, timings
├── provenance.json      engine/model/endpoint, request id, token usage
├── pages/page_NNN.md    per-page markdown (when produced page-by-page)
└── assets/crop_*.png    images downloaded the same second they are referenced
```

The markdown is **never** rewritten: byte-fidelity is what the parser's
identity rule needs (`documentId = SHA-256(bytes) + engine + engineVersion`).
The manifest carries the URL → `assets/…` mapping instead. Asset names keep
the website convention (`crop_<n>_<millis>.png`), so the layout matches the
existing manually-OCRed corpus (`QP.md` / `MS.md` / `assets/`).

Fail-loud rules: an empty or malformed OCR result fails that paper (and the
run exits non-zero) and writes a failure `provenance.json` — nothing is
silently fabricated. A dead image URL is recorded under `unfetchedAssets`
and never blocks the text pipeline.

## Tests

```bash
python3 tools/ocr_batch/test_ocr_batch.py -v
```

17 unit tests, no network and no key required (both backends run against a
local mock endpoint; rasterization is exercised on a real two-page PDF).
The `tool-tests` job in `.github/workflows/ocr-batch.yml` runs them in CI on
every push/PR touching this directory.

## GitHub Actions

`.github/workflows/ocr-batch.yml` provides:

| Job | Trigger | What it proves |
|---|---|---|
| `tool-tests` | push/PR to `tools/ocr_batch/**` | the tool works (mocked HTTP, stdlib-only) |
| `demo-api` | manual (`workflow_dispatch`) | real end-to-end run against the Z.ai API on a corpus paper; artifacts uploaded |
| `demo-ollama` | manual | real end-to-end run against Ollama `glm-ocr:q8_0` on a GitHub runner — no API key |

Runner spec (standard free `ubuntu-latest`): **4 vCPU, 16 GB RAM, ~14 GB
free disk** — both routes fit comfortably. The `demo-api` job is
network-bound (≈1–3 min per paper). The `demo-ollama` job pays a ~2 GB model
pull plus CPU-only inference — smoke-test scale, not bulk.

To run the demos: add `ZAI_API_KEY` (and, if the papers repo is private,
`PAPERS_PAT`) as repository secrets, then *Run workflow* → pick the job's
inputs (papers repo/ref/sample path).
