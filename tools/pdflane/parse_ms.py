"""Deterministic MS mark-grid parser over the pdftotext -layout base layer.

Why this layer: the text layer contains the merged-cell "Total N marks" rows
that every table detector loses (evidence: FAILSAFE_PLAN F2).

Row grammar (layout text):
  Question
                        Answer                    Notes            Marks
  number
  1 a      M1      beaker        Accept phonetic spellings        1
           M2      water                                          1
     b   i    M1   (filter) paper Accept phonetic spellings        1
  (ii)     A1   shift to right  Allow more ammonia / products    1
                                                                 Total 10 marks

Handles the observed deterministic artifacts:
  - marks column wrapped onto a continuation line (provisional point, then
    marks recovered from the continuation tail)
  - label split across lines ("M" ending a line, its digit starting the next)
  - guidance rows ("M2 dependent on M1", "Do not award M3 ...") classified as
    guidance notes, NOT points, but their label tokens are accounted
  - parenthesized sub-parts "(ii)"

FAILSAFE ACCOUNTING: every raw [MA]<n> token in the layout must end up in
exactly one bucket: parsed point | guidance note | unclassified (flagged).
Nothing silently disappears. Deterministic throughout.
"""
import json
import re

TOTAL_RE = re.compile(r"^\s*Total\s+(\d{1,3})\s+marks?\s*$", re.I)
TOTAL_BARE_RE = re.compile(r"^\s*Total\s+(\d{1,3})\s*$")          # 4CH1: 'Total 7'
TOTAL_UPPER_RE = re.compile(r"^\s*TOTAL\s{2,}(\d{1,3})\s*$")       # 4CH0 2C: 'TOTAL   7'
TOTAL_Q_RE = re.compile(r"Total\s+marks\s+for\s+Question\s+(\d{1,2})\s*=\s*(\d{1,3})\s*$", re.I)
TOTAL_Q_SHORT_RE = re.compile(r"Total\s+for\s+Q\s?(\d{1,2})\s*=\s*(\d{1,3})\s*$", re.I)  # Nov 2020 COVID: 'Total for Q1 = 5'
TOTAL_IMPLICIT_RE = re.compile(r"^\s*total\s+for\s+question\s*=\s*(\d{1,3})\s*$", re.I)  # 4CH1 2024: 'total for question = 5' — no question number in row; assigned to the open question by sequence
TOTAL_SPLIT_RE = re.compile(r"^(?P<pre>.*?\S)?\s*Tota(?:l)?\s*$")  # 4CH1 2019: number on next line ('Tota' = clipped)
TOTAL_SPLIT_NUM_RE = re.compile(r"^(?P<pre>.*?\S)?\s{2,}(?P<n>\d{1,3})\s*$|^(?P<bare>\d{1,3})\s*$")
NOTE_KW_TAIL_RE = re.compile(r"\b(ALLOW|ACCEPT|REJECT|IGNORE)\s*$", re.I)
NOTE_KW_START_RE = re.compile(
    r"^\s*(ALLOW|ACCEPT|REJECT|IGNORE|Do not accept|Do not allow|"
    r"Ignore|Accept)\b", re.I)
# --- label-less grid rows (4CH1 style / label-less 4CH0 rows) ---
QPART_PAREN_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+\((?P<part>[a-z])\)\s*(?:\(\s*(?P<sub>[ivx]+)\s*\)\s*)?(?P<rest>\S.*)$")
# G1.2 (RC-A): opener-only variants — "1 (a)" / "5 a" with NO trailing text
# (2012+ table grids print the question/part opener alone; the marks cell and
# the answer table content sit on their own lines). The opener still opens
# the question/part block so the displaced cells attach to it.
QPART_PAREN_SOLO_RE = re.compile(r"^\s*(?P<qn>\d{1,2})\s+\((?P<part>[a-z])\)\s*$")
QPART_BARE_SOLO_RE = re.compile(r"^\s*(?P<qn>\d{1,2})\s+(?P<part>[a-z])\s*$")
QPART_BARE_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+(?P<part>[a-z])\s+(?:(?P<sub>[ivx]{1,4})\s+)?(?P<rest>\S.*)$")
PART_PAREN_RE = re.compile(r"^\s*\((?P<part>[a-z])\)\s+(?:\(\s*(?P<sub>[ivx]+)\s*\)\s*)?(?P<rest>\S.*)$")
# G1.3-r3 (RC-C round 3): COMPACT part+sub opener with no space — '(c)(i)
# (Iron (III) oxide) loses oxygen   1' (4CH1 1CR Jan 2020 q11(c)(i) p18).
# PART_PAREN_RE requires \s+ after the part letter, so the opener row merged
# into the PREVIOUS block's text and the whole (c) letter scored under (b)
# (signature ms b13 vs qp b5, c none).
PART_PAREN_COMPACT_RE = re.compile(
    r"^\s*\((?P<part>[a-h])\)\s*\(\s*(?P<sub>[ivx]+)\s*\)\s*(?P<rest>\S.*)$")
PART_BARE_RE = re.compile(r"^\s{1,8}(?P<part>[a-z])\s+(?:(?P<sub>[ivx]{1,4})\s+)?(?P<rest>\S.*)$")
# G1.3-r3 (RC-C round 3): column-0 bare part opener. pdftotext -layout can
# print the part letter at the LEFT MARGIN when the question-number column is
# empty on a page: banner rows ('f   In part (f):', 4CH0 1C Jun 2015 q8 p21)
# and scored rows ('d   i   silica ... 1'). PART_BARE_RE requires 1-8 leading
# spaces, so these never matched: the whole letter block inherited the
# PREVIOUS letter (letter-shift signature ms e3->8 / qp f5->None) or the row
# fell to unclassified. Letters constrained to a-h; the sequential guard
# (next/same letter, question open) lives at the call site.
PART_BARE_COL0_RE = re.compile(
    r"^(?P<part>[a-h])\s{2,}(?:(?P<sub>[ivx]{1,4})\s{2,})?(?P<rest>\S.*)$")
# G1.3-r3 (RC-C round 3): qn + bare roman sub lead with an EMPTY part column
# ('5   iv   oxygen / O2   1', 4CH0 1C Jun 2013 q5(a) p10 continuation page).
# QPART_BARE_RE needs a part letter ('5 a'); SUB_BARE_RE needs leading spaces
# and no qn. Neither matched, so the whole sub-block was dropped and the
# following rows inherited the PREVIOUS sub's label (ms a5 vs qp a6).
QPART_BARE_SUB_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+(?P<sub>[ivx]{1,4})\s{2,}(?P<rest>\S.*)$")
# G1.3-r3 (RC-C round 3): bare part letter ALONE (no qn, no text, no marks
# cell — 'b' on its own line, 4CH1 1C Jun 2019 q9(b) p13: the question
# continues from the previous page so the qn column is empty and the marks
# cell sits on a following note row). Opens the part aggregate with the same
# semantics as QPART_*_SOLO; the end-of-parse resolution fills or demotes it.
PART_BARE_SOLO_RE = re.compile(r"^\s{1,8}(?P<part>[a-h])\s*$")
PART_BARE_SOLO_COL0_RE = re.compile(r"^(?P<part>[a-h])\s*$")
# G1.3-r3 (RC-C round 3): paren part letter ALONE without a question number
# ('   (c)' on its own line, 4CH0 1C Jan 2018 q12(c) p18). QPART_PAREN_SOLO_RE
# needs the qn — dropped here, the whole (c) block inherited (b). Same
# aggregate semantics as the bare form.
PART_PAREN_SOLO_QNLESS_RE = re.compile(r"^\s{0,8}\((?P<part>[a-h])\)\s*$")
SUB_PAREN_RE = re.compile(r"^\s*\(\s*(?P<sub>[ivx]+)\s*\)\s+(?P<rest>\S.*)$")
# G1.3-r3 (RC-C round 3): parenthesized ARABIC option leads — matching/
# multiple-statement MS blocks print numbered answer options '(2) time / how
# long ... 1' (4CH0 1C Jun 2013 q8(b), options (2)-(5), one mark each).
# SUB_PAREN_RE only accepts romans, so the tail-less wrapped option rows fell
# out of the block (letter short by one mark). Scores under the open part;
# the end-of-parse resolution fills a deferred cell from a following note row.
SUB_PAREN_NUM_RE = re.compile(
    r"^\s*\(\s*(?P<sub>\d{1,2})\s*\)\s+(?P<rest>\S.*)$")
SUB_BARE_RE = re.compile(r"^\s{1,8}(?P<sub>[ivx]{1,4})\s{2,}(?P<rest>\S.*)$")
ROMAN_RE_MS = re.compile(r"^[ivx]{1,4}$")

