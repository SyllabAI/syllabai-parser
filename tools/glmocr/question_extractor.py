"""Question-paper extractor port (``GlmOcrQuestionExtractor``).

Faithful port including every warning string and confidence value — the
conformance harness compares them verbatim.
"""

from __future__ import annotations

import re

from . import QP_EXTRACTION_METHOD, DRAFT_SCHEMA_VERSION
from .canonical import elements_in_reading_order

QUESTION_COLON = re.compile(r"^\*?(\d{1,2}):[ \t]*(.*)$")
QUESTION_SPACE = re.compile(r"^(\*?)(\d{1,2})\s+(\S.*)$")
QUESTION_DOT = re.compile(r"^(\*?)(\d{1,2})\.\s+(\S.*)$")
COMBINED_PART = re.compile(r"^\*?\(([a-h])\)\s*\(([ivx]+)\)\s*(.*)$")
LETTER_PART = re.compile(r"^\*?\(([a-h])\)\s*(.*)$")
ROMAN_PART = re.compile(r"^\(([ivx]+)\)\s*(.*)$")
OPTION = re.compile(r"^([A-D])\s+(\S.*)$")
BARE_LETTER = re.compile(r"^([A-D])$")
MARKS_BLOCK = re.compile(r"^\((\d{1,2})\)\s*$")
TOTAL_FOR_QUESTION = re.compile(
    r"^\(?(?:Total for question|TOTAL FOR QUESTION)\s*(\d{1,2})\s*=\s*(\d{1,3})"
    r"\s*marks?\)?\.?$", re.I)
TOTAL_FOR_PAPER = re.compile(r"TOTAL FOR PAPER\s*=\s*(\d{1,3})\s*MARKS", re.I)
TOTAL_FOR_SECTION = re.compile(r"TOTAL FOR SECTION\s*([A-Z])\s*=\s*(\d{1,3})\s*MARKS", re.I)
# Paper reference codes. Two printed families (engine parity with the Java
# twin's widened pattern):
#  - IAL unit codes  : WCH11/1C  (W + 2 letters + 2 digits)
#  - IGCSE codes     : 4CH0/1C, 4CH1/1CR, KCH0/2C (4 chars + / + number + up to 2 letters)
PAPER_REF = re.compile(r"\b((?:W[A-Z]{2}\d{2}|[A-Z0-9]{4})/\d{1,2}[A-Z]{0,2})\b")
LOG_NUMBER = re.compile(r"log\s+number\s+(P\d{5,6}[A-Z])\b", re.I)
PUBLICATION_CODE = re.compile(r"publications?\s+code\s+(\S+)", re.I)
LOG_TOTAL = re.compile(r"total mark for this paper is\s*(\d{1,3})", re.I)
TURN_OVER = re.compile(r"^Turn over\s*$", re.I)
NOISE = re.compile(
    r"^(Not to scale|\*NOT TO SCALE\*|See next page|End of Question Paper)\s*$", re.I)
SOURCE_NOTE = re.compile(r"^\(Source: ?(.*)\)\s*$")
# months accepted on a printed session line (e.g. "Summer 2013", "November 2021")
SESSION_MONTHS = ("January|February|March|April|May|June|July|"
                  "August|September|October|November|December")
SESSION_LINE = re.compile(r"^(Summer|Autumn|Winter|" + SESSION_MONTHS + r")\s+20\d{2}$", re.I)
DATE_LINE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\s+"
    r"(" + SESSION_MONTHS + r")\s+20\d{2}"
    # newer covers append the sitting time to the same line:
    # "Wednesday 18 January 2017 – Afternoon"
    r"(\s*[–—-]\s*(Morning|Afternoon|Evening))?$", re.I)
SPECIMEN_YEAR = re.compile(r"Sample Assessment Materials.*?(20\d{2})", re.I)
MONTH_YEAR = re.compile(r"(" + SESSION_MONTHS + r")\s+(20\d{2})", re.I)

FIGURE_UNAVAILABLE = "unavailable-signed-url"


