"""Mark-scheme extractor port (``GlmOcrMarkSchemeExtractor``).

Faithful port: table-first entries, rowspan-deferred marks, both total
placements, IC tables (standalone / embedded / June long-header), marking
vocabulary, warnings — all byte-identical to the Java implementation.
"""

from __future__ import annotations

import re

from . import DRAFT_SCHEMA_VERSION, MS_EXTRACTION_METHOD
from .canonical import elements_in_reading_order
from .question_extractor import FIGURE_UNAVAILABLE

LABEL = re.compile(r"^(\*?)(\d{1,2})\s*((?:\([a-h]\))?(?:\([ivx]+\))?)\s*$")
TOTAL_IN_TABLE = re.compile(r"^total for question\s*(\d{1,2})\s*$", re.I)
TOTAL_STANDALONE = re.compile(
    r"Total for [Qq]uestion\s*(\d{1,2})\s*=?\s*(\d{1,3})\s*marks?")
PAPER_TOTAL_IN_LINE = re.compile(r"total for paper\s*=?\s*(\d{1,3})\s*marks?", re.I)
MCQ_ANSWER = re.compile(r"The only correct answer is\s*([A-D])\b")
MARKER = re.compile(r"\((\d{1,2})\)")
DEPENDENT_ON = re.compile(r"dependent on\s+([^)]*)", re.I)
MP_REF = re.compile(r"\bMP\s?(\d+)", re.I)
ECF = re.compile(r"\becf\b", re.I)
ANY_TWO_FROM = re.compile(r"any\s+two\s+from", re.I)
REJECT = re.compile(r"do\s+not\s+accept|is\s+insufficient", re.I)
OR_SPLIT = re.compile(r"\bor\b", re.I)
PAPER_REF = re.compile(r"\b(W[A-Z]{2}\d{2}/\d{1,2}[A-Z]?)\b")
LOG_NUMBER = re.compile(r"log\s+number\s+(P\d{5,6}[A-Z])\b", re.I)
PUBLICATION_CODE = re.compile(r"publications?\s+code\s+(\S+)", re.I)
SESSION_LINE = re.compile(
    r"^(Summer|Autumn|Winter|January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+20\d{2}$", re.I)
IC_HEADER_CELL = re.compile(r"^(ic points|number of indicative marking points.*)$", re.I)
IC_VALUE = re.compile(r"^\d{1,2}([–—-]\d{1,2})?$")
BARE_INT = re.compile(r"^\d{1,3}$")


class _RawEntry:
    __slots__ = ("entry_id", "label", "number", "qwc", "answer_text", "mark_points",
                 "guidance", "marks", "marks_cell_source")

    def __init__(self, entry_id, label, number, qwc, mark_points, initial_answer):
        self.entry_id = entry_id
        self.label = label
        self.number = number
        self.qwc = qwc
        self.answer_text = initial_answer
        self.mark_points = mark_points
        self.guidance = []
        self.marks = None
        self.marks_cell_source = None


class _State:
    def __init__(self, doc_id):
        self.doc_id = doc_id
        self.entries = []
        self.totals = {}
        self.warnings = []
        self.ic_rows = []
        self.figure_refs = []
        self.meta = [None] * 7  # board, qual, subject, paperRef, session, date, duration
        self.log_number = None
        self.publication_code = None
        self.paper_total = None
        self.ic_table = None
        self.current = None
        self.in_ic_block = False
        self.ic_location = None


def _classify_guidance(guidance_text, sink):
    """Classify each guidance line by leading keyword (Java twin)."""
    for line in (guidance_text or "").split("\n"):
        t = line.strip()
        if not t:
            continue
        lower = t.lower()
        if lower.startswith("allow"):
            kind = "allow"
        elif lower.startswith("ignore"):
            kind = "ignore"
        elif lower.startswith("example calculation"):
            kind = "example-calculation"
        elif lower.startswith("example diagram") or lower.startswith("example graph"):
            kind = "example-diagram"
        elif lower.startswith("ecf"):
            kind = "ecf"
        elif lower.startswith("mp") and "dependent" in lower:
            kind = "dependent"
        else:
            kind = "note"
        sink.append({"kind": kind, "text": t})


