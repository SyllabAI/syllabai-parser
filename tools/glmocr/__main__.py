"""CLI: ``python -m glmocr <markdown-file> <doc|qp|ms>`` → JSON on stdout.

Mirrors the Java ``GlmOcrConformanceDump`` CLI mode-for-mode (extractedAt
pinned to the epoch) so the conformance harness can diff the outputs.
"""

from __future__ import annotations

import json
import sys

from .canonical import GlmOcrMarkdownParser, EPOCH
from .markscheme_extractor import GlmOcrMarkSchemeExtractor
from .question_extractor import GlmOcrQuestionExtractor


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m glmocr <markdown-file> <doc|qp|ms>", file=sys.stderr)
        return 2
    path, mode = args
    with open(path, "rb") as handle:
        source = handle.read()
    uri = "corpus/" + path.replace("\\", "/").split("/")[-1]

    parser = GlmOcrMarkdownParser()
    if mode == "doc":
        document = parser.parse_with_fixed_identity(source, uri, EPOCH)
        print(json.dumps(document, ensure_ascii=False, indent=2))
    elif mode == "qp":
        document = parser.parse_with_fixed_identity(source, uri, EPOCH)
        draft = GlmOcrQuestionExtractor().extract(document)
        print(json.dumps(draft, ensure_ascii=False))
    elif mode == "ms":
        document = parser.parse_with_fixed_identity(source, uri, EPOCH)
        draft = GlmOcrMarkSchemeExtractor().extract(document)
        print(json.dumps(draft, ensure_ascii=False))
    else:
        print("unknown mode: " + mode, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