def table_cell_lines(table_html):
    """splits an HTML-table blob into printed cell lines, tags stripped
    (port of the Java ``tableCellLines`` helper)."""
    lines = []
    if not table_html or "<table" not in table_html.lower():
        return lines
    for cell in re.split(r"</t[dh]>|<tr[^>]*>|</tr>", table_html):
        # cells keep raw internal newlines (e.g. "Wednesday 18 January 2017 – Afternoon\nTime: 1 hour");
        # each printed line is matched separately so the ^...$ identity regexes survive
        for line in re.sub(r"<[^>]+>", " ", cell).split("\n"):
            stripped = (line.replace("&amp;", "&").replace("&nbsp;", " ")
                        .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
            stripped = re.sub(r"[ \t\r]+", " ", stripped).strip()
            if stripped:
                lines.append(stripped)
    return lines


class _RawPart:
    __slots__ = ("label", "text", "figures", "answer_prompts", "marks", "qwc")

    def __init__(self, label: str):
        self.label = label
        self.text = ""
        self.figures = []
        self.answer_prompts = []
        self.marks = None
        self.qwc = False


class _RawQuestion:
    __slots__ = ("number", "numbering_style", "section", "stem", "qwc", "option_letters",
                 "option_texts", "parts", "figures", "table_element_ids",
                 "answer_prompts", "bare_letter_lines")

    def __init__(self, number: int, numbering_style: str):
        self.number = number
        self.numbering_style = numbering_style
        self.section = None
        self.stem = ""
        self.qwc = False
        self.option_letters = []
        self.option_texts = {}
        self.parts = []
        self.figures = []
        self.table_element_ids = []
        self.answer_prompts = []
        self.bare_letter_lines = False


class _State:
    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        self.questions = []
        self.totals = {}
        self.section_totals = {}
        self.front_matter_figures = []
        self.warnings = []
        self.meta = [None] * 7  # board, qual, subject, paperRef, session, date, duration
        self.log_number = None
        self.publication_code = None
        self.specimen_year = None
        # every printed paper-reference code, in reading order (covers print 2-3:
        # the Edexcel-Certificate twin KCH0/1C, the International GCSE 4CH0/1C and
        # the Double Award 4SC0/1C)
        self.paper_ref_candidates = []
        self.paper_total = None
        self.section = None
        self.in_formula_appendix = False
        self.current = None


class GlmOcrQuestionExtractor:
    extraction_method = QP_EXTRACTION_METHOD

    def extract(self, question_paper: dict) -> dict:
        state = _State(question_paper["documentId"])
        for element in elements_in_reading_order(question_paper):
            kind = element["element_type"]
            if kind == "text_block":
                if element["role"] == "heading":
                    self._handle_heading(element["text"], state)
                else:
                    self._handle_line(element["text"], state)
            elif kind == "figure":
                self._handle_figure(element, state)
            elif kind == "table":
                self._handle_table(element, state)
            elif kind == "equation":
                if state.current is not None and element.get("latex"):
                    self._append_text(
                        " $" + element["latex"].replace("\n", " ").strip() + "$", state)

        totals = {str(number): value for number, value in sorted(state.totals.items())}
        return {
            "schemaVersion": DRAFT_SCHEMA_VERSION,
            "extractionMethod": QP_EXTRACTION_METHOD,
            "reviewRequired": True,
            "paper": self._paper_meta(question_paper, state),
            "questions": [self._to_draft(raw, state) for raw in state.questions],
            "questionTotals": totals,
            "paperTotal": state.paper_total,
            "sectionTotals": dict(sorted(state.section_totals.items())),
            "frontMatterFigures": state.front_matter_figures,
            "warnings": state.warnings,
        }

    # ── heading handling ──────────────────────────────────────────────────────

    def _handle_heading(self, text, state):
        t = (text or "").strip()
        total = TOTAL_FOR_QUESTION.fullmatch(t)
        if total:
            self._record_total(total, state)
            return
        if re.fullmatch(r"SECTION ([A-Z])", t, re.I):
            state.section = t[-1]
            return
        if t.lower().startswith("list of data") or t.lower().startswith("formulae"):
            state.in_formula_appendix = True
            return
        if (t.upper() == "BLANK PAGE" or t == "Advice"
                or t.lower().startswith("instructions") or t.upper() == "INFORMATION"
                or t.lower().startswith("answer all")):
            return  # boilerplate headings
        # documented defect: question numbers promoted to Markdown headings
        colon = QUESTION_COLON.fullmatch(t)
        if colon and self._is_forward_question(int(colon.group(1)), state):
            self._open_question(int(colon.group(1)), "colon", colon.group(2), state)
            if t.startswith("*"):
                state.current.qwc = True
            state.warnings.append(
                "Q" + colon.group(1) + ": question number promoted to heading (opened from heading)")
            return
        space = QUESTION_SPACE.fullmatch(t)
        if space and self._is_forward_question(int(space.group(2)), state):
            self._open_question(int(space.group(2)), "space", space.group(3), state)
            if space.group(1):
                state.current.qwc = True
            state.warnings.append(
                "Q" + space.group(2) + ": question number promoted to heading (opened from heading)")
            return
        dot = QUESTION_DOT.fullmatch(t)
        if dot and self._is_forward_question(int(dot.group(2)), state) \
                and self._dot_stem_plausible(dot.group(3)):
            self._open_question(int(dot.group(2)), "dot", dot.group(3), state)
            if dot.group(1):
                state.current.qwc = True
            state.warnings.append(
                "Q" + dot.group(2) + ": question number promoted to heading (opened from heading)")
            return
        state.warnings.append("unclassified heading: " + t)

    def _is_forward_question(self, number, state):
        return state.current is None or number > state.current.number

    # ── line handling ─────────────────────────────────────────────────────────

    def _handle_line(self, raw_line, state):
        text = (raw_line or "").strip()
        if not text or NOISE.fullmatch(text) or TURN_OVER.fullmatch(text):
            return

        total = TOTAL_FOR_QUESTION.fullmatch(text)
        if total:
            self._record_total(total, state)
            return
        paper_total = TOTAL_FOR_PAPER.search(text)
        if paper_total:
            state.paper_total = int(paper_total.group(1))
            # "TOTAL FOR SECTION B=70 MARKS TOTAL FOR PAPER=80 MARKS" can share a line
            section_total = TOTAL_FOR_SECTION.search(text)
            if section_total:
                state.section_totals[section_total.group(1)] = int(section_total.group(2))
            return
        section_total = TOTAL_FOR_SECTION.search(text)
        if section_total:
            state.section_totals[section_total.group(1)] = int(section_total.group(2))
            return
        log_total = LOG_TOTAL.search(text)
        if log_total:
            state.paper_total = int(log_total.group(1))
            return
        self._extract_meta(text, state)

        if state.in_formula_appendix:
            return  # appendix text after "List of data…" is not question content

        # question starts — both numbering styles, sequence-checked
        colon = QUESTION_COLON.fullmatch(text)
        if colon and self._is_next_question(int(colon.group(1)), state):
            self._open_question(int(colon.group(1)), "colon", colon.group(2), state)
            if text.startswith("*"):
                state.current.qwc = True  # question-level QWC asterisk (*14)
            return
        space = QUESTION_SPACE.fullmatch(text)
        if space and self._is_next_question(int(space.group(2)), state):
            self._open_question(int(space.group(2)), "space", space.group(3), state)
            if space.group(1):
                state.current.qwc = True  # question-level QWC asterisk (*14)
            return
        dot = QUESTION_DOT.fullmatch(text)
        if dot and self._is_next_question(int(dot.group(2)), state) \
                and self._dot_stem_plausible(dot.group(3)):
            self._open_question(int(dot.group(2)), "dot", dot.group(3), state)
            if dot.group(1):
                state.current.qwc = True  # question-level QWC asterisk (*14)
            return

        if state.current is None:
            return  # content before the first question

        q = state.current

        combined = COMBINED_PART.fullmatch(text)
        if combined:
            part = _RawPart(combined.group(1))
            part.text = combined.group(3)
            q.parts.append(part)
            if text.startswith("*"):
                part.qwc = True
            return
        letter = LETTER_PART.fullmatch(text)
        if letter:
            part = _RawPart(letter.group(1))
            part.text = letter.group(2)
            if text.startswith("*"):
                part.qwc = True
                q.qwc = True
            q.parts.append(part)
            return
        roman = ROMAN_PART.fullmatch(text)
        if roman and q.parts:
            # parent = last LETTER-level part so "(ii)" after "b-i" → "b-ii"
            parent = None
            for candidate in reversed(q.parts):
                if "-" not in candidate.label:
                    parent = candidate
                    break
            if parent is not None:
                sub = _RawPart(parent.label + "-" + roman.group(1))
                sub.text = roman.group(2)
                q.parts.append(sub)
                return
        marks = MARKS_BLOCK.fullmatch(text)
        if marks:
            value = int(marks.group(1))
            if q.parts:
                q.parts[-1].marks = value
            else:
                q.answer_prompts.append(text)  # stem-level (N) — recorded, marks unknown
            return
        bare = BARE_LETTER.fullmatch(text)
        if bare and not q.parts:
            # detached MCQ option letters (defect: letters on their own lines after figures)
            q.option_letters.append(bare.group(1))
            q.bare_letter_lines = True
            return
        option = OPTION.fullmatch(text)
        if option and not q.parts:
            # candidate option — letter + whitespace required, validated in hindsight
            q.option_texts[option.group(1)] = option.group(2)
            return
        source = SOURCE_NOTE.fullmatch(text)
        if source:
            state.warnings.append("figure attribution Q" + str(q.number) + ": " + text)
            return
        if text.endswith("=") or re.fullmatch(r".*=\s*", text):
            prompt = re.sub(r"\s*=\s*$", "", text).strip()
            if q.parts:
                q.parts[-1].answer_prompts.append(prompt)
            else:
                q.answer_prompts.append(prompt)
            return

        self._append_text(" " + text, state)

    def _append_text(self, text, state):
        q = state.current
        if q is None:
            return
        if not q.parts:
            q.stem += text
        else:
            part = q.parts[-1]
            if part.text:
                part.text += " "
            part.text += text.strip()

    def _open_question(self, number, style, stem, state):
        raw = _RawQuestion(number, style)
        raw.section = state.section
        if stem is not None and stem.strip():
            raw.stem = stem.strip()
        state.current = raw
        state.questions.append(raw)

    def _is_next_question(self, number, state):
        if state.current is None:
            return number == 1
        return number == state.current.number + 1

    @staticmethod
    def _dot_stem_plausible(remainder):
        """Decimal-quantity guard for the "N." numbering style (2011-Jun,
        Specimen-2017). GLM-OCR line-breaks decimal quantities after the
        decimal point — "25.0 cm3" surfaces as "25. 0 cm3…" — and such a
        fragment must NOT open question 25. Every real dot-style stem in the
        audited corpus starts with a part label "(a)" or a capital letter;
        every observed decimal fragment starts with a digit. A rejected real
        stem fails safe: its text stays attached to the previous question
        where teacher review sees it."""
        return bool(remainder) and (remainder[0] == "(" or remainder[:1].isupper())

    def _record_total(self, total, state):
        state.totals[int(total.group(1))] = int(total.group(2))

    def _extract_meta(self, text, state):
        if "<" in text and "<table" in text.lower():
            # Cover metadata on newer templates lives inside HTML table cells; a
            # whole-table element defeats the ^...$ line regexes. Run the same
            # matchers against each printed cell line (tags split, entities kept
            # simple). Plain-line extraction below still runs first.
            for candidate in table_cell_lines(text):
                self._meta_from_line(candidate, state)
        self._meta_from_line(text, state)

    def _meta_from_line(self, text, state):
        for match in PAPER_REF.finditer(text):
            code = match.group(1)
            if state.meta[3] is None:
                state.meta[3] = code
            if code not in state.paper_ref_candidates:
                state.paper_ref_candidates.append(code)
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
        if state.meta[6] is None and "time:" in text.lower() and "minutes" in text.lower():
            state.meta[6] = re.sub(r"\s+", " ", text).strip()
        if state.meta[5] is None and DATE_LINE.fullmatch(text):
            state.meta[5] = text
        if state.specimen_year is None:
            specimen = SPECIMEN_YEAR.search(text)
            if specimen:
                state.specimen_year = specimen.group(1)
        if state.meta[1] is None and "international advanced" in text.lower():
            state.meta[1] = "IAL"

    def _session_label(self, state):
        """Session label resolution, first evidence wins: printed session line,
        then the printed exam date (month mapped to the session name — May and
        June sittings are the "June" session, Pearson's own session naming),
        then "Specimen <year>" for Sample Assessment Materials covers."""
        if state.meta[4] is not None:
            return state.meta[4]
        if state.meta[5] is not None:
            m = MONTH_YEAR.search(state.meta[5])
            if m:
                month = m.group(1)
                month = "June" if month.lower() == "may" \
                    else month[0].upper() + month[1:].lower()
                return month + " " + m.group(2)
        return None if state.specimen_year is None else "Specimen " + state.specimen_year

    def _paper_reference(self, state):
        """Paper-reference choice: prefer the FIRST 4-prefixed code — the
        International GCSE series this pipeline ingests — falling back to the
        first printed code. Deterministic and printed-faithful."""
        for code in state.paper_ref_candidates:
            if code.startswith("4"):
                return code
        return state.paper_ref_candidates[0] if state.paper_ref_candidates else None

    def _paper_meta(self, doc, state):
        board = state.meta[0]
        if board is None and state.meta[3] is not None:
            board = "Edexcel"
        return {
            "board": board,
            "qualification": state.meta[1],
            "subject": state.meta[2],
            "paperReference": self._paper_reference(state),
            "logNumber": state.log_number,
            "publicationCode": state.publication_code,
            "session": self._session_label(state),
            "examDate": state.meta[5],
            "duration": state.meta[6],
            "canonicalDocumentId": doc["documentId"],
        }

    # ── figures and tables ────────────────────────────────────────────────────

    def _handle_figure(self, figure, state):
        ref = {
            "elementId": figure["element_id"],
            "sourceName": figure["source_name"],
            "format": figure["format"],
            "url": figure["text"],
            "availability": FIGURE_UNAVAILABLE,
        }
        q = state.current
        if q is None or state.in_formula_appendix:
            if q is None:
                state.front_matter_figures.append(ref)
            else:
                q.figures.append(ref)
            return
        q.figures.append(ref)
        if q.parts:
            q.parts[-1].figures.append(ref)

    def _handle_table(self, table, state):
        # Front-matter cover tables carry the printed paper identity (paper
        # reference, exam date, session line). Extract it BEFORE the
        # current-question early return — that return skips everything else in
        # a cover table, and the identity regexes need printed cell lines, not
        # the element as a whole.
        for row in table["rows"]:
            for cell in row:
                for line in cell.split("\n"):
                    self._meta_from_line(re.sub(r"[ \t\r]+", " ", line).strip(), state)
        if not table["rows"] and table.get("text"):
            for candidate in table_cell_lines(table["text"]):
                self._meta_from_line(candidate, state)
        q = state.current
        if q is None:
            return  # front-matter cover table (1A variant)
        q.table_element_ids.append(table["element_id"])
        # MCQ grid: rows whose first cell is a bare letter A-D with text cells
        grid_options = []
        for row in table["rows"]:
            if len(row) >= 2 and re.fullmatch(r"[A-D]", row[0].strip()):
                grid_options.append((row[0].strip(), " ".join(row[1:]).strip()))
        if len(grid_options) >= 2 and not q.parts:
            for letter, text in grid_options:
                q.option_texts[letter] = text

    # ── completion ────────────────────────────────────────────────────────────

    def _to_draft(self, raw, state):
        short_doc = state.doc_id[:8] if state.doc_id else "doc"
        question_id = "q" + f"{raw.number:02d}" + "-" + short_doc

        # MCQ validation in hindsight: complete A–D set, no parts
        mcq = (not raw.parts) and set(raw.option_texts.keys()) >= {"A", "B", "C", "D"}
        if raw.bare_letter_lines and not mcq:
            state.warnings.append("Q" + str(raw.number) + ": detached option letters without option text")

        options = []
        if mcq:
            for letter in ("A", "B", "C", "D"):
                options.append({"letter": letter, "text": raw.option_texts.get(letter)})
        elif raw.option_texts:
            # incomplete option set folds back into stem (defect evidence)
            for letter, text in raw.option_texts.items():
                raw.stem += " " + letter + " " + text
            state.warnings.append("Q" + str(raw.number) + ": incomplete MCQ option set folded into stem")

        parts = []
        part_marks = 0
        all_marks_known = bool(raw.parts)
        for part in raw.parts:
            parts.append({
                "partId": question_id + "-p" + part.label,
                "label": part.label,
                "text": part.text.strip(),
                "marks": part.marks,
                "qwc": part.qwc,
                "figures": part.figures,
                "answerPrompts": part.answer_prompts,
                "confidence": 0.8 if part.marks is not None else 0.55,
            })
            if part.marks is not None:
                part_marks += part.marks
            else:
                all_marks_known = False

        total_from_paper = state.totals.get(raw.number)
        # honesty: part-sum / printed-total conflicts invalidate marksKnown
        marks_conflict = (all_marks_known and total_from_paper is not None
                          and part_marks != total_from_paper)
        if marks_conflict:
            state.warnings.append(
                "Q" + str(raw.number) + ": part marks sum (" + str(part_marks)
                + ") conflicts with printed total (" + str(total_from_paper) + ")")
        if all_marks_known:
            marks = part_marks
        elif total_from_paper is not None:
            marks = total_from_paper
        elif mcq:
            marks = 1
        else:
            marks = 0

        if mcq:
            confidence = 0.8
        elif all_marks_known:
            confidence = 0.75
        elif total_from_paper is not None:
            confidence = 0.6
        else:
            confidence = 0.45

        return {
            "questionId": question_id,
            "number": raw.number,
            "numberingStyle": raw.numbering_style,
            "section": raw.section,
            "stem": raw.stem.strip(),
            "mcq": mcq,
            "options": options,
            "parts": parts,
            "figures": raw.figures,
            "tableElementIds": raw.table_element_ids,
            "marks": marks,
            "marksKnown": (all_marks_known or total_from_paper is not None) and not marks_conflict,
            "qwc": raw.qwc,
            "answerPrompts": raw.answer_prompts,
            "confidence": confidence,
        }