# --- G1.3 (RC-C letter-level residual): opener rows whose ONLY content is
# the marks cell — the answer body is empty (a table / step rows follow on
# the next lines) and the printed marks sit on the opener line itself:
#   '4 (a) (i)                                     3'   (4CH1 1C Jan 2020 q4 a-i)
#   '  (b)   (i)                                   2'   (4CH1 1C Jun 2021 q7 b-i)
#   '        (ii)                                  3'   (4CH1 1C Jan 2020 q4 b-ii)
#   '7        (ii)      •   substitute ...   2'         (4CH1 1C Jun 2021 q7 b-ii)
# Previously nothing matched (QPART/PART/SUB regexes demand non-empty rest,
# and a bare rest='2' lost its marks semantics via tail_marks' \s{2,} rule),
# so the whole sub-part was dropped -> QP-EXTRA-SUB / PART-MARKS-MISMATCH.
# The tail digit is column-disciplined (marks column, never the answer
# column) so MCQ answer-value rows keep their existing handling.
OPENER_MARKS_QPS_RE = re.compile(   # qn + (part) + ((sub))? + tail, empty body
    r"^\s*(?P<qn>\d{1,2})\s+\((?P<part>[a-z])\)\s*"
    r"(?:\(\s*(?P<sub>[ivx]+)\s*\)\s*)?(?P<mk>\d{1,3})\s*$")
OPENER_MARKS_PS_RE = re.compile(    # (part) + ((sub))? + tail, empty body
    r"^\s*\((?P<part>[a-z])\)\s*(?:\(\s*(?P<sub>[ivx]+)\s*\)\s*)?"
    r"(?P<mk>\d{1,3})\s*$")
OPENER_MARKS_QS_RE = re.compile(    # qn + ((sub)) + [content] + tail (no part)
    r"^\s*(?P<qn>\d{1,2})\s+\(\s*(?P<sub>[ivx]+)\s*\)\s*"
    r"(?P<rest>\S.*?)?\s{2,}(?P<mk>\d{1,3})\s*$")
OPENER_MARKS_S_RE = re.compile(     # ((sub)) + tail, empty body (no qn/part)
    r"^\s*\(\s*(?P<sub>[ivx]+)\s*\)\s*(?P<mk>\d{1,3})\s*$")


def collapse_spaced(s):
    """Collapse letter-spaced glyph runs ('e v a p o r a t i o n' ->
    'evaporation', '( i )' -> '(i)') produced by wide-tracking fonts in some
    mark schemes (4CH1 2019). Fires only when EVERY token is a single
    character (>= 3 tokens), so normal sentences never match."""
    tokens = s.split(" ")
    if len(tokens) >= 3 and all(len(t) == 1 for t in tokens):
        return "".join(tokens)
    return s


MARKS_CELL_MAX = 6  # a printed per-row marks cell in these MSs never exceeds 6


def tail_marks(rest):
    """(matched, value) for a trailing marks cell; values >6 are data
    artifacts (table numbers), not marks. A zero value is never a marks cell
    ('400 000' arithmetic tails end in '000')."""
    mt = MARKS_TAIL_RE.match(rest)
    if not mt:
        return None, None
    v = int(mt.group("mk"))
    return mt, (v if 0 < v <= MARKS_CELL_MAX else None)


# G1.2 (RC-B): the marks cell is a table COLUMN — in -layout text it sits at
# a stable right-edge position. A trailing digit far LEFT of the established
# marks column is table data ('1  1  3' fraction rows under an OR), never a
# marks cell (evidence: 4CH0 1C June 2011 q5 phantom +3 point, sum 12 vs 10).
MARKS_COL_MIN = 48        # real marks columns sit >= 73 in the corpus; data
                          # columns (fractions/tables) sit <= 33
MARKS_COL_SLACK = 12      # one-sided tolerance: reject tails far LEFT only


def tail_marks_at(line, marks_col):
    """Column-disciplined tail_marks: `line` is the full layout line, so the
    tail's absolute column can be checked against the page's established
    marks column. Returns (mt, value) or (None, None) when rejected."""
    mt = MARKS_TAIL_RE.match(line.rstrip())
    if not mt:
        return None, None
    v = int(mt.group("mk"))
    if not 0 < v <= MARKS_CELL_MAX:
        return None, None
    col = len(line.rstrip()) - len(mt.group("mk"))
    if marks_col is not None:
        if col < marks_col - MARKS_COL_SLACK:
            return None, None
    elif col < MARKS_COL_MIN:
        return None, None
    return mt, v


def _next_content_line(raw_lines, idx):
    """First non-blank, non-furniture line after idx (G1.2 RC-E lookahead)."""
    for j in range(idx + 1, len(raw_lines)):
        t = raw_lines[j].strip()
        if not t:
            continue
        cleaned = clean_line(raw_lines[j])
        return cleaned.strip() if cleaned is not None else None
    return None


def _next_substantive_line(raw_lines, idx):
    """First non-blank, non-furniture, non-note-led line after idx (G1.2
    deferred-cell lookahead: note-column wraps between the displaced cell and
    the true row are skipped)."""
    for j in range(idx + 1, len(raw_lines)):
        t = raw_lines[j].strip()
        if not t:
            continue
        cleaned = clean_line(raw_lines[j])
        if cleaned is None:
            continue
        st = cleaned.strip()
        if NOTE_KW_START_RE.match(st):
            continue
        return st
    return None


def _labeled_row_ahead(raw_lines, idx, window=3):
    """G1.3 (RC-C): True when a complete M/A-labeled row starts within the
    next `window` plain continuation lines (blank/furniture lines skipped)
    WITHOUT a block opener intervening.

    Used to decide whether a displaced merged marks cell belongs to the next
    labeled row (redirect via pending_marks_next) or opens its own deferred
    point (legacy behavior, Jan-2012 two-mark blocks). Evidence split:
    4CH0 1C Jun 2012 q6(c)(i) 'mass of isotopes ... 1' has 'M2 compared to...'
    two continuation lines below -> the cell IS M2's (redirect);
    4CH0 2C Jan 2012 q1(b)(ii) 'proton number ... 1' has only note wraps
    below -> the cell is an independent mark point (spawn);
    4CH0 1C Jun 2012 q4(d) 'ferric fluoride / FeF3 ... 1' has the '(e)'
    block opener before any labeled row -> the cell belongs to the CURRENT
    block (spawn) — the lookahead must not cross block boundaries."""
    seen = 0
    j = idx
    while j + 1 < len(raw_lines) and seen < window:
        j += 1
        t = raw_lines[j].strip()
        if not t:
            continue
        cleaned = clean_line(raw_lines[j])
        if cleaned is None:
            continue
        seen += 1
        st = cleaned.strip()
        if re.match(r"^\s*[MA]\d{1,2}\b", st):
            return True
        if (QPART_PAREN_RE.match(st) or QPART_BARE_RE.match(st)
                or QPART_PAREN_SOLO_RE.match(st) or QPART_BARE_SOLO_RE.match(st)
                or PART_PAREN_RE.match(st) or PART_BARE_RE.match(st)
                or SUB_PAREN_RE.match(st) or SUB_BARE_RE.match(st)):
            return False  # block boundary: no same-block labeled row follows
    return False


def _is_opener_shaped(st):
    """True when a stripped line opens a question/part/sub point row (G1.2
    RC-E: the deferred marks cell attaches to the next opener's point)."""
    if not st:
        return False
    if LABEL_RE.match(st) and (LABEL_RE.match(st).group("labelbase")):
        return True
    return bool(QPART_PAREN_RE.match(st) or QPART_BARE_RE.match(st)
                or QPART_PAREN_SOLO_RE.match(st) or QPART_BARE_SOLO_RE.match(st)
                or PART_PAREN_RE.match(st) or PART_BARE_RE.match(st)
                or SUB_PAREN_RE.match(st) or SUB_BARE_RE.match(st))


LABEL_RE = re.compile(
    r"^(?P<lead>[\s.(]*)"
    r"(?:(?P<qn>\d{1,2})[\s().]*)?"
    r"(?:(?P<part>[a-z])[\s().]*)?"
    r"(?:(?P<sub>i{1,3}|iv|v)[\s().]*)?"
    r"(?P<labelbase>[MA])(?P<labelnum>\d{0,2})"
    # G1 upgrade: the label token must terminate at whitespace/'('/EOL —
    # word-initial letters ('Ask The Expert', 'Ammonia', 'Mark scheme')
    # previously matched as bare M/A labels and misfired the pending-label
    # machinery (evidence: 4CH0 boilerplate 'point-row-before-any-question')
    r"(?=[\s(]|$)"
    r"(?P<rest>.*)$")
