"""Maths-B grid dialect (4MB1) — 'Question | Working | Answer | Mark | Notes'.

Deterministic grid parser for the Edexcel International GCSE Maths B mark
schemes (60/66 4MB1 MS carry this exact header; the 6 legacy 2018-06 files
use the 7-column 'Question | Working | Answer | Notes | Mark | Sub-Total |
Total' dialect and are DETECTED but routed to review, never guessed).

Column semantics (proven against 4MB1-01 2024-06 page 6/8 word coordinates):
  - the Mark column cell is VERTICALLY MERGED: its value is printed on the
    FIRST row of the span it covers — per part when the question has parts
    (Q4: (a)->1, (b)->2), per question when unparted (Q5->3) — and validates
    the SUM of the M/A/B code-marks of every row it spans (Q1: one merged
    cell '2' spanning (a)+(b) whose B1+B1 sum to 2);
  - per-row marks come from the mark-type codes in the Notes column
    (B1/M1/A1/B2/M2/A2... — value = the digit suffix);
  - 'Total N marks' closes each question (same TOTAL_RE as chemistry).

Output contract: identical shape to parse_ms.parse_pages (questions with
number/total_row/arithmetic_ok/points/guidance/pages/capped_groups, plus
label_count/total_rows_found/witnesses/unclassified/buckets) so run_paper,
gates.py and emit_atoms.py consume it unchanged. Deterministic. Honest:
rows that parse to nothing land in unclassified, never dropped.
"""
import json
import re

TOTAL_RE = re.compile(r"^\s*Total\s+(\d{1,3})\s+marks?\s*$", re.I)

# dialect A header: five named columns on one layout line. Round 2: the
# corpus census (66 ms.pdfs) found 4 papers whose first column prints as the
# abbreviation 'Ques'/'Qu' instead of 'Question' (2018-06 4MB1-02R,
# 2021-11 4MB1-02, 2022-01 4MB1-02R, 2023-06 4MB1-02R) — same column ORDER,
# so the alias is accepted and the x-map uses the printed token's position.
HEADER_A_RE = re.compile(
    r"^\s*(?:Question|Ques|Qu)\s+Working\s+Answer\s+Mark\s+Notes\b")
# dialect B header (2018-06 legacy): Notes BEFORE Mark, plus Sub-Total/Total
HEADER_B_RE = re.compile(
    r"^\s*(?:Question|Ques|Qu)\s+Working\s+Answer\s+Notes\s+Mark\b")

# col-0 opener: question number, optional part label(s): '1 (a)', '26 (a)(i)'
OPENER_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+(?P<labels>\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\)"
    r"(?:\s*\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\))*)?\s*(?P<rest>.*)$")
# part label continuing on its own row (merged question-number cell)
PART_ONLY_RE = re.compile(
    r"^\s*(?P<labels>\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\)"
    r"(?:\s*\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\))*)\s*(?P<rest>.*)$")
# mark-type codes: B1/M1/A1/B2/M2/A2/B1ft/M1dep... Round 2 (q22 2024-06):
# pdftotext sometimes glues the suffix word to the code ('A1allow', 5 letters),
# so the suffix run is widened 2..6 letters; the leading \b still anchors the
# code, and 'M marks'/'M1s' still never tokenize.
MARK_CODE_RE = re.compile(r"\b([BMA])(\d)(?:[a-z]{2,6})?\b")

# round 2: ordinal cross-reference words — a code whose immediately preceding
# token is one of these is a REFERENCE to another mark ('the 4th M1' in the
# guidance 'May be implied by award of the 4th M1'), never a scored award
# (proven on 4MB1-01 2024-06 q24; q20's real 'A1 dep on 3 M marks awarded' is
# row-initial and unaffected).
XREF_PREV_RE = re.compile(
    r"^(?:1st|2nd|3rd|4th|5th|6th|first|second|third|fourth|fifth|next|previous|"
    r"respective|each|both)$")

