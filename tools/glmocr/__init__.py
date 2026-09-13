"""GLM-OCR reference implementation (Session 9).

Executable behavioral reference for the Java production parser in
``syllabai-parser``. Mirrors:

- ``com.syllabai.parser.canonical.CanonicalIdentity`` (deterministic ids)
- ``com.syllabai.parser.engine.glmocr.GlmOcrMarkdownParser`` (canonical adapter)
- ``com.syllabai.parser.structure.glmocr.GlmOcrQuestionExtractor`` (QP drafts)
- ``com.syllabai.parser.structure.glmocr.GlmOcrMarkSchemeExtractor`` (MS drafts)

Every regex, warning string, confidence value and field name is a faithful
port — cross-language conformance is enforced by ``conformance.py`` over the
six real corpus fixtures. When the Java side changes, this reference must
change with it (and vice versa).
"""

ENGINE_NAME = "glm-ocr-markdown"
ENGINE_VERSION = "1.1.0"  # 1.1.0: <br> -> newline in table cells (Java twin parity)

QP_EXTRACTION_METHOD = "glm-ocr-qp-v1"
MS_EXTRACTION_METHOD = "glm-ocr-ms-v1"

DRAFT_SCHEMA_VERSION = "1.0"

__all__ = [
    "canonical",
    "question_extractor",
    "markscheme_extractor",
    "ENGINE_NAME",
    "ENGINE_VERSION",
]
