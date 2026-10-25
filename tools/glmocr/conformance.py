"""Cross-language conformance harness (Session 9, §12).

Runs every real GLM-OCR sample through BOTH implementations:

1. Python reference implementation (this package — the behavioral reference)
2. Java production implementation (``GlmOcrConformanceDump``)

and compares the semantic output: document structure, IDs, question numbers,
parts, marks, QWC markers, MarkScheme entries, MarkPoints, image references,
warnings (validation findings) and provenance — all fields, verbatim.

The ``atomize`` stage additionally runs the per-sitting atomizer (OCR-Q4) on
both sides — Java ``GlmOcrAtomizeDump`` vs Python ``atomize_parsed`` over the
same fixed-identity documents — and diffs the full ``paper.json`` export
(questions, parts, inherited-stem prompts, mark-scheme bindings, totals,
unmatched entries, warnings).

Usage (from the repo root, after ``mvn -o test`` has compiled target/classes):

    python3 tools/glmocr/conformance.py

Exit code 0 = full conformance across all fixtures and modes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "src" / "test" / "resources" / "glm-ocr"
GLYPH_FIXTURES = REPO_ROOT / "src" / "test" / "resources" / "glyph-normalization"
TABLE = REPO_ROOT / "tools" / "glyph-normalization" / "table.v1.json"
TOOLS_DIR = REPO_ROOT / "tools"

# Jackson artifacts the Java dump CLI needs (version-agnostic discovery;
# override with the GLMOCR_JAVA_CP environment variable, e.g. from
# `mvn dependency:build-classpath -Dmdep.outputFile=cp.txt`)
JACKSON_PATTERNS = [
    "com/fasterxml/jackson/core/jackson-databind/*/jackson-databind-*.jar",
    "com/fasterxml/jackson/core/jackson-core/*/jackson-core-*.jar",
    "com/fasterxml/jackson/core/jackson-annotations/*/jackson-annotations-*.jar",
    "com/fasterxml/jackson/datatype/jackson-datatype-jsr310/*/jackson-datatype-jsr310-*.jar",
]

FIXTURE_PAIRS = [
    ("june-2025-wph11-01-qp.md", "june-2025-wph11-01-ms.md"),
    ("october-2025-wph11-01-qp.md", "october-2025-wph11-01-ms.md"),
    ("october-2025-wph11-01a-qp.md", "october-2025-wph11-01a-ms.md"),
    # synthetic hardening fixture: unterminated <table>, orphan $$ fence,
    # unclosed <div align=center>, "N." numbering style + decimal guard
    ("pathological-qp.md", "pathological-ms.md"),
    # synthetic hardening fixture: MS/QP centered figure blocks — figureRefs
    # surfaced at draft level (previously silently dropped), QP ownership
    ("figure-ms-qp.md", "figure-ms-ms.md"),
]

MODES = ("doc", "qp", "ms")


def java_classpath() -> str:
    override = os.environ.get("GLMOCR_JAVA_CP")
    if override:
        return override
    entries = [str(REPO_ROOT / "target" / "classes")]
    m2 = Path.home() / ".m2" / "repository"
    for pattern in JACKSON_PATTERNS:
        for jar in sorted(m2.glob(pattern), reverse=True):
            if "sources" not in jar.name and "javadoc" not in jar.name:
                entries.append(str(jar))
                break
    return ":".join(entries)


def run_java(path: Path, mode: str) -> dict:
    result = subprocess.run(
        ["java", "-cp", java_classpath(),
         "com.syllabai.parser.tools.GlmOcrConformanceDump", str(path), mode],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def run_java_atomize(qp_file: Path, ms_file: Path) -> dict:
    result = subprocess.run(
        ["java", "-cp", java_classpath(),
         "com.syllabai.parser.tools.GlmOcrAtomizeDump", str(qp_file), str(ms_file)],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _normalize_source(path: Path) -> bytes:
    """T-MIG-141 Phase E intake law (the SAME law the Java dumps run since
    PuaNormalizer.normalizeAtIntake): normalize PUA/C0 artifacts through the
    canonical table before parsing. Identity on artifact-free fixtures.
    Byte-exact read (no universal-newline translation — the law is
    char-level and must see exactly what Java sees)."""
    from glmocr.normalize_pua import compile_table, load_table

    ct = compile_table(load_table(TABLE))
    return ct.normalize(path.read_bytes().decode("utf-8")).encode("utf-8")


def run_python(path: Path, mode: str) -> dict:
    sys.path.insert(0, str(TOOLS_DIR))
    from glmocr.canonical import GlmOcrMarkdownParser, EPOCH
    from glmocr.markscheme_extractor import GlmOcrMarkSchemeExtractor
    from glmocr.question_extractor import GlmOcrQuestionExtractor

    source = _normalize_source(path)
    uri = "corpus/" + path.name
    parser = GlmOcrMarkdownParser()
    document = parser.parse_with_fixed_identity(source, uri, EPOCH)
    if mode == "doc":
        return document
    if mode == "qp":
        return GlmOcrQuestionExtractor().extract(document)
    return GlmOcrMarkSchemeExtractor().extract(document)


def run_python_atomize(qp_file: Path, ms_file: Path) -> dict:
    sys.path.insert(0, str(TOOLS_DIR))
    from glmocr.atomize import atomize_parsed
    from glmocr.canonical import GlmOcrMarkdownParser, EPOCH

    parser = GlmOcrMarkdownParser()
    qp_doc = parser.parse_with_fixed_identity(
        _normalize_source(qp_file), "corpus/" + qp_file.name, EPOCH)
    ms_doc = parser.parse_with_fixed_identity(
        _normalize_source(ms_file), "corpus/" + ms_file.name, EPOCH)
    return atomize_parsed(qp_doc, ms_doc,
                          "corpus/" + qp_file.name, "corpus/" + ms_file.name)


def diff(path: str, expected, actual, out: list, depth: int = 0) -> None:
    """Collect human-readable differences between the Java and Python output."""
    if type(expected) is not type(actual) and not (
            isinstance(expected, (int, float)) and isinstance(actual, (int, float))):
        out.append(f"{path}: type {type(expected).__name__} != {type(actual).__name__}")
        return
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                out.append(f"{path}.{key}: only in Python output")
            elif key not in actual:
                out.append(f"{path}.{key}: only in Java output")
            else:
                diff(f"{path}.{key}", expected[key], actual[key], out, depth + 1)
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            out.append(f"{path}: length {len(expected)} != {len(actual)}")
        for index, (e, a) in enumerate(zip(expected, actual)):
            diff(f"{path}[{index}]", e, a, out, depth + 1)
    elif expected != actual:
        out.append(f"{path}: {expected!r} != {actual!r}")


def summarize(node, counters=None):
    """Small semantic summary printed for the final report."""
    if counters is None:
        counters = {}
    if isinstance(node, dict):
        if "questionId" in node:
            counters["questions"] = counters.get("questions", 0) + 1
        if "entryId" in node:
            counters["entries"] = counters.get("entries", 0) + 1
        if "ordinal" in node:
            counters["markPoints"] = counters.get("markPoints", 0) + 1
        if node.get("element_type") == "figure":
            counters["figures"] = counters.get("figures", 0) + 1
        for value in node.values():
            summarize(value, counters)
    elif isinstance(node, list):
        for value in node:
            summarize(value, counters)
    return counters



# --------------------------------------------------------------------------- #
# T-MIG-141 Phase E glyph leg (run-010): the canonical table's Python
# reference vs the Java PuaNormalizer (GlmOcrGlyphDump), over 16 glyph
# fixture classes — each class pinned by a fixture pair + expected outputs
# (manifest.json). CI fails on drift. Canary: C-intake-zero-pua.

GLYPH_MODELS = ["unmapped_pua_instances", "unmapped_pua_distinct",
                "c0_outside_mapped_instances", "c0_distinct"]


def run_java_glyph(path: Path, table: Path) -> dict:
    result = subprocess.run(
        ["java", "-cp", java_classpath(),
         "com.syllabai.parser.tools.GlmOcrGlyphDump", str(table), str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def glyph_leg() -> int:
    from glmocr.normalize_pua import compile_table, load_table

    manifest = json.loads((GLYPH_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    table = load_table(TABLE)
    ct = compile_table(table)
    failures = 0
    classes = manifest["classes"]
    for gc in classes:
        for name, pin in gc["files"].items():
            path = GLYPH_FIXTURES / name
            problems: list[str] = []
            text = path.read_bytes().decode("utf-8")  # byte-exact (no newline translation)
            py_norm = ct.normalize(text)
            py_pre = ct.census(text)
            py_post = ct.census(py_norm)
            if py_norm != pin["expectedNormalized"]:
                problems.append("python output != manifest expectedNormalized")
            if py_pre != pin["censusPre"]:
                problems.append("python censusPre != manifest pin")
            if py_post != pin["censusPost"]:
                problems.append("python censusPost != manifest pin")
            java = run_java_glyph(path, TABLE)
            if java["normalized"] != py_norm:
                problems.append("java normalized != python normalized (cross-language drift)")
            for key in GLYPH_MODELS:
                if java["censusPre"][key] != py_pre[key] or java["censusPost"][key] != py_post[key]:
                    problems.append(f"java census drift on {key}")
            if java["idempotenceDelta"] != 0 or ct.idempotence_delta(text) != 0:
                problems.append("idempotence violated")
            # the born-clean law: PASS classes must census ZERO post-normalization
            if gc["gate"] == "PASS" and (py_post["unmapped_pua_instances"]
                                         or py_post["c0_outside_mapped_instances"]):
                problems.append("born-clean violation on a PASS class")
            if gc["gate"] == "FAIL" and not (py_post["unmapped_pua_instances"]
                                             or py_post["c0_outside_mapped_instances"]):
                problems.append("the FAIL class did not fire the born-clean gate")
            if problems:
                failures += 1
                print(f"FAIL {name} — {len(problems)} difference(s):")
                for problem in problems[:10]:
                    print(f"     {problem}")
            else:
                post = py_post["unmapped_pua_instances"]
                print(f"PASS {name} [{gc['gate']}] (post-census artifacts: {post})")
    if failures:
        print(f"\nGLYPH CONFORMANCE FAILED: {failures} fixture file(s) differ")
        return 1
    print(f"\nGLYPH CONFORMANCE: {len(classes)}/{len(classes)} glyph fixture classes green "
          f"(py/java byte-exact + manifest pins + born-clean law; canary {manifest['canary']})")
    return 0


def main() -> int:
    failures = 0
    for qp_file, ms_file in FIXTURE_PAIRS:
        pair = qp_file.replace("-qp.md", "")
        files = {"doc": [qp_file, ms_file], "qp": [qp_file], "ms": [ms_file]}
        for mode, names in files.items():
            for name in names:
                java_output = run_java(FIXTURES / name, mode)
                python_output = run_python(FIXTURES / name, mode)
                problems = []
                diff(f"{name}:{mode}", java_output, python_output, problems)
                if problems:
                    failures += 1
                    print(f"FAIL {name} [{mode}] — {len(problems)} difference(s):")
                    for problem in problems[:10]:
                        print(f"     {problem}")
                    if len(problems) > 10:
                        print(f"     … and {len(problems) - 10} more")
                else:
                    summary = summarize(java_output)
                    detail = ", ".join(f"{key}={value}" for key, value in sorted(summary.items()))
                    print(f"PASS {name} [{mode}]" + (f" ({detail})" if detail else ""))

        # atomize stage: full paper.json export, Java vs Python, same pair
        java_export = run_java_atomize(FIXTURES / qp_file, FIXTURES / ms_file)
        python_export = run_python_atomize(FIXTURES / qp_file, FIXTURES / ms_file)
        problems = []
        diff(f"{pair}:atomize", java_export, python_export, problems)
        if problems:
            failures += 1
            print(f"FAIL {pair} [atomize] — {len(problems)} difference(s):")
            for problem in problems[:10]:
                print(f"     {problem}")
            if len(problems) > 10:
                print(f"     … and {len(problems) - 10} more")
        else:
            summary = summarize(java_export)
            detail = ", ".join(f"{key}={value}" for key, value in sorted(summary.items()))
            print(f"PASS {pair} [atomize]" + (f" ({detail})" if detail else ""))

    if failures:
        print(f"\nCONFORMANCE FAILED: {failures} file/mode combination(s) differ")
        return 1
    print("\nFULL CONFORMANCE: Java production and Python reference agree on every "
          "field of every fixture in every mode (doc/qp/ms + atomize export)")

    glyph_failures = glyph_leg()
    if glyph_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