# round 2: the Notes column carries big-bracket alternative blocks printed in
# the Symbol PUA range. Glyph census of 4MB1-01 2024-06 (24/39/24 paired
# counts) proves the extensible-paren piece pairs: LEFT = \uf0e6 top,
# \uf0e7 extender, \uf0e8 bottom; RIGHT = \uf0f6/\uf0f7/\uf0f8; \uf0e9..\uf0eb /
# \uf0f9..\uf0fb the bracket/brace siblings. The SAME family renders Working-
# column matrices ('\uf0e6 1 -6 \uf0f6'), so glyph identity alone cannot
# discriminate: the law is band-gated to the Notes column (x within the
# header Notes position, less a small tolerance). Codes inside an open Notes
# band block are the PARTIAL award of the route the block annotates
# ('\uf0e6 M1 for TAB = 10' under an M2; q9/q24 2024-06) — the same semantics
# as the proven '(B1 ...)' ASCII split-award rule, never additive to the
# merged cell.
BRACKET_LEFT = set("\uf0e6\uf0e7\uf0e8\uf0e9\uf0ea\uf0eb")   # left-edge pieces (top/ext/bottom + bracket/brace siblings)
BRACKET_RIGHT = set("\uf0f6\uf0f7\uf0f8\uf0f9\uf0fa\uf0fb")  # right-edge pieces (close side)
BRACKET_TOP = set("\uf0e6\uf0e9\uf0ea")                    # left top pieces = a NEW block opens
BRACKET_BOTTOM = set("\uf0e8\uf0f8")                       # bottom pieces terminate the block
BRACKET_FAMILY = BRACKET_LEFT | BRACKET_RIGHT
BRACKET_BAND_TOL = 12           # Notes-band tolerance (layout-char space)
QNUM_CODE_RE = re.compile(r"^(\d{1,2})\s*\(")  # '26(a)(i)' glued form

OPENER_X_MAX = 8   # col-0 test in layout-char space: a question opener's
#   first token starts within ~8 chars of the header's Question x;
#   Working-column math starts far right (proven on 4MB1-01 2024-06:
#   qnum x0~1, part labels x0~6, working math x0~45+).

MARK_X_TOL = 12      # mark-cell x tolerance around the header Mark position
FURNITURE_RES = [
    re.compile(r"^PMT$"),
]


def _find_header(line):
    """Return (dialect, names, x-positions dict) for a header line, else None.

    Round 2: the first column may print as 'Question', 'Ques' or 'Qu' — the
    x-map takes the printed alias token's own position so column geometry
    stays true to the page (proven on the 4 abbreviated-header papers).
    """
    if HEADER_A_RE.match(line):
        dialect, names = "A", ["Question", "Working", "Answer", "Mark", "Notes"]
    elif HEADER_B_RE.match(line):
        dialect, names = "B", ["Question", "Working", "Answer", "Notes", "Mark"]
    else:
        return None
    pos = {}
    m0 = re.match(r"\s*(Question|Ques|Qu)\s+", line)
    pos["Question"] = m0.start(1) if m0 else 0
    qend = m0.end() if m0 else 0
    for n in names[1:]:
        pos[n] = line.find(n, qend)
    return dialect, names, pos


def detects_dialect(pages):
    """True when any page carries the dialect-A header (strict: dialect B
    does NOT route here — it is detected separately and routed to review)."""
    for p in pages:
        for raw in p.get("text", "").splitlines():
            h = _find_header(raw)
            if h and h[0] == "A":
                return True

    return False


def _col_of(x, pos):
    """Column name for an x char-position given the header positions."""
    if x is None:
        return "notes"
    order = sorted(pos.items(), key=lambda kv: kv[1])
    col = order[-1][0]
    for name, hx in order:
        if x < hx - 4:
            break
        col = name
    return col