# G1 upgrade: 'any N for M each' capped alternative groups (e.g. 4CH0 8b(i)
# 'Any two for 1 each' — six 1-mark rows, max 2 awardable). Detected on the
# note line that closes the group; membership = the current part-block's rows.
ANY_N_FOR_EACH_RE = re.compile(
    r"\bAny\s+(?P<n>\d{1,2}|two|three|four|five|six)\s+for\s+"
    r"(?P<per>\d{1,2})\s+each\b", re.I)
WORD_NUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
# G1 upgrade: grid header rows print as one line on content pages
# ('Answer   Notes   Marks') — furniture, not an unclassified row
GRID_HEADER_RES = [
    re.compile(r"^Answer\s{2,}Notes(\s{2,}Marks)?\s*$", re.I),
    re.compile(r"^Question\s{2,}Answer\s{2,}Notes(\s{2,}Marks)?\s*$", re.I),
    # G1.2 (RC-A): the 2012+ TABLE grid family — header row printed as one
    # line with column gaps ('Expected Answer ... Accept ... Reject ... Marks',
    # 'Answer ... Accept ... Reject ... Marks', 'Answer ... Notes ... Marks').
    # Pages carrying ONLY this header (no M/A labels, no 'Total' row — e.g.
    # 4CH0 2C Jan 2012) were skipped whole as furniture by is_grid_page,
    # dropping every point row on the page (evidence: 201201 q1 sum 1 vs 10;
    # 201401 q3/q10 zero capture).
    re.compile(r"^Expected\s+Answer\s{2,}.*\bAccept\b.*\bMarks\b\s*$", re.I),
    re.compile(r"^Answer\s{2,}.*\bAccept\b.*\bReject\b.*\bMarks\b\s*$", re.I),
    re.compile(r"^Answer\s{2,}.*\bNotes\b.*\bMarks\b\s*$", re.I),
]
MARKS_TAIL_RE = re.compile(r"^(?P<body>.*?)\s{2,}(?P<mk>\d{1,3})\s*$")
GUIDANCE_RE = re.compile(
    r"(dependent|independent|can\s+(?:still\s+)?(?:be\s+)?award|can\s+score|"
    r"Do\s+not\s+award|do\s+not\s+award|do\s+not\s+allow|Reject|Max\s*\d|"
    r"only\s+[MA]\d|no\s+[MA]\d|for\s+[MA]\d|is\s+for)", re.I)
WITNESS_RES = [
    re.compile(r"total\s+marks?\s+for\s+this\s+paper\s+is\s+(\d{2,3})", re.I),
    re.compile(r"TOTAL\s*:\s*(\d{2,3})\s*MARKS", re.I),
    re.compile(r"TOTAL\s+FOR\s+PAPER\s*=\s*(\d{2,3})\s*MARKS", re.I),
]
FURNITURE_EXACT = {"PMT", "Question", "number", "Answer", "Notes", "Marks",
                   "Questio", "numbe", "n", "r", "OR"}
FURNITURE_RES = [
    re.compile(r"^Mark Scheme \(Results\)$", re.I),
    re.compile(r"^(January|June|November|October|March|Specimen)\s+\d{4}$", re.I),
    re.compile(r"^INTERNATIONAL\s+GCSE\b.*", re.I),
    re.compile(r"^\*P[0-9A-Z]+\*$"),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.I),
]
MAX_QN = 25
ROMAN = {"i", "ii", "iii", "iv", "v"}


def clean_line(s):
    t = s.rstrip()
    st = t.strip()
    if st in FURNITURE_EXACT:
        return None
    for r in FURNITURE_RES:
        if r.match(st):
            return None
    for r in GRID_HEADER_RES:
        if r.match(st):
            return None
    return t


PAGE_GRID_TOKEN_RE = re.compile(r"\b[MA]\d{1,2}\b")
PAGE_TOTAL_RE = re.compile(r"\bTotal\b", re.I)


def is_grid_page(text):
    """G1 upgrade: a page carrying no [MA]<n> token, no total row and no grid
    header row is document furniture (cover, boilerplate, publications) —
    never mark-grid content. Skipping it whole removes ~30 unclassified noise
    rows per old-spec MS while guaranteeing zero label tokens are lost (a
    non-grid page has none by definition). Deterministic.

    The header row is required as a third signal because label-split layouts
    (4CH0 2012+: bare 'M' on the row, its digit on the next) contain no
    complete [MA]<n> token on some genuine grid pages (evidence: 4CH0 1C
    jan2012 p16 lost whole question parts)."""
    if PAGE_GRID_TOKEN_RE.search(text) or PAGE_TOTAL_RE.search(text):
        return True
    for ln in text.splitlines():
        st = ln.strip()
        for r in GRID_HEADER_RES:
            if r.match(st):
                return True
    # G1.3 (RC-C): MS continuation pages can carry ONLY label-less sub-part
    # rows — MCQ answer rows '(ii)   D yellow   1' + incorrect-option notes
    # carry no [MA]<n> token, no total row and no grid header, yet are real
    # mark content (evidence: 4CH1 1C Jun 2021 q6(b)(ii) p13 lost whole ->
    # MS-PART-NO-POINTS + letter-sum mismatch). A page showing an
    # opener-shaped row WITH a trailing marks digit is grid content.
    for ln in text.splitlines():
        st = ln.strip()
        if not re.search(r"\d{1,3}\s*$", st):
            continue
        if SUB_PAREN_RE.match(st) or PART_PAREN_RE.match(st) \
                or QPART_PAREN_RE.match(st) or OPENER_MARKS_S_RE.match(st) \
                or OPENER_MARKS_PS_RE.match(st):
            return True
    return False


