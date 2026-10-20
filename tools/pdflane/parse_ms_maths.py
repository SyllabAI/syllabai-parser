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

# dialect A header: five named columns on one layout line
HEADER_A_RE = re.compile(
    r"^\s*Question\s+Working\s+Answer\s+Mark\s+Notes\b")
# dialect B header (2018-06 legacy): Notes BEFORE Mark, plus Sub-Total/Total
HEADER_B_RE = re.compile(
    r"^\s*Question\s+Working\s+Answer\s+Notes\s+Mark\b")

# col-0 opener: question number, optional part label(s): '1 (a)', '26 (a)(i)'
OPENER_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+(?P<labels>\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\)"
    r"(?:\s*\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\))*)?\s*(?P<rest>.*)$")
# part label continuing on its own row (merged question-number cell)
PART_ONLY_RE = re.compile(
    r"^\s*(?P<labels>\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\)"
    r"(?:\s*\((?:[a-z]|\d+|i{1,3}|iv|v|vi{1,3}|ix|x)\))*)\s*(?P<rest>.*)$")
# mark-type codes: B1/M1/A1/B2/M2/A2/B1ft/M1dep...
MARK_CODE_RE = re.compile(r"\b([BMA])(\d)(?:[a-z]{2,3})?\b")
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
    """Return (dialect, names, x-positions dict) for a header line, else None."""
    if HEADER_A_RE.match(line):
        dialect, names = "A", ["Question", "Working", "Answer", "Mark", "Notes"]
    elif HEADER_B_RE.match(line):
        dialect, names = "B", ["Question", "Working", "Answer", "Notes", "Mark"]
    else:
        return None
    pos = {}
    for n in names:
        i = line.find(n)
        pos[n] = i
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
        """Point contract mirrors parse_ms: label/text/notes/page singular."""
        nonlocal cur_point, point_seq
        point_seq += 1
        pt = {"label": "P%d" % point_seq, "part": cur_part, "sub": cur_sub,
              "marks": marks, "text": text.strip(), "notes": [], "page": page}
        cur_point = pt
        if cur is not None:
            cur["points"].append(pt)
            cur["pages"].add(page)
        buckets["point"] += 1
        if open_cell is not None:
            open_cell["codes"].append(marks)
        return pt

    for p in pages:
        page = p["page"]
        pos = None
        x_mark = None
        for raw in p.get("text", "").splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            st = line.strip()
            if st == "PMT":
                buckets["furniture_pages"] += 1
                continue
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
            elif po and in_col0:
                labels = po.group("labels")
            elif glued and in_col0:
                cand = int(glued.group(1))
                if expected is None or cand == expected:
                    qn = cand
                    labels = line.strip()[len(glued.group(1)):]
            elif in_col0 and re.match(r"^\s*\d{1,2}\s*$", line):
                cand = int(st)
                if expected is None or cand == expected:
                    qn = cand  # bare question number (vertical centering)
            if qn is not None:
                if cur is not None and qn != cur["number"]:
                    close_cell(page)
                alt_route = False   # a new question leaves any Alt block
                ensure_question(qn, page)
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