def _split_row(line, pos):
    """Split a grid row into columns by char gaps under the header map.

    Returns {col: text}. Columns are cut at midpoints between adjacent
    header x positions so cell text starting slightly left of a header
    still lands in its own column.
    """
    order = sorted(pos.items(), key=lambda kv: kv[1])
    cuts = []
    for (n1, x1), (n2, x2) in zip(order, order[1:]):
        cuts.append((n1, n2, (x1 + x2) // 2))
    out = {n: "" for n, _ in order}
    # token-wise assignment using the token's own start x
    for m in re.finditer(r"\S+", line):
        x = m.start()
        col = order[-1][0]
        for n1, n2, mid in cuts:
            if x < mid:
                col = n1
                break
        out[col] += (("" if not out[col] else " ") + m.group(0))
    return out


def _labels_of(labels):
    """'(a)(ii)' -> ('a', 'ii'); '1 (a)' handled by OPENER_RE."""
    if not labels:
        return None, None
    parts = re.findall(r"\(([^)]+)\)", labels)
    part = parts[0] if parts else None
    sub = "(".join(parts[1:]) + (")" * max(0, len(parts) - 2)) if len(parts) > 1 else None
    if len(parts) > 1:
        sub = parts[1]
        if len(parts) > 2:
            sub += " (" + ")(".join(parts[2:]) + ")"
    return part, sub


def _clean(s):
    s = s.replace("\uf06f", "").replace("\uf0b4", "x")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _alt_ahead(plines, li, pos):
    """Round 2 (L4): True when an 'Alt' col-0 line occurs within the current
    grid section below line li (before its Total row or the next sequential
    opener). Bounded scan; deterministic. Proven on 4MB1-01 2024-06 q18: the
    Alt section's first mark row prints its code on the row's FIRST line
    while the 'Alt' token prints on the vertically-centred line below, so the
    v0 flag fired one line late and the Alt M1 scored into the main route.
    """
    expected_ahead = None
    for j in range(li + 1, min(li + 60, len(plines))):
        s2 = plines[j].strip()
        if not s2:
            continue
        if TOTAL_RE.match(s2):
            return False
        x2 = len(plines[j]) - len(plines[j].lstrip())
        if x2 <= pos["Question"] + OPENER_X_MAX:
            if re.match(r"^Alt\b", s2):
                return True
            om2 = OPENER_RE.match(plines[j].rstrip())
            if om2 and om2.group("qn"):
                return False   # a real opener arrived first — not an Alt row
    return False


def parse_pages(pages, qp_totals=None):
    """pages: [{"page": n, "text": str}] from pdftotext -layout split.

    Row law (deterministic, position-anchored):
      - 'Total N marks' closes the open question;
      - a col-0 token (within OPENER_X_MAX of the header Question x) opens a
        question (sequential law) or a part label;
      - mark-type codes (B1/M1/A1/B2...) found anywhere right of col-0 are
        POINTS: each code's guidance text runs to the next code token;
      - the merged Mark-column cell = the LAST bare 1-2 digit token BEFORE
        the first code token whose x sits in the mark-cell window
        [x_mark-8, first_code_x); it opens a span validated against the sum
        of the code-marks of the rows it covers (closed by the next cell,
        the next part, or the Total row).
    Everything else is continuation (of a point, when one is open) or honest
    guidance/unclassified — never dropped.
    """
    questions = []
    unclassified = []
    guidance = []
    buckets = {"point": 0, "guidance": 0, "unclassified": 0,
               "continuation": 0, "furniture_pages": 0}
    dialect_b_pages = []
    cur = None
    cur_part = None
    cur_sub = None
    cur_point = None
    open_cell = None
    alt_route = False   # inside an 'Alt' alternative-method block: its codes
    #                       are reprints of the main route — never re-scored
    point_seq = 0
    # round 2 state:
    pending = False     # a Total closed the previous question; code rows
    #                       arriving before the next opener are STAGED, never
    #                       attached to the closed question (q19/q20 2024-06:
    #   q20's number prints vertically-centred on a later line, so its first
    #   M1 row precedes the opener — v0 leaked it backward into q19)
    staged = []         # points awaiting their question
    bracket_open = False   # round 2: a Notes-band big-bracket block is open

    def ensure_question(qn, page):
        nonlocal cur, cur_part, cur_sub, cur_point, point_seq
        if any(x["number"] == qn and x["total_row"] is not None
               for x in questions):
            return  # a closed question number never reopens
        if cur is not None and cur["number"] == qn:
            return
        if cur is not None and cur["total_row"] is None:
            unclassified.append({"page": page,
                                 "text": "question %d opened while %d unclosed"
                                         % (qn, cur["number"])})
        cur = {"number": qn, "total_row": None, "total_row_page": None,
               "points": [], "guidance": [], "pages": set(),
               "capped_groups": [], "arithmetic_ok": True}
        questions.append(cur)
        cur_part = None
        cur_sub = None
        cur_point = None
        point_seq = 0

    def close_cell(page):
        nonlocal open_cell
        if open_cell is None or cur is None:
            open_cell = None
            return
        s = sum(open_cell["codes"])
        if s != open_cell["value"]:
            cur["arithmetic_ok"] = False
            unclassified.append({
                "page": page,
                "text": "MS-SPAN-MARKS-MISMATCH cell=%d span_sum=%d q=%d"
                        % (open_cell["value"], s, cur["number"])})
        open_cell = None

    def add_point(marks, text, page):
        """Point contract mirrors parse_ms: label/text/notes/page singular.

        Round 2 (staging law): while `pending` (previous question closed by
        its Total, next opener not yet seen) the point is staged, not
        attached to the closed question; the flush moves it into the opened
        question. The merged-cell code ledger is untouched — the staged mark
        still validates the cell it was printed under.
        """
        nonlocal cur_point, point_seq
        point_seq += 1
        pt = {"label": "P%d" % point_seq, "part": cur_part, "sub": cur_sub,
              "marks": marks, "text": text.strip(), "notes": [], "page": page}
        cur_point = pt
        if pending:
            staged.append(pt)
        elif cur is not None:
            cur["points"].append(pt)
            cur["pages"].add(page)
        buckets["point"] += 1
        if open_cell is not None:
            open_cell["codes"].append(marks)
        return pt

    def drop_staged(page):
        """Record staged points whose question never opened (honest, loud)."""
        nonlocal staged
        for pt in staged:
            unclassified.append({
                "page": pt["page"],
                "text": "MS-STAGED-POINT-UNATTRIBUTED marks=%d: %s"
                        % (pt["marks"], (pt["text"] or "(bare code)")[:80])})
        staged = []

    def flush_staged(page):
        """Move staged points into the current (just opened) question.

        Labels are reassigned sequentially from the freshly reset point_seq
        so the product's P-numbers stay monotonic per question.
        """
        nonlocal staged, point_seq
        if not staged:
            return
        if cur is None or cur["total_row"] is not None:
            # no OPEN question for the staged section — honest record
            drop_staged(page)
            return
        for pt in staged:
            point_seq += 1
            pt["label"] = "P%d" % point_seq
            cur["points"].append(pt)
            cur["pages"].add(pt["page"])
            cur["pages"].add(page)
        staged = []

    for p in pages:
        page = p["page"]
        pos = None
        x_mark = None
        plines = p.get("text", "").splitlines()
        for li, raw in enumerate(plines):
            line = raw.rstrip()
            if not line.strip():
                continue
            st = line.strip()
            if st == "PMT":
                buckets["furniture_pages"] += 1
                continue
            # round 2: big-bracket carry state — piece-transition model. A
            # multi-row alternatives block prints LEFT-edge pieces (top,
            # extenders, bottom) down the notes gutter; inline fraction pairs
            # print balanced left+right on ONE line and never open a carry.
            # The carry band starts at the Answer column so Working-column
            # matrices never participate.
            if pos is not None:
                band_lo = pos["Answer"]
                bl = sum(1 for i, ch in enumerate(line)
                         if ch in BRACKET_LEFT and i >= band_lo)
                br = sum(1 for i, ch in enumerate(line)
                         if ch in BRACKET_RIGHT and i >= band_lo)
                if br:
                    bracket_open = False        # right side closes/balances the line
                elif bl:
                    if any(ch in BRACKET_TOP for ch in line if ch in BRACKET_LEFT):
                        bracket_open = True     # top piece without a close: block opens
                    elif any(ch in BRACKET_BOTTOM for ch in line if ch in BRACKET_LEFT):
                        bracket_open = False    # bottom piece: block ended
                    # extender-only line: carry unchanged (spine row)
            h = _find_header(line)
            if h:
                dialect, names, hpos = h
                if dialect == "B":  # legacy 2018-06: Notes before Mark
                    dialect_b_pages.append(page)
                    pos = None
                    continue
                pos = hpos
                x_mark = hpos["Mark"]
                # a repeated header re-opens a grid section; the Alt flag is
                # set by the 'Alt' row INSIDE the section, so keep it here
                continue
            tm = TOTAL_RE.match(st)
            if tm:
                if pending and staged:
                    # a whole section staged but its number never printed —
                    # honest unattributed record, never silently attached
                    close_cell(page)
                    drop_staged(page)
                    pending = False
                if cur is not None:
                    close_cell(page)
                    cur["total_row"] = int(tm.group(1))
                    cur["total_row_page"] = page
                    cur["pages"].add(page)
                    s = sum(pt["marks"] for pt in cur["points"])
                    if s != cur["total_row"]:
                        cur["arithmetic_ok"] = False
                        unclassified.append({
                            "page": page,
                            "text": "MS-QUESTION-MARKS-MISMATCH q=%d total=%d sum=%d"
                                    % (cur["number"], cur["total_row"], s)})
                    # round 2: arm staging — code rows before the next opener
                    # belong to the NEXT question (number-absent opener), not
                    # to the question this Total just closed
                    pending = True
                    staged = []
                continue
            if pos is None:
                if dialect_b_pages and dialect_b_pages[-1] == page:
                    buckets["unclassified"] += 1
                    unclassified.append({"page": page,
                                         "text": "DIALECT-B-UNSUPPORTED: " + st[:120]})
                else:
                    buckets["continuation"] += 1
                continue

            x0 = len(line) - len(line.lstrip())
            in_col0 = x0 <= pos["Question"] + OPENER_X_MAX
            if in_col0 and re.match(r"^Alt\b", st):
                alt_route = True
                buckets["continuation"] += 1
                continue
            # ---- openers (col-0 only, sequential law) ----
            qn = None
            labels = None
            om = OPENER_RE.match(line)
            po = None if (om and om.group("qn")) else PART_ONLY_RE.match(line)
            glued = QNUM_CODE_RE.match(line.strip()) if in_col0 else None
            expected = (cur["number"] + 1) if cur is not None else None
            if om and om.group("qn") and in_col0:
                cand = int(om.group("qn"))
                if expected is None or cand == expected:
                    qn = cand
                    labels = om.group("labels")
                elif (cur is not None and cand == cur["number"]
                      and cur["total_row"] is None
                      and _alt_ahead(plines, li, pos)):
                    # round 2 (L4): re-print of the OPEN question = Alt
                    # section restart — its first mark row carries the code
                    # before the 'Alt' token prints (q18 2024-06)
                    alt_route = True
            elif po and in_col0:
                labels = po.group("labels")
            elif glued and in_col0:
                cand = int(glued.group(1))
                if expected is None or cand == expected:
                    qn = cand
                    labels = line.strip()[len(glued.group(1)):]  # noqa: E501
                elif (cur is not None and cand == cur["number"]
                      and cur["total_row"] is None
                      and _alt_ahead(plines, li, pos)):
                    alt_route = True
            elif in_col0 and re.match(r"^\s*\d{1,2}\s*$", line):
                cand = int(st)
                if expected is None or cand == expected:
                    qn = cand  # bare question number (vertical centering)
                elif (cur is not None and cand == cur["number"]
                      and cur["total_row"] is None
                      and _alt_ahead(plines, li, pos)):
                    alt_route = True
            if qn is not None:
                if cur is not None and qn != cur["number"]:
                    close_cell(page)
                alt_route = False   # a new question leaves any Alt block
                ensure_question(qn, page)
                pending = False
                if cur is not None and cur["number"] == qn:
                    flush_staged(page)
            if labels:
                part, sub = _labels_of(labels if isinstance(labels, str) else "")
                if part is not None and (cur_part != part or sub != cur_sub):
                    # NOTE: a new part does NOT close an open mark-cell span —
                    # the merged cell frequently spans several part rows
                    # (evidence: 4MB1-01 2024-06 q1, one cell '2' over (a)+(b))
                    cur_part = part
                    cur_sub = sub
                    cur_point = None

            # ---- mark codes -> points (guidance splits at code tokens) ----
            scan = re.sub(r"\b([BMA]\d)\s+(?:dep(?:enden)?t?\s+on|io|in\s+that"
                          r"\s+case)\s+(?:\(\s*)?[BMA]\d(?:\s*\))?", r"\1", line)
            # SC (special case) codes are contingency awards — never part of
            # the question total ('SC B1 for awrt 3.6 ...')
            scan = re.sub(r"\bSC\s+[BMA]\d\b", "SC", scan)
            codes = []
            for m_ in MARK_CODE_RE.finditer(scan):
                if m_.start() <= pos["Question"] + OPENER_X_MAX:
                    continue
                # a code directly inside '(' ... ')' is a split-award note
                # ('(B1 for an expression ...)'), not a scored point
                before = scan[:m_.start()].rstrip()
                if before.endswith("("):
                    continue
                # round 2 (L1): big-bracket partial-award block — codes whose
                # immediately-preceding glyph is a LEFT-family paren piece
                # (top/extender/bottom) sit inside an alternatives block that
                # annotates the route above them as its partial award; same
                # non-additive semantics as the proven '(B1 ...)' ASCII rule.
                # No band gate needed here: Working-column matrices CLOSE with
                # RIGHT-family pieces ('\uf0e6 1 -6 \uf0f6' — F6 never fires),
                # and only a LEFT piece can sit directly left of a code.
                in_bracket = False
                stripped_gap = len(scan[:m_.start()]) - len(before)
                gx = m_.start() - stripped_gap - 1
                if before and before[-1] in BRACKET_LEFT:
                    in_bracket = True   # left piece immediately left of the code
                elif bracket_open:
                    # carry: spine-row codes with text between the spine and
                    # the code; band-gated right of the Answer column so
                    # Working-column math never participates
                    band_lo = pos["Answer"]
                    closed_before = any(
                        (ch in BRACKET_RIGHT or ch in BRACKET_BOTTOM)
                        for i, ch in enumerate(scan[:m_.start()])
                        if ch in BRACKET_FAMILY and i >= band_lo)
                    if not closed_before:
                        in_bracket = True   # block carried open from an earlier line
                if in_bracket:
                    unclassified.append({
                        "page": page,
                        "text": "MS-BRACKET-PARTIAL-CODE-SKIPPED q=%d: %s"
                                % (cur["number"] if cur else -1, st[:90])})
                    continue
                # round 2 (L2): ordinal cross-reference — a code whose
                # preceding token is an ordinal is a REFERENCE to another
                # mark ('May be implied by award of the 4th M1'), never an
                # award of its own
                toks = before.split()
                if toks and XREF_PREV_RE.match(toks[-1]):
                    unclassified.append({
                        "page": page,
                        "text": "MS-CODE-XREF-SKIPPED q=%d: %s"
                                % (cur["number"] if cur else -1, st[:90])})
                    continue
                codes.append(m_)
            # dep-reference law: a code whose gap from the previous kept code
            # contains 'dep on'/'dependent on' phrasing is a REFERENCE to that
            # mark ('M1 dependent on 1st M1 for ...') — one mark, not two
            kept = []
            for m_ in codes:
                prev_end = kept[-1].end() if kept else 0
                between = scan[prev_end:m_.start()]
                if kept and re.search(r"\b(dep|indep|dependent|dependant)\b",
                                      between):
                    continue
                kept.append(m_)
            codes = kept
            if codes and alt_route:
                # alternative-method reprint: record honestly, never re-score
                buckets["continuation"] += 1
                unclassified.append({"page": page,
                                     "text": "ALT-ROUTE-CODE-SKIPPED q=%d: %s"
                                             % (cur["number"] if cur else -1,
                                                st[:90])})
                continue
            if codes:
                first_x = codes[0].start()
                # merged Mark cell: last bare digit token before the first
                # code inside the mark-cell window
                if open_cell is None:
                    for dm in re.finditer(r"(?<![\d.])(\d{1,2})(?![\d.])", line[:first_x]):
                        if x_mark - 8 <= dm.start() < first_x:
                            close_cell(page)
                            open_cell = {"value": int(dm.group(1)),
                                         "page": page, "codes": []}
                for i, cm in enumerate(codes):
                    seg_end = codes[i + 1].start() if i + 1 < len(codes) else len(scan)
                    add_point(int(cm.group(2)), scan[cm.end():seg_end], page)
                continue

            # ---- non-code rows ----
            if cur is None:
                buckets["unclassified"] += 1
                unclassified.append({"page": page, "text": st[:120]})
                continue
            if cur_point is not None and st:
                cur_point["notes"].append(_clean(st))
                buckets["continuation"] += 1
            elif any(k in ("Accept", "accept", "Allow", "allow", "Ignore", "ignore")
                     for k in st.split()[:2]):
                buckets["guidance"] += 1
                g = {"page": page, "text": _clean(st), "labels": []}
                guidance.append(g)
                cur["guidance"].append(g)
                cur["pages"].add(page)
            else:
                buckets["continuation"] += 1
    close_cell(sorted(questions[-1]["pages"])[0] if questions else 0)

    for q in questions:
        q["pages"] = sorted(q["pages"])
    label_count = sum(len(q["points"]) for q in questions)
    return {"questions": questions, "label_count": label_count,
            "total_rows_found": sum(1 for q in questions if q["total_row"] is not None),
            "witnesses": [], "unclassified": unclassified,
            "buckets": buckets, "raw_label_count": None}


def load_pages(pages_json):
    with open(pages_json, encoding="utf-8") as f:
        return json.load(f)