def parse_pages(pages, qp_totals=None):
    """pages: [{"page": n, "text": str}] from pdftotext -layout split.

    G1 upgrade: qp_totals (optional {question_number: printed_total} from the
    QP parse) enables (a) displaced-marks-cell recovery against the QP total
    when the MS total row cannot close, and (b) QP-aware arithmetic_ok.
    """
    questions = []
    cur = None
    cur_point = None
    pending_label = None   # (part, sub) when a bare M/A awaits its digit
    pending_total = False  # 'Total' seen; the number sits on the next line
    last_part = None       # last explicit part letter (for sub-row inheritance)
    point_seq = 0          # per-question synthesized label counter
    group_start = 0        # G1 upgrade: index into cur["points"] where the
    #                        current explicit part-block began (capped-group
    #                        membership = points[group_start:])
    cur_group = None       # G1 upgrade: (part, sub) of the last explicitly
    #                        printed opener row; part-less scored rows inherit
    #                        it so pool/capped-group part scoping works
    unclassified = []
    guidance = []          # {page, text, labels}
    witnesses = []
    buckets = {"point": 0, "guidance": 0, "unclassified": 0,
               "continuation": 0, "furniture_pages": 0}

    def ensure_question(qn):
        nonlocal cur, last_part, point_seq, group_start, cur_group, \
            pending_marks_next
        closed = any(x["number"] == qn and x["total_row"] is not None
                     for x in questions)
        if closed:
            return  # a closed question number never reopens (layout artifacts
            # can reprint a question row after later questions)
        if cur is None or cur["number"] != qn:
            cur = {"number": qn, "total_row": None, "total_row_page": None,
                   "points": [], "guidance": [], "pages": set(),
                   "capped_groups": []}
            questions.append(cur)
            last_part = None
            point_seq = 0
            group_start = 0
            cur_group = None
            # G1.3 (RC-C): a displaced merged marks cell belongs to the
            # question it was printed in. If its intended row absorbed as
            # prose instead of creating a point, an unexpired pending value
            # poisoned the NEXT question's first provisional point
            # (evidence: 4CH1 1C Jun 2020 q5 lone '2' leaked into q6
            # M2(a-i) -> letter sum 8 vs 6; latent in G1.2, exposed once
            # the OM branch recovered q6(c)(iii)'s real 2-mark cell).
            pending_marks_next = None

    def new_point(part, sub, chunks, marks, pageno, answer_col=None):
        nonlocal cur_point, point_seq, pending_marks_next
        point_seq += 1
        deferred_flag = False
        if marks is None and pending_marks_next is not None:
            # G1.2 (RC-A/RC-E): a lone marks cell displaced ABOVE this opener
            # row (vertically centered merged cell) supplies its marks
            marks = pending_marks_next
            deferred_flag = True
        pending_marks_next = None  # consumed or expired either way (no leaks)
        pt = {"label": "P%d" % point_seq, "part": part, "sub": sub,
              "text": chunks[:1], "notes": chunks[1:],
              "marks": marks, "page": pageno, "answer_col": answer_col}
        if deferred_flag:
            pt["_from_deferred"] = True
        cur["points"].append(pt)
        cur["pages"].add(pageno)
        cur_point = pt
        return pt

    def _consume_pending(pt):
        """G1.2 (RC-A/RC-E): apply a deferred lone marks cell to a directly
        constructed point still lacking marks (LABEL-path sites bypass
        new_point). Marks the point as a deferred-cell block opener: further
        tail-less M/A rows in the same block are marking STEPS (notes), not
        independently scored points. The pending value expires after the next
        point creation regardless (consumed or not) — no leaks."""
        nonlocal pending_marks_next
        if pt.get("marks") is None and pending_marks_next is not None:
            pt["marks"] = pending_marks_next
            pt["_from_deferred"] = True
        pending_marks_next = None
        return pt

    def _discipline(mt, mk, line):
        """G1.2 (RC-B): column-discipline a matched marks tail against the
        page's established marks column; establish the column on first
        acceptance. Returns (mt, mk) — (None, None) when rejected."""
        nonlocal marks_col
        if mt is None:
            return None, None
        tcol = len(line.rstrip()) - len(mt.group("mk"))
        if marks_col is not None:
            if tcol < marks_col - MARKS_COL_SLACK:
                return None, None
        elif tcol < MARKS_COL_MIN:
            return None, None
        marks_col = tcol
        return mt, mk

    prev_line_guidance = False  # G1 upgrade: note-wrap adjacency tracker
    marks_col = None        # G1.2 (RC-B): established marks-column position, per page
    pending_marks_next = None  # G1.2 (RC-A/E): lone cell deferred to the next opener
    for p in pages:
        pageno = p["page"]
        raw_text = p["text"]
        # G1 upgrade: whole-page furniture skip (see is_grid_page)
        if not is_grid_page(raw_text):
            buckets["furniture_pages"] += 1
            continue
        raw_lines = raw_text.splitlines()
        marks_col = None  # column geometry is a per-page property
        for idx, raw in enumerate(raw_lines):
            carry_guidance = prev_line_guidance   # flag from the previous line
            prev_line_guidance = False
            # note-column continuity: a line directly following one that ends
            # with ALLOW/ACCEPT/REJECT/IGNORE is that note's value, never a
            # scored point (adjacency read from the RAW text, so furniture
            # lines in between do not break it)
            prev_note_open = idx > 0 and bool(
                NOTE_KW_TAIL_RE.search(raw_lines[idx - 1].strip()))
            line = clean_line(raw)
            if line is None:
                continue
            st = line.strip()
            lbl_n = len(re.findall(r"\b[MA]\d{1,2}\b", st))  # per-line accounting unit

            m = TOTAL_RE.match(line)
            if not m:
                mq = TOTAL_Q_RE.search(st)
                if mq:
                    ensure_question(int(mq.group(1)))
                    m = True  # treat as matched total row below
                    total_val = int(mq.group(2))
                else:
                    msq = TOTAL_Q_SHORT_RE.search(st)
                    if msq:
                        ensure_question(int(msq.group(1)))
                        m = True
                        total_val = int(msq.group(2))
            else:
                total_val = int(m.group(1))
            if not m:
                mu = TOTAL_UPPER_RE.match(line)
                if mu:
                    m = True
                    total_val = int(mu.group(1))
            if not m:
                mb = TOTAL_BARE_RE.match(line)
                if mb:
                    m = True
                    total_val = int(mb.group(1))
            if not m:
                mi = TOTAL_IMPLICIT_RE.match(line)
                if mi:
                    m = True
                    total_val = int(mi.group(1))
            if m:
                if cur is not None and cur["total_row"] is None:
                    cur["total_row"] = total_val
                    cur["total_row_page"] = pageno
                    cur_point = None
                    pending_label = None
                else:
                    unclassified.append({"page": pageno, "text": st,
                                         "reason": "total-row-without-open-question"})
                    buckets["unclassified"] += len(re.findall(r"\b[MA]\d{1,2}\b", st))
                continue

            # --- split total: 'Total' ends this line, number sits on the next ---
            tsplit = TOTAL_SPLIT_RE.match(line)
            if tsplit:
                pending_total = True
                pre = (tsplit.group("pre") or "").strip()
                if pre and cur_point is not None:
                    (cur_point["notes"] if cur_point["text"] else cur_point["text"]).append(pre)
                continue
            if pending_total:
                nm = TOTAL_SPLIT_NUM_RE.match(line)
                pending_total = False
                opener = QPART_PAREN_RE.match(line) or QPART_BARE_RE.match(line)
                if nm and cur is not None and not opener:
                    # anything opener-shaped is a grid row whose marks tail
                    # must not be eaten as the total
                    val = int(nm.group("n") or nm.group("bare"))
                    if cur["total_row"] is None:
                        cur["total_row"] = val
                        cur["total_row_page"] = pageno
                    pre = (nm.group("pre") or "").strip()
                    if pre:
                        unclassified.append({"page": pageno, "text": pre,
                                             "reason": "pre-total-fragment"})
                    continue
                # pattern broken: fall through and process the line normally

            for w in WITNESS_RES:
                wm = w.search(st)
                if wm:
                    witnesses.append({"page": pageno, "value": int(wm.group(1)), "text": st})

            # --- pending bare-label digit completion: "M" ended previous line,
            #     this line starts with its digit(s) ---
            if pending_label is not None:
                if QPART_PAREN_RE.match(line) or QPART_BARE_RE.match(line) \
                        or QPART_PAREN_SOLO_RE.match(line) \
                        or QPART_BARE_SOLO_RE.match(line):
                    pending_label = None  # a question opener wins; the bare
                    # label's digit never arrived (label-split misfire)
                else:
                    dm = re.match(r"^(?P<d>\d{1,2})(?:\s{2,}(?P<rest>.*))?$", st)
                    if dm:
                        part, sub, prev = pending_label
                        pending_label = None
                        pt = {"label": prev["base"] + dm.group("d"), "part": part,
                              "sub": sub, "text": list(prev["text"]),
                              "notes": list(prev["notes"]), "marks": prev["marks"],
                              "page": pageno}
                        if dm.group("rest"):
                            pt["notes"].append(dm.group("rest").strip())
                        if cur is not None:
                            _consume_pending(pt)
                            cur["points"].append(pt)
                            if prev.get("opener"):
                                # G1 upgrade: the completed opener row starts a
                                # new part-block (capped-group membership)
                                group_start = len(cur["points"]) - 1
                            cur["pages"].add(pageno)
                            buckets["point"] += lbl_n
                            cur_point = pt
                        else:
                            buckets["unclassified"] += lbl_n
                        continue
                    pending_label = None  # pattern broken; fall through

            lm = LABEL_RE.match(line)
            if lm and lm.group("labelbase") and not lm.group("labelnum") \
                    and lm.group("rest") and re.match(r" \S", lm.group("rest")):
                # G1.2: a BARE label token followed by a SINGLE space + text
                # ('(c) (i) A discussion which refers to...') is an answer
                # sentence whose first word starts with A/M — columnar bare
                # labels either carry no same-line text or separate it by 2+
                # spaces. Fall through to the grid-row paths (evidence: 4CH1
                # 2C June 2021 q5(c)(i) opener hijacked as bare-A; the
                # pending-label machinery then discarded its 6-mark point).
                lm = None
            elif lm and lm.group("labelbase") and not lm.group("labelnum") \
                    and lm.group("rest"):
                mt_bare = MARKS_TAIL_RE.match(lm.group("rest"))
                if mt_bare and not (mt_bare.group("body") or "").strip():
                    # G1.2: '(ii)    A         1' — a bare letter followed only
                    # by whitespace and a marks digit is an ANSWER VALUE row
                    # (option letter in the answer column of a matching MS),
                    # never a split label. Fall through so the sub-part path
                    # scores it (evidence: 4CH0 2C Jan 2012 q2 (ii) lost).
                    lm = None
            if lm and lm.group("labelbase") and lm.group("rest") is not None:
                qn = int(lm.group("qn")) if lm.group("qn") else None
                if qn is not None:
                    if qn > MAX_QN:
                        # answer value like "28", not a question number
                        qn = None
                    else:
                        ensure_question(qn)
                if cur is None:
                    unclassified.append({"page": pageno, "text": st,
                                         "reason": "point-row-before-any-question"})
                    buckets["unclassified"] += lbl_n
                    continue
                part = lm.group("part")
                sub = lm.group("sub") if lm.group("sub") in ROMAN else None
                if part in ("i", "v", "x"):
                    # '(ii)'-style lead consumed as part: shift to sub and
                    # inherit the real part letter from the open question
                    sub = (part + (sub or "")) if sub else part
                    part = last_part
                base = lm.group("labelbase")
                num = lm.group("labelnum")
                rest = lm.group("rest") or ""
                # G1.2 (RC-E): an explicitly printed sub lead with no part
                # letter ('(iii)   M1 fraction A refinery gases', 4CH1 style)
                # inherits the open part — the sub belongs to the last printed
                # part block, same semantics as the '(ii)'-shift above.
                if part is None and sub is not None and last_part is not None:
                    part = last_part
                mt = MARKS_TAIL_RE.match(rest)
                if mt:
                    # G1.2 (RC-B): reject tails far left of the established
                    # marks column (fraction/table data), keep value semantics
                    mt, _ = _discipline(mt, None, line)

                if num == "":
                    # bare M/A: digit arrives on the next line; marks may be
                    # at this line's end or still pending.
                    # G1 upgrade: part-less bare labels inherit the open part
                    # block (same rule as completed label rows) — otherwise
                    # every second row of a label-split pair ('M' + digit
                    # lines) lands as an orphan point with no part (evidence:
                    # 4CH0 q6c M2, q7 a-i M2 / b M2 all part-less). An
                    # explicitly-printed part/sub OPENS the block immediately
                    # so following inherited rows attach to THIS block, and
                    # the opener flag rides through to the completion.
                    bare_opener = part is not None or sub is not None
                    if part is None and sub is None and cur_group is not None:
                        part, sub = cur_group
                    if bare_opener:
                        cur_group = (part, sub)
                    if part:
                        # G1 upgrade: bare rows carry the part letter too —
                        # the later '(ii)'-shift rows inherit it (evidence:
                        # 4CH0 q7 a-ii landed part-less -> PART-MARKS-MISMATCH)
                        last_part = part
                    buckets["point"] += lbl_n  # line consumed by point handling
                    if mt:
                        body = (mt.group("body") or "").strip()
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body) if c.strip()]
                        pending_label = (part, sub, {"base": base,
                                                     "text": [chunks[0]] if chunks else [],
                                                     "notes": chunks[1:] if len(chunks) > 1 else [],
                                                     "marks": int(mt.group("mk")),
                                                     "opener": bare_opener})
                    else:
                        pending_label = (part, sub, {"base": base, "text": [],
                                                     "notes": [], "marks": None,
                                                     "opener": bare_opener})
                    continue

                label = base + num
                if part:
                    last_part = part
                # G1 upgrade: part-block tracking. Explicitly printed part or
                # sub opens/refreshes the block; a scored row printed without
                # one (old-spec label-less continuation rows under 'b i')
                # inherits the open block so downstream part-scoped pools and
                # letter-level cross-checks see the true structure.
                # is_opener MUST be computed before inheritance mutates
                # part/sub — inherited rows belong to the open block and must
                # not advance its start index.
                is_opener = part is not None or sub is not None
                if is_opener:
                    cur_group = (part, sub)
                elif part is None and sub is None and cur_group is not None:
                    part, sub = cur_group
                rest_col = len(line) - len(rest.lstrip())  # answer-text column
                if mt:
                    body = mt.group("body") or ""
                    marks = int(mt.group("mk"))
                    chunks = [c.strip() for c in re.split(r"\s{2,}", body) if c.strip()]
                    pt = {"label": label, "part": part, "sub": sub,
                          "text": [chunks[0]] if chunks else [],
                          "notes": chunks[1:] if len(chunks) > 1 else [],
                          "marks": marks, "page": pageno,
                          "answer_col": rest_col}
                    cur["points"].append(pt)
                    if is_opener:
                        group_start = len(cur["points"]) - 1
                    cur["pages"].add(pageno)
                    buckets["point"] += lbl_n
                    cur_point = pt
                    continue

                # no marks column on this line. G1 upgrade: guidance takes the
                # row ONLY when there is no answer text beside the note — a
                # row like 'M3  (litmus paper) turns blue   Do not award M3
                # ...' is a scored row whose answer text must not be hijacked
                # into guidance (evidence: 4CH0 3b(i) M3 row lost, cascade
                # unclassified OR-rows, broken merged-cell recovery).
                rest_chunks_n = len([c for c in re.split(r"\s{2,}", rest) if c.strip()])
                if GUIDANCE_RE.search(st) and rest_chunks_n <= 1:
                    cur["guidance"].append({"page": pageno, "text": st})
                    buckets["guidance"] += lbl_n
                    cur_point = None
                    prev_line_guidance = True
                    continue
                # G1 upgrade: prose notes whose text opens with an M/A token
                # ('M2 can be awarded for use of') — a SINGLE space between the
                # token and the text proves prose: columnar label rows always
                # separate label and answer by 2+ spaces. Never a label row;
                # absorb into the open point so its note-wraps stay chained
                # (evidence: p25 'M2 can be awarded...' hijack orphaned four
                # subsequent note lines into unclassified).
                if not mt and re.match(r"\s\S", rest) and sub is None:
                    # G1.2 (RC-E): a printed '(iii)   M1 ...' lead makes this a
                    # structural grid row, never prose — only part-less AND
                    # sub-less rows can be prose notes ('M2 can be awarded...')
                    # G1.3-r2 (RC-C): the code checked ONLY `sub is None` — an
                    # explicit part lead ('(d)   M1 – incomplete combustion',
                    # 4CH0 1C Jun 2014 q9(d) p16) slipped through as prose and
                    # its whole block was absorbed into the previous point's
                    # notes (MS-NO-POINTS for the letter). The part-less
                    # condition is now enforced as documented.
                    if part is None and cur_point is not None:
                        (cur_point["notes"] if cur_point["text"] else cur_point["text"]).append(st)
                        buckets["continuation"] += lbl_n
                        continue
                if prev_note_open:
                    # note-column continuation that merely looks like a label
                    # (e.g. 'ALLOW' ended the previous line, 'M1 bromide solution'
                    # is the allowed value) — never a scored point
                    tgt = cur_point["notes"] if (cur_point is not None
                                                and cur_point["text"]) else \
                        (cur_point["text"] if cur_point is not None else None)
                    if tgt is not None:
                        tgt.append(st)
                        buckets["continuation"] += lbl_n
                        continue
                if part is None and sub is None and cur_point is not None \
                        and not GUIDANCE_RE.search(st):
                    # 4CH1-style split descriptor ('M1 (use damp blue) litmus
                    # paper') inside an answer cell — the part row already
                    # carries the marks; the split never carries its own cell.
                    # 4CH0-style grid rows carry the part letter or a marks
                    # cell, so they never take this path.
                    tgt = cur_point["notes"] if cur_point["text"] else cur_point["text"]
                    tgt.append(st)
                    buckets["continuation"] += lbl_n
                    continue
                # provisional point; marks expected on a wrapped line
                # G1.2 (RC-E): a tail-less M/A row under a deferred-cell block
                # opener ('M2 fraction F bitumen' under '(iii) M1 ...' + lone
                # '2') is a marking STEP of that block — absorb as its notes;
                # creating a second scored point mis-splits the merged cell
                # and poisons the letter-level part sums.
                if cur_point is not None and cur_point.get("_from_deferred") \
                        and cur_point.get("part") == part \
                        and cur_point.get("sub") == sub:
                    (cur_point["notes"] if cur_point["text"] else cur_point["text"]).append(st)
                    buckets["continuation"] += lbl_n
                    continue
                chunks = [c.strip() for c in re.split(r"\s{2,}", rest) if c.strip()]
                pt = {"label": label, "part": part, "sub": sub,
                      "text": [chunks[0]] if chunks else [],
                      "notes": chunks[1:] if len(chunks) > 1 else [],
                      "marks": None, "page": pageno,
                      "answer_col": rest_col}
                _consume_pending(pt)
                cur["points"].append(pt)
                if is_opener:
                    group_start = len(cur["points"]) - 1
                cur["pages"].add(pageno)
                buckets["point"] += lbl_n
                cur_point = pt
                continue

            # --- label-less grid rows (4CH1 style / label-less 4CH0 rows) ---
            # --- G1.3 (RC-C): opener rows whose only content is the marks
            # cell (empty answer body). Must run BEFORE solo/qpm/prm/sm —
            # those match with rest='<digit>' and lose the marks semantics
            # (tail_marks needs \s{2,}; a bare rest digit became junk text,
            # the sub-part aggregate was demoted and the letter sum broke).
            om = (OPENER_MARKS_QPS_RE.match(line)
                  or OPENER_MARKS_PS_RE.match(line)
                  or OPENER_MARKS_QS_RE.match(line)
                  or OPENER_MARKS_S_RE.match(line))
            om_ok = False
            if om:
                # value cap + column discipline (the bare digit must sit at
                # the established marks column — answer-value digits at the
                # answer column keep the legacy junk-point handling)
                mk_raw = int(om.group("mk"))
                mk_val = mk_raw if 0 < mk_raw <= MARKS_CELL_MAX else None
                _, mk_om = _discipline(om, mk_val, line)
                om_ok = mk_om is not None
            if om and om_ok:
                gd_om = om.groupdict()
                qn_om = gd_om.get("qn") or None
                part_om = gd_om.get("part")
                sub_om = gd_om.get("sub")
                if qn_om is not None:
                    if int(qn_om) > MAX_QN:
                        om_ok = False  # answer value '28', not a question row
                    else:
                        ensure_question(int(qn_om))
            if om and om_ok:
                if cur is None:
                    om_ok = False  # row before any question: legacy handling
            if om and om_ok:
                rest_om = (gd_om.get("rest") or "").strip()
                chunks_om = [c.strip() for c in re.split(r"\s{2,}", rest_om)
                             if c.strip()] if rest_om else []
                if part_om is None and sub_om is not None:
                    # '7 (ii)' / '(ii)' — solo sub inherits the open part
                    # (same semantics as the '(ii)'-shift in the label path).
                    # NO open part context -> the roman may BE the part
                    # letter ('(v)' degenerate page, RC-D legacy fallback) —
                    # never claim; fall through to the legacy paths.
                    if last_part is None:
                        om_ok = False
                    else:
                        part_om = last_part
                if part_om is None and sub_om is None:
                    om_ok = False
            if om and om_ok:
                gp_om = new_point(part_om, sub_om, chunks_om, mk_om, pageno,
                                  answer_col=len(line.rstrip()))
                gp_om["_from_deferred"] = True  # step rows below are notes
                if part_om:
                    last_part = part_om
                cur_group = (part_om, sub_om)
                group_start = len(cur["points"]) - 1
                buckets["point"] += lbl_n
                continue

            gp = None
            solo = QPART_PAREN_SOLO_RE.match(line) or QPART_BARE_SOLO_RE.match(line)
            # G1.3-r3 (RC-C round 3): bare part letter ALONE (see
            # PART_BARE_SOLO_RE). Sequential guard: next/same letter of the
            # open question, or the question's first letter.
            bsolo = None
            if solo is None and cur is not None:
                for _bsre in (PART_BARE_SOLO_RE, PART_BARE_SOLO_COL0_RE,
                              PART_PAREN_SOLO_QNLESS_RE):
                    _m = _bsre.match(line)
                    if _m and (last_part is None
                               or _m.group("part") == last_part
                               or ord(_m.group("part")) == ord(last_part) + 1):
                        bsolo = _m
                        break
            qpm = None if (solo or bsolo) else (QPART_PAREN_RE.match(line) or QPART_BARE_RE.match(line))
            if solo:
                # G1.2 (RC-A): opener-only row — '1 (a)' / '5 a' with no text.
                # 2012+ table grids print the opener alone; the part's merged
                # marks cell and the answer-table content sit on their own
                # lines and attach to this aggregate point (backward lone-cell
                # rule below). Without it the question never opened and the
                # whole part block was lost.
                qn = int(solo.group("qn"))
                if qn <= MAX_QN:
                    ensure_question(qn)
                    if cur is not None:
                        part = solo.group("part")
                        gp = new_point(part, None, [], None, pageno,
                                       answer_col=len(line.rstrip()))
                        last_part = part
                        cur_group = (part, None)
                        group_start = len(cur["points"]) - 1
                        buckets["point"] += lbl_n
            elif bsolo:
                part = bsolo.group("part")
                gp = new_point(part, None, [], None, pageno,
                               answer_col=len(line.rstrip()))
                last_part = part
                cur_group = (part, None)
                group_start = len(cur["points"]) - 1
                buckets["point"] += lbl_n
            elif qpm:
                qn = int(qpm.group("qn"))
                if qn <= MAX_QN:
                    ensure_question(qn)
                    part = qpm.group("part")
                    sub = qpm.group("sub")
                    rest = qpm.group("rest")
                    mt, mk = _discipline(*tail_marks(rest), line)
                    marks = mk
                    body = mt.group("body") if mt else rest
                    chunks = [c.strip() for c in re.split(r"\s{2,}", body or "") if c.strip()]
                    gp = new_point(part, sub, chunks, marks, pageno,
                                   answer_col=len(line) - len(rest.lstrip()))
                    last_part = part
                    cur_group = (part, sub)
                    group_start = len(cur["points"]) - 1
                    buckets["point"] += lbl_n
            elif cur is not None:
                prm = PART_PAREN_RE.match(line) or PART_PAREN_COMPACT_RE.match(line)
                # G1.2 (RC-D): '(v)'/'(i)'/'(x)' with an open part context is a
                # roman SUB-part opener, never a part letter (parts are a-h).
                # PART_PAREN_RE previously claimed '(v)', landing the row as
                # part='v'/sub=None (evidence: 4CH1 1C June 2024 q2 (a)(v) ->
                # MS-POINT-UNKNOWN-PART).
                if prm and prm.group("part") in ("i", "v", "x") \
                        and last_part is not None:
                    prm = None
                brm = None if prm else PART_BARE_RE.match(line)
                # same guard for the bare form ('v  text') — prefer the roman
                # sub-part reading (SUB_BARE) when a part context is open
                if brm and brm.group("part") in ("i", "v", "x") \
                        and last_part is not None and SUB_BARE_RE.match(line):
                    brm = None
                # G1.3-r3 (RC-C round 3): column-0 bare part opener (see
                # PART_BARE_COL0_RE). Sequential guard: the letter must be
                # the NEXT or SAME part of the open question (banner rows
                # can reprint), and a question must be open at all — this
                # keeps leftmost-column data fragments ('g  cm3' units,
                # lowercase stray marks) from opening phantom parts.
                col0m = None
                if prm is None and brm is None and cur is not None:
                    m0 = PART_BARE_COL0_RE.match(line)
                    if m0 and (last_part is None
                               or m0.group("part") == last_part
                               or ord(m0.group("part")) == ord(last_part) + 1):
                        col0m = m0
                # G1.3-r3 (RC-C round 3): qn + bare roman sub lead (see
                # QPART_BARE_SUB_RE) — same-question continuation only, and
                # only under an open part (a sub needs its parent letter).
                qsubm = None
                if col0m is None and prm is None and brm is None \
                        and cur is not None and last_part is not None:
                    m5 = QPART_BARE_SUB_RE.match(line)
                    if m5 and int(m5.group("qn")) <= MAX_QN \
                            and cur["number"] == int(m5.group("qn")):
                        qsubm = m5
                if qsubm is not None:
                    sub5 = qsubm.group("sub")
                    rest5 = qsubm.group("rest")
                    mt5, mk5 = _discipline(*tail_marks(rest5), line)
                    body5 = mt5.group("body") if mt5 else rest5
                    chunks5 = [c.strip() for c in re.split(r"\s{2,}", body5) if c.strip()]
                    gp = new_point(last_part, sub5, chunks5, mk5, pageno,
                                   answer_col=len(line) - len(rest5.lstrip()))
                    cur_group = (last_part, sub5)
                    group_start = len(cur["points"]) - 1
                    buckets["point"] += lbl_n
                    continue
                if col0m is not None:
                    part = col0m.group("part")
                    sub = col0m.group("sub")
                    rest = col0m.group("rest")
                    mt, mk = _discipline(*tail_marks(rest), line)
                    last_part = part
                    if mt:
                        # scored opener ('d   i   silica ... 1'): a real point
                        body = mt.group("body")
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body) if c.strip()]
                        gp = new_point(part, sub, chunks, mk, pageno,
                                       answer_col=len(line) - len(rest.lstrip()))
                        cur_group = (part, sub)
                        group_start = len(cur["points"]) - 1
                        buckets["point"] += lbl_n
                    else:
                        # banner/prose opener ('f   In part (f):'): structural
                        # only — the scored rows below carry their own marks
                        # cells; creating a marks-less point here would leak a
                        # None into the letter sums
                        cur_group = (part, sub)
                    continue
                if prm or brm:
                    mm = prm or brm
                    part = mm.group("part")
                    sub = mm.group("sub")
                    rest = mm.group("rest")
                    mt, mk = _discipline(*tail_marks(rest), line)
                    # G1.3 (RC-C round 2): a COLUMNAR bare-letter row keeps
                    # opening its point even without a same-line marks cell —
                    # the printed marks sit on a wrapped line below ('1 c
                    # isotopes / atomic numbers / mass numbers   3', 4CH0 1C
                    # Jan 2015 q1(c): the cell used to be claimed by the
                    # previous letter's block as a phantom further-answer
                    # row). Prose stays excluded: the 2+ space gap between
                    # the letter and the text proves columnar layout.
                    columnar_bare = bool(brm) and bool(
                        re.match(r"^\s{1,8}[a-z]\s{2,}", line))
                    if prm or mt or columnar_bare:
                        marks = mk
                        body = mt.group("body") if mt else rest
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body or "") if c.strip()]
                        gp = new_point(part, sub, chunks, marks, pageno,
                                       answer_col=len(line) - len(rest.lstrip()))
                        last_part = part
                        cur_group = (part, sub)
                        group_start = len(cur["points"]) - 1
                        buckets["point"] += lbl_n
                else:
                    sm = SUB_PAREN_RE.match(line) or SUB_BARE_RE.match(line) \
                        or SUB_PAREN_NUM_RE.match(line)
                    if sm and last_part:
                        sub = sm.group("sub")
                        if not ROMAN_RE_MS.match(sub or ""):
                            # G1.3-r3: arabic option numbers ('(2)'-'(5)') are
                            # option leads, not sub-parts — the atoms schema
                            # types sub as roman only. Score under the open
                            # part with sub=None.
                            sub = None
                        rest = sm.group("rest")
                        mt, mk = _discipline(*tail_marks(rest), line)
                        marks = mk
                        body = mt.group("body") if mt else rest
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body or "") if c.strip()]
                        gp = new_point(last_part, sub, chunks, marks, pageno,
                                       answer_col=len(line) - len(rest.lstrip()))
                        cur_group = (last_part, sub)
                        group_start = len(cur["points"]) - 1
                        buckets["point"] += lbl_n
            if gp is not None:
                continue

            # --- G1.2 (RC-A/RC-E): lone marks cell — a deep-indented line whose
            # entire content is a 1-2 digit value <= MARKS_CELL_MAX.
            # Backward: fills the open aggregate/opener point still lacking
            # marks (2012+ table grids print the part's merged marks cell on
            # its own line under the opener: 4CH0 2C Jan 2012 '1 (a)' + '4').
            # Forward: otherwise it belongs to the NEXT opener row (displaced
            # upward merged cell: 4CH1 2C June 2021 q3 '2' above '(iii) M1').
            lone = re.match(r"^\s{4,}(?P<v>\d{1,2})\s*$", line)
            if lone and 0 < int(lone.group("v")) <= MARKS_CELL_MAX:
                lcol = len(line.rstrip()) - len(lone.group("v"))
                lval = int(lone.group("v"))
                # G1.2 (RC-B): the cell must sit at the established marks
                # column — deep-left lone digits are fraction denominators
                # ('OR answer to M1 / 2')
                col_ok = (lcol >= marks_col - MARKS_COL_SLACK) \
                    if marks_col is not None else (lcol >= MARKS_COL_MIN)
                if col_ok:
                    # G1.3-r3 (RC-C round 3): the backward fill no longer
                    # demands an EMPTY point. 2011-2013 old-spec blocks print
                    # a sub-part's second marks cell on a lone line directly
                    # under the tail-less M2 row ('M2 - 0.006' + lone '1',
                    # 4CH0 2C Jan 2013 q7(a)(i)/(iii)) — with text the point
                    # was skipped, the cell routed forward as pending and was
                    # then WIPED by the next opener's own cell (double loss:
                    # M2 unfilled + cell vanished).
                    if (cur is not None and cur_point is not None
                            and cur_point["marks"] is None):
                        cur_point["marks"] = lval
                        buckets["continuation"] += lbl_n
                        continue
                    nxt = _next_content_line(raw_lines, idx)
                    if cur is not None and nxt is not None and _is_opener_shaped(nxt):
                        pending_marks_next = lval
                        buckets["continuation"] += lbl_n
                        continue
                    # G1.2 (RC-A): the cell sits above the next PLAIN answer row of
                    # the open block ('1 (c)' table: lone '1' above '= 79.99') —
                    # create the deferred point now; following answer-column lines
                    # become its text. Openers keep the pending_marks_next route.
                    if cur is not None and cur_point is not None \
                            and not _is_opener_shaped(nxt or "") \
                            and not NOTE_KW_START_RE.match(nxt or ""):
                        dp = new_point(cur_point["part"], cur_point["sub"], [],
                                       lval, pageno, answer_col=cur_point.get("answer_col"))
                        dp["_from_deferred"] = True
                        buckets["point"] += lbl_n
                        continue
                # else: fall through — absorbed as note text (previous behavior)

            # continuation line
            if cur_point is not None and raw[:2].strip() == "" and st:
                # G1 upgrade: capped alternative group ('Any two for 1 each')
                # closes the current part-block's rows as a capped pool; the
                # line itself still absorbs as a note (text preserved)
                an = ANY_N_FOR_EACH_RE.search(st)
                if an and group_start < len(cur["points"]):
                    n_val = WORD_NUM.get(an.group("n").lower()) or int(an.group("n"))
                    per_val = int(an.group("per"))
                    members = cur["points"][group_start:]
                    cur["capped_groups"].append({
                        "anyN": n_val, "per": per_val, "page": pageno,
                        "labels": [m_["label"] for m_ in members],
                        "_members": members})
                mt0, mk0 = tail_marks(st)
                if mt0 is not None:
                    # G1.2 (RC-B): column-discipline the continuation tail
                    mt0, mk0 = _discipline(mt0, mk0, line)
                body0 = (mt0.group("body") or "").strip() if mt0 else ""
                if mt0 and mk0 is not None and body0:
                    if cur_point["marks"] is None and re.search(r"\D", body0):
                        # wrapped marks recovered (legacy rule, now
                        # column-disciplined, value-capped and prose-gated —
                        # a bare-digit body is parallel fraction data, e.g.
                        # 'OR answer to M1' over '2', never a marks note)
                        cur_point["text"].append(body0)
                        cur_point["marks"] = mk0
                        continue
                    # a further answer row of the same part carrying its own
                    # marks cell (alternative answers / multi-row parts) —
                    # never absorb it into the previous point's notes.
                    # G1 upgrade: only when the line sits at/near the point's
                    # ANSWER column — deep notes-column wraps whose tail digit
                    # is a displaced merged-cell value must NOT spawn phantom
                    # points (evidence: 4CH0 q3 'ammonia in M2 ... 1' wrap ->
                    # synthesized P1, arithmetic overcount).
                    line_col = len(raw) - len(raw.lstrip())
                    ans_col = cur_point.get("answer_col")
                    if re.search(r"\D", body0) \
                            and not NOTE_KW_START_RE.match(body0) \
                            and (ans_col is None or line_col <= ans_col + 8):
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body0) if c.strip()]
                        new_point(cur_point["part"], cur_point["sub"], chunks,
                                  mk0, pageno, answer_col=line_col)
                        buckets["point"] += lbl_n
                        continue
                    # G1.2 (RC-B/RC-E): displaced marks cell in the notes
                    # region (deep indent, tail at the marks column) opens a
                    # DEFERRED point inheriting the open block; the row's own
                    # text is preserved and following answer-column lines
                    # become the deferred point's text (evidence: 4CH0 2C
                    # Jan 2012 q1 (b)(ii) 'proton number / 1' + 'with
                    # different masses'; 4CH0 1C Jun 2011 q5 (iii) 'Ignore
                    # solid 1' + 'silver/grey/shiny (liquid)').
                    # G1 guard: ONLY when the true row below is not a labeled
                    # opener — when an M/A label row follows, the cell belongs
                    # to it and the merged-cell recovery fills it (evidence:
                    # 4CH0 q3 'ammonia in M2 ... 1' wrap two rows above its
                    # M3 row — spawning a point here double-counts).
                    nxt = _next_substantive_line(raw_lines, idx)
                    # G1.3 (RC-C): if a complete M/A-labeled row starts within
                    # the next few plain continuation lines, this cell is that
                    # row's vertically-centered merged marks cell — hand it to
                    # the row via pending_marks_next instead of spawning a
                    # phantom point that steals it (evidence: 4CH0 1C Jun 2012
                    # q6(c)(i) 'mass of isotopes 1' two lines above its M2 row
                    # -> phantom P2 'on a scale where' + M2 poisoned by the
                    # accept-text bleed). Note-wrap-only continuation chains
                    # (4CH0 2C Jan 2012 q1(b)(ii) 'proton number 1' block)
                    # keep the legacy deferred-point spawn.
                    if _labeled_row_ahead(raw_lines, idx):
                        pending_marks_next = mk0
                        buckets["continuation"] += lbl_n
                    elif ans_col is not None and nxt is not None \
                            and not _is_opener_shaped(nxt):
                        dp = new_point(cur_point["part"], cur_point["sub"], [],
                                       mk0, pageno, answer_col=ans_col)
                        dp["notes"].append(body0)
                        buckets["point"] += lbl_n
                        continue
                buckets["continuation"] += lbl_n
                if cur_point["marks"] is None:
                    # G1.3 (RC-C): the legacy unguarded recovery here undid the
                    # G1.2 column/value discipline — accept-text digits ('12'
                    # from 'carbon-12 has a mass of / 12') poisoned tail-less
                    # M-rows (evidence: 4CH0 1C Jun 2012 q6(c)(i) M2 marks=12).
                    # Same guards as the disciplined recovery above: value cap
                    # + marks-column discipline.
                    mt, mk = _discipline(*tail_marks(st), line)
                    if mt and mk is not None and (mt.group("body") or "").strip():
                        cur_point["text"].append(mt.group("body").strip())
                        cur_point["marks"] = mk
                        continue
                (cur_point["notes"] if cur_point["text"] else cur_point["text"]).append(st)
                continue
            if st:
                an = ANY_N_FOR_EACH_RE.search(st)
                if an and cur is not None and group_start < len(cur["points"]):
                    n_val = WORD_NUM.get(an.group("n").lower()) or int(an.group("n"))
                    per_val = int(an.group("per"))
                    members = cur["points"][group_start:]
                    if members:
                        cur["capped_groups"].append({
                            "anyN": n_val, "per": per_val, "page": pageno,
                            "labels": [m_["label"] for m_ in members],
                            "_members": members})
                if GUIDANCE_RE.search(st) and cur is not None:
                    cur["guidance"].append({"page": pageno, "text": st})
                    buckets["guidance"] += lbl_n
                    prev_line_guidance = True
                elif carry_guidance and cur is not None \
                        and raw[:2].strip() == "":
                    # G1 upgrade: wrapped note fragment directly following a
                    # guidance row ('M2 dependent on mention of both' /
                    # 'attraction and electrons in M1') — a guidance
                    # continuation, not an unclassified row
                    cur["guidance"].append({"page": pageno, "text": st})
                    buckets["guidance"] += lbl_n
                    prev_line_guidance = True
                else:
                    unclassified.append({"page": pageno, "text": st, "reason": "unclassified"})
                    buckets["unclassified"] += lbl_n

    for q in questions:
        q["pages"] = sorted(q["pages"])
        # merged-cell recovery: when exactly ONE point lacks a printed marks
        # cell and a printed total is known, the missing value is fully
        # determined (total - resolved sum). Never guesses otherwise.
        # G1 upgrade: recovery tries the MS total row first, then the QP
        # printed total — displaced merged-cell values in old-spec layouts
        # (evidence: 4CH0 q3 cell lands on a notes wrap two rows above its
        # M3 row) leave the MS total unable to close while the QP total does.
        unresolved = [p for p in q["points"] if p["marks"] is None]
        resolved_sum = sum(p["marks"] for p in q["points"] if p["marks"] is not None)
        if len(unresolved) == 1:
            for src_total in (q["total_row"],
                              (qp_totals or {}).get(q["number"])):
                if src_total is None:
                    continue
                diff = src_total - resolved_sum
                if diff > 0:
                    unresolved[0]["marks"] = diff
                    break
        # rows whose marks cell never resolved are answer-cell descriptors,
        # not scored points: demote to the previous point's notes (or question
        # guidance) — text preserved, never a None-marks point downstream
        kept, demoted = [], []
        for p in q["points"]:
            (kept if p["marks"] is not None else demoted).append(p)
        for p in demoted:
            frags = [t for t in (p["text"] or []) if t] + \
                    [n for n in (p["notes"] or []) if n]
            body = " | ".join(frags) if frags else p["label"]
            if kept:
                tgt = kept[-1]
                (tgt["notes"] if tgt["text"] else tgt["text"]).append(
                    "%s (no printed marks cell): %s" % (p["label"], body))
            else:
                q["guidance"].append({"page": p["page"], "text": body})
        if demoted:
            q["demoted_points"] = [p["label"] for p in demoted]
        # G1.2 (RC-B): points whose ONLY text chunks are note-keyword rows
        # ('Ignore "electrons cannot...' — the answer column was empty at the
        # marks row, so the note column supplied the "text") are note-led;
        # move those chunks to the notes so the md renders answer-first.
        # Content is preserved either way; arithmetic is unaffected.
        for p in kept:
            txt = [t for t in (p["text"] or []) if (t or "").strip()]
            if txt and all(NOTE_KW_START_RE.match(t) for t in txt):
                p["notes"] = p["text"] + (p["notes"] or [])
                p["text"] = []
            p.pop("_from_deferred", None)  # internal marker never reaches atoms
        q["points"] = kept
        # G1 upgrade: capped alternative groups ('Any N for M each') contribute
        # their CAP to the arithmetic, not the sum of their member rows — the
        # members are alternatives, only N of them are awardable (evidence:
        # 4CH0 q8 8b(i) six 1-mark rows, total 10, raw sum 14). Member dicts
        # are held by reference, so demoted members drop out naturally.
        cap_total = 0
        member_marks = 0
        capped_groups_out = []
        for g in q["capped_groups"]:
            members = [m_ for m_ in g["_members"] if m_["marks"] is not None]
            if not members:
                continue
            cap = int(g["anyN"]) * int(g["per"])
            cap_total += cap
            member_marks += sum(m_["marks"] for m_ in members)
            # resolve member positions against the FINAL kept points so emit
            # can form position-indexed pools without re-matching identity
            idxs = [i for i, p in enumerate(q["points"])
                    if any(p is m_ for m_ in members)]
            capped_groups_out.append({"anyN": g["anyN"], "per": g["per"],
                                      "cap": cap, "page": g["page"],
                                      "labels": [m_["label"] for m_ in members],
                                      "_members": members, "indices": idxs})
        q["capped_groups"] = capped_groups_out
        q["sum_points"] = (sum(p["marks"] for p in q["points"])
                           - member_marks + cap_total)
        q["label_count"] = len(q["points"])
        q["unresolved_marks"] = []
        # G1 upgrade: arithmetic closes against the MS total row OR the QP
        # printed total (old-spec MSs carry misprinted total rows; the QP/MS
        # conflict stays disclosed via PRINTED-QP-MS-TOTAL-DISCREPANCY).
        qp_total = (qp_totals or {}).get(q["number"])
        q["arithmetic_ok"] = (
            not q["unresolved_marks"]
            and (q["total_row"] is not None and q["sum_points"] == q["total_row"]
                 or qp_total is not None and q["sum_points"] == qp_total))
        for p in q["points"]:
            p["text"] = collapse_spaced(" ".join(p["text"]).strip())

    label_count = sum(q["label_count"] for q in questions)
    return {"questions": questions, "label_count": label_count,
            "total_rows_found": sum(1 for q in questions if q["total_row"] is not None),
            "witnesses": witnesses, "unclassified": unclassified,
            "buckets": buckets,
            "raw_label_count": None}


def raw_label_count(pages):
    n = 0
    for p in pages:
        n += len(re.findall(r"\b[MA]\d{1,2}\b", p["text"]))
    return n


def load_pages(pages_json):
    with open(pages_json, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    r = parse_pages(load_pages(sys.argv[1]))
    r["raw_label_count"] = raw_label_count(load_pages(sys.argv[1]))
    print(json.dumps({"label_count": r["label_count"], "raw": r["raw_label_count"],
                      "buckets": r["buckets"],
                      "total_rows_found": r["total_rows_found"],
                      "questions": [{"number": q["number"], "total_row": q["total_row"],
                                     "sum_points": q["sum_points"], "arithmetic_ok": q["arithmetic_ok"],
                                     "unresolved": q["unresolved_marks"]}
                                    for q in r["questions"]],
                      "witnesses": r["witnesses"],
                      "unclassified_n": len(r["unclassified"])}, indent=1))