def _mark_point(ordinal: int, segment: str, marks):
    raw = segment.strip()
    dependent_on = []
    for dependent in DEPENDENT_ON.finditer(raw):
        for ref in MP_REF.finditer(dependent.group(1)):
            value = "MP" + ref.group(1)
            if value not in dependent_on:
                dependent_on.append(value)
    ecf = ECF.search(raw) is not None
    any_two_from = ANY_TWO_FROM.search(raw) is not None
    reject = REJECT.search(raw) is not None
    or_parts = OR_SPLIT.split(raw)
    alternatives = [part.strip() for part in or_parts[1:] if part.strip()]
    text = or_parts[0].strip()
    return {
        "ordinal": ordinal,
        "text": text,
        "marks": marks,
        "dependentOn": dependent_on,
        "ecf": ecf,
        "alternatives": alternatives,
        "anyTwoFrom": any_two_from,
        "reject": reject,
        "rawText": raw,
    }


def mark_points(answer_cell):
    """Split an answer cell on "(N)" markers (see Java twin for the rules)."""
    if answer_cell is None or not answer_cell.strip():
        return []
    points = []
    current = []
    consumed = 0
    ordinal = 0
    for marker in MARKER.finditer(answer_cell):
        current.append(answer_cell[consumed:marker.start()])
        segment = "".join(current)
        if segment.strip():
            ordinal += 1
            points.append(_mark_point(ordinal, segment, int(marker.group(1))))
        current = []
        consumed = marker.end()
    current.append(answer_cell[min(consumed, len(answer_cell)):])
    tail = "".join(current).strip()
    if tail and not points:
        # no markers at all — not a splittable cell; leave whole (honesty)
        return []
    if tail:
        ordinal += 1
        points.append(_mark_point(ordinal, tail, None))
    return points


def _trailing_integer(cells):
    for cell in reversed(cells):
        c = cell.strip()
        if not c:
            continue
        return int(c) if BARE_INT.fullmatch(c) else None
    return None


def _all_ic_values(cells):
    any_value = False
    for cell in cells:
        c = cell.strip()
        if not c:
            continue
        if not IC_VALUE.fullmatch(c):
            return False
        any_value = True
    return any_value


def _first_non_empty(cells):
    for cell in cells:
        if cell.strip():
            return cell.strip()
    return ""


class GlmOcrMarkSchemeExtractor:
    extraction_method = MS_EXTRACTION_METHOD

    def extract(self, mark_scheme: dict) -> dict:
        state = _State(mark_scheme["documentId"])
        for element in elements_in_reading_order(mark_scheme):
            kind = element["element_type"]
            if kind == "table":
                self._handle_table(element, state)
            elif kind == "text_block":
                self._handle_text_line(element["text"], state)
            elif kind == "figure":
                state.figure_refs.append(self._figure_ref(element))
        self._close_entry(state)
        if state.figure_refs:
            # visibility warning: MS figures exist but the entries have no
            # per-row attachment — a reviewer must see what was found
            state.warnings.append(
                str(len(state.figure_refs))
                + " figure reference(s) in the mark-scheme markdown are not "
                + "represented in the structured entries; preserved in figureRefs")
        draft = {
            "schemaVersion": DRAFT_SCHEMA_VERSION,
            "extractionMethod": MS_EXTRACTION_METHOD,
            "reviewRequired": True,
            "paper": self._paper_meta(mark_scheme, state),
            "entries": state.entries,
            "questionTotals": {str(number): value
                               for number, value in sorted(state.totals.items())},
            "paperTotal": state.paper_total,
            "icTable": state.ic_table,
            "warnings": state.warnings,
        }
        if state.figure_refs:
            # null/absent in the Java twin (per-field NON_NULL) — the key is
            # omitted entirely so figure-free drafts stay byte-identical
            draft["figureRefs"] = list(state.figure_refs)
        return draft

    @staticmethod
    def _figure_ref(figure: dict) -> dict:
        """Figure reference exactly as the QP extractor records it (same
        failure state, same field semantics) — MS entries stay unassigned,
        so the ref carries just the canonical element identity and URL."""
        return {
            "elementId": figure["element_id"],
            "sourceName": figure["source_name"],
            "format": figure["format"],
            "url": figure["text"],
            "availability": FIGURE_UNAVAILABLE,
        }

    # ── table handling ────────────────────────────────────────────────────────

    def _handle_table(self, table, state):
        state.in_ic_block = False
        for row in table["rows"]:
            self._handle_row(row, state)
        state.in_ic_block = False
        self._finalize_ic_block(state)
        self._close_entry(state)  # each table completes its entries

    def _finalize_ic_block(self, state):
        if state.ic_rows and state.ic_table is None:
            state.ic_table = {
                "rows": list(state.ic_rows),
                "location": state.ic_location or "standalone",
            }
            state.ic_rows = []

    def _handle_row(self, row, state):
        cells = [cell if cell is not None else "" for cell in row]
        if not cells:
            return

        # IC header (standalone table or embedded in the QWC question)
        if len(cells) >= 3 and IC_HEADER_CELL.fullmatch(cells[0].strip()):
            state.in_ic_block = True
            if state.ic_table is None:
                state.ic_location = "standalone" if state.current is None else "embedded"
            elif state.current is not None:
                state.warnings.append("duplicate IC table header at " + self._label_of(state))
            return
        if state.in_ic_block and _all_ic_values(cells):
            state.ic_rows.append(cells)
            return
        if state.in_ic_block:
            state.in_ic_block = False  # first non-value row exits the IC block
            self._finalize_ic_block(state)

        # header row
        if cells[0].strip().lower() == "question number":
            return

        # in-table total row
        for cell in cells:
            total = TOTAL_IN_TABLE.fullmatch(cell.strip())
            if total:
                self._record_total(total.group(1), _trailing_integer(cells), "in-table row", state)
                return

        # label row → new entry
        label = LABEL.fullmatch(cells[0].strip())
        if label:
            self._open_entry(label, cells, state)
            return

        # everything else is a continuation of the current entry (rowspan)
        self._handle_continuation(cells, state)

    def _handle_continuation(self, cells, state):
        current = state.current
        if current is None:
            if any(cell.strip() for cell in cells):
                state.warnings.append(
                    "orphan row before first entry: " + _first_non_empty(cells))
            return
        for i, cell in enumerate(cells):
            if not cell.strip():
                continue
            last = i == len(cells) - 1
            if last and BARE_INT.fullmatch(cell.strip()) and len(cells) >= 3 and current.marks is None:
                # rowspan-deferred marks arriving on a later row
                current.marks = int(cell.strip())
                current.marks_cell_source = "rowspan continuation row"
                continue
            if BARE_INT.fullmatch(cell.strip()):
                state.warnings.append(self._label_of(state) + ': bare integer cell "'
                                      + cell.strip() + '" skipped (rubric/rowspan ambiguity)')
                continue
            if i == 0 and len(cells) <= 2:
                current.answer_text += "\n" + cell.strip()
            else:
                _classify_guidance(cell.strip(), current.guidance)

    def _open_entry(self, label, cells, state):
        self._close_entry(state)
        asterisk = label.group(1)
        number = int(label.group(2))
        part = "" if label.group(3) is None else re.sub(r"[()]", "", label.group(3))
        printed_label = asterisk + label.group(2) + (label.group(3) or "")
        entry_id = "ms-" + (state.doc_id[:8] if state.doc_id else "doc") + "-q" + str(number) + part

        answer = cells[1] if len(cells) > 1 else None
        marks = _trailing_integer(cells)

        points = mark_points(answer)
        guidance = []
        # guidance cells live between the answer cell and the mark cell
        for i in range(2, len(cells) - 1):
            if cells[i].strip():
                _classify_guidance(cells[i].strip(), guidance)

        entry = _RawEntry(entry_id, printed_label, number, bool(asterisk), points,
                          "" if answer is None else answer.strip())
        entry.marks = marks
        entry.marks_cell_source = "label row" if marks is not None else None
        entry.guidance.extend(guidance)
        state.current = entry
        state.entries.append(self._to_entry(entry))

    def _close_entry(self, state):
        if state.current is not None:
            state.entries[-1] = self._to_entry(state.current)
            state.current = None

    def _to_entry(self, raw):
        answer = raw.answer_text.strip()
        mcq = MCQ_ANSWER.search(answer)
        is_mcq = mcq is not None
        confidence = 0.85 if is_mcq else (0.75 if raw.marks is not None else 0.5)
        return {
            "entryId": raw.entry_id,
            "label": raw.label,
            "number": raw.number,
            "qwc": raw.qwc,
            "mcq": is_mcq,
            "correctOption": mcq.group(1) if is_mcq else None,
            "answerText": answer,
            "markPoints": raw.mark_points,
            "guidance": raw.guidance,
            "marks": raw.marks,
            "marksCellSource": raw.marks_cell_source,
            "confidence": confidence,
        }

    # ── text lines (standalone totals + metadata) ─────────────────────────────

    def _handle_text_line(self, raw_line, state):
        text = (raw_line or "").strip()
        if not text:
            return
        # search — not fullmatch — June/1A glue the paper total onto the line
        total = TOTAL_STANDALONE.search(text)
        if total:
            self._record_total(total.group(1), int(total.group(2)), "standalone line", state)
        paper_total = PAPER_TOTAL_IN_LINE.search(text)
        if paper_total:
            value = int(paper_total.group(1))
            if state.paper_total is not None and state.paper_total != value:
                state.warnings.append(
                    "paper total conflict: " + str(state.paper_total) + " vs " + str(value))
            state.paper_total = value
        self._extract_meta(text, state)

    def _extract_meta(self, text, state):
        paper_ref = PAPER_REF.search(text)
        if paper_ref and state.meta[3] is None:
            state.meta[3] = paper_ref.group(1)
        log_number = LOG_NUMBER.search(text)
        if log_number and state.log_number is None:
            state.log_number = log_number.group(1)
        publication_code = PUBLICATION_CODE.search(text)
        if publication_code and state.publication_code is None:
            state.publication_code = publication_code.group(1)
        if state.meta[0] is None and "Pearson Edexcel" in text:
            state.meta[0] = "Edexcel"
        if state.meta[4] is None and SESSION_LINE.fullmatch(text):
            state.meta[4] = text
        if state.meta[1] is None and "international advanced" in text.lower():
            state.meta[1] = "IAL"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _record_total(self, number_text, mark, placement, state):
        number = int(number_text)
        if mark is None:
            state.warnings.append("total for question " + str(number) + " (" + placement
                                  + "): no mark value in row")
            return
        existing = state.totals.get(number)
        if existing is not None and existing != mark:
            state.warnings.append("total conflict for question " + str(number) + ": "
                                  + str(existing) + " (first) vs " + str(mark)
                                  + " (" + placement + ")")
        state.totals[number] = mark

    def _paper_meta(self, doc, state):
        board = state.meta[0]
        if board is None and state.meta[3] is not None:
            board = "Edexcel"
        return {
            "board": board,
            "qualification": state.meta[1],
            "subject": state.meta[2],
            "paperReference": state.meta[3],
            "logNumber": state.log_number,
            "publicationCode": state.publication_code,
            "session": state.meta[4],
            "examDate": state.meta[5],
            "duration": state.meta[6],
            "canonicalDocumentId": doc["documentId"],
        }

    def _label_of(self, state):
        return "?" if state.current is None else state.current.label
