"""Maths-B legacy grid dialect B (2018-06) — the 7-column mark scheme.

'Question | Working | Answer | Notes | Mark | Sub-Total | Total' — the
2018-06 legacy layout (of-record census: 4MB1-01 + 4MB1-02; the other two
2018-06 papers print the abbreviated dialect-A header 'Ques'). Differences
from dialect A (parse_ms_maths), proven by the PyMuPDF word-coordinate study
(scripts/b2_dialect_b_study.py; Mark codes x≈630-672 vs Notes codes x≈489-497
in point space — a 100pt gap):

  - mark codes print PER ROW in the Mark column (no vertical merge);
  - the Notes column carries method statements whose embedded codes
    ('M1 for ±(75-69)/75', 'B1 for each coordinate', 'SC B1B0') are NOT row
    awards — the Mark-column x-window is the discriminator;
  - the Sub-Total / Total columns carry per-row and per-question digits;
    the question total = the max digit seen in the Total band across the
    question's rows (q1 4MB1-02 prints part totals 2/3 then the question
    total 7 on the last row);
  - dep-reference and SC laws carry over from dialect A.

Output contract: identical shape to parse_ms/parse_ms_maths (questions with
number/total_row/arithmetic_ok/points/guidance/pages, plus label_count/
total_rows_found/witnesses/unclassified/buckets). Deterministic; honest.
"""
import re

from pdflane.parse_ms_maths import (MARK_CODE_RE, PART_ONLY_RE, QNUM_CODE_RE,
                                    TOTAL_RE, _clean, _labels_of)

HEADER_B7_RE = re.compile(
    r"^\s*(?:Question|Ques|Qu)\s+Working\s+Answer\s+Notes\s+Mark\b")

OPENER_X_MAX = 8
OR_X_MAX = 16         # the alternative-route 'OR' line prints indented
MARK_WIN_LEFT = 7     # mark-column window: codes print within ~7 chars
                      # of the Mark header x (coordinate study: -3..+7); the
                      # wider 12 let Notes-text code mentions score (q25)
MARK_WIN_RIGHT = 18
DEP_RE = re.compile(r"\b(dep|indep|dependent|dependant)\b")
OR_ROUTE_RE = re.compile(r"^(?:OR|Or|or)\s*$")


def _dep_sanitize(line):
    """'M1 dep on M1' -> 'M1' (the row's own award, dep is an annotation)."""
    return re.sub(r"\b([BMA]\d)\s+(?:dep(?:enden)?t?\s+on|io|in\s+that"
                  r"\s+case)\s+(?:\(\s*)?[BMA]\d(?:\s*\))?", r"\1", line)


def _find_header_b(line):
    """(names, x-positions) for the 7-column header line, else None."""
    if not HEADER_B7_RE.match(line):
        return None
    m0 = re.match(r"\s*(Question|Ques|Qu)\s+", line)
    pos = {"Question": m0.start(1) if m0 else 0}
    qend = m0.end() if m0 else 0
    for n in ("Working", "Answer", "Notes", "Mark", "Sub-", "Total"):
        pos[n] = line.find(n, qend)
    return pos


def detects_dialect_b(pages):
    """True when any page carries the 7-column legacy header."""
    for p in pages:
        for raw in p.get("text", "").splitlines():
            if _find_header_b(raw):
                return True
    return False


def parse_pages(pages, qp_totals=None):
    questions = []
    unclassified = []
    buckets = {"point": 0, "guidance": 0, "unclassified": 0,
               "continuation": 0, "furniture_pages": 0}
    cur = None
    cur_part = None
    cur_sub = None
    cur_point = None
    point_seq = 0
    or_route = False   # below a standalone col-0-indented 'OR' line: the
    #                      alternative route reprints the main codes — the
    #                      same non-additive semantics as dialect A's Alt
    #                      blocks (4MB1-01 2018-06 q23: two full routes)

    def ensure_question(qn, page):
        nonlocal cur, cur_part, cur_sub, cur_point, point_seq
        if any(x["number"] == qn and x["total_row"] is not None
               for x in questions):
            return  # closed questions never reopen
        if cur is not None and cur["number"] == qn:
            return
        if cur is not None and cur["total_row"] is None:
            unclassified.append({"page": page,
                                 "text": "question %d opened while %d unclosed"
                                         % (qn, cur["number"])})
            close_question(page)
        cur = {"number": qn, "total_row": None, "total_row_page": None,
               "points": [], "guidance": [], "pages": set(),
               "capped_groups": [], "arithmetic_ok": True,
               "total_candidates": []}
        questions.append(cur)
        cur_part = None
        cur_sub = None
        cur_point = None
        point_seq = 0

    def close_question(page):
        """Close the open question: the QP printed total is authoritative
        (the lane's pinned law — the 2018-06 MS Total column prints PART
        totals, not question totals); the Total-column max is the fallback.
        Disagreement is recorded honestly, never silently resolved."""
        nonlocal cur
        if cur is None:
            return
        col_max = max(cur["total_candidates"]) if cur["total_candidates"] else None
        if cur["total_row"] is None:
            if qp_totals and cur["number"] in qp_totals:
                cur["total_row"] = qp_totals[cur["number"]]
                cur["total_row_page"] = page
                cur["total_from"] = "qp-printed"
            elif col_max is not None:
                cur["total_row"] = col_max
                cur["total_row_page"] = page
                cur["total_from"] = "total-column"
        if col_max is not None and cur["total_row"] is not None \
                and col_max != cur["total_row"]:
            unclassified.append({
                "page": page,
                "text": "MS-TOTAL-COLUMN-DISAGREEMENT q=%d column=%d used=%d"
                        % (cur["number"], col_max, cur["total_row"])})
        cur["pages"].add(page)
        if cur["total_row"] is not None:
            s = sum(pt["marks"] for pt in cur["points"])
            if s != cur["total_row"]:
                cur["arithmetic_ok"] = False
                unclassified.append({
                    "page": page,
                    "text": "MS-QUESTION-MARKS-MISMATCH q=%d total=%d sum=%d"
                            % (cur["number"], cur["total_row"], s)})
        cur.pop("total_candidates", None)
        cur = None

    def add_point(marks, text, page):
        nonlocal cur_point, point_seq
        point_seq += 1
        pt = {"label": "P%d" % point_seq, "part": cur_part, "sub": cur_sub,
              "marks": marks, "text": text.strip(), "notes": [], "page": page}
        cur_point = pt
        if cur is not None:
            cur["points"].append(pt)
            cur["pages"].add(page)
        buckets["point"] += 1
        return pt

    for p in pages:
        page = p["page"]
        pos = None
        for raw in p.get("text", "").splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            st = line.strip()
            if st == "PMT":
                buckets["furniture_pages"] += 1
                continue
            if st == "Total" and pos is not None:
                continue  # the wrapped Sub-Total header fragment
            h = _find_header_b(line)
            if h:
                pos = h
                continue
            tm = TOTAL_RE.match(st)
            if tm:
                if cur is not None:
                    cur["total_row"] = int(tm.group(1))
                    cur["total_row_page"] = page
                    cur["pages"].add(page)
                    close_question(page)
                continue
            if pos is None:
                if cur is None:
                    buckets["unclassified"] += 1
                    unclassified.append({"page": page, "text": st[:120]})
                else:
                    buckets["continuation"] += 1
                continue

            # token-wise column assignment by x
            toks = [(m.start(), m.group(0)) for m in re.finditer(r"\S+", line)]
            x0 = toks[0][0] if toks else 0
            in_col0 = x0 <= pos["Question"] + OPENER_X_MAX

            # ---- alternative-route marker (standalone indented 'OR') ----
            if x0 <= OR_X_MAX and OR_ROUTE_RE.match(st):
                or_route = True
                buckets["continuation"] += 1
                continue

            # ---- openers (col-0, sequential law) ----
            qn = None
            labels = None
            om = re.match(
                r"^\s*(?P<qn>\d{1,2})\s*(?P<labels>\((?:[a-z]|\d+)\)"
                r"(?:\s*\((?:[a-z]|\d+)\))*)?(?P<rest>.*)$", line) \
                if in_col0 else None
            glued = QNUM_CODE_RE.match(line.strip()) if in_col0 else None
            po = PART_ONLY_RE.match(line) if in_col0 and not om else None
            expected = (cur["number"] + 1) if cur is not None else None
            if om and om.group("qn"):
                cand = int(om.group("qn"))
                if expected is None or cand == expected:
                    qn = cand
                    labels = om.group("labels")
                elif (cur is not None and cand == cur["number"]
                      and cur["total_row"] is None):
                    # '1(b)' re-print of the OPEN question = part continuation
                    # (4MB1-02 prints every part as '4(a)','4(b)',...)
                    labels = om.group("labels")
            elif glued:
                cand = int(glued.group(1))
                if expected is None or cand == expected:
                    qn = cand
                    labels = line.strip()[len(glued.group(1)):]
            elif po:
                labels = po.group("labels")
            if qn is not None:
                close_question(page)
                ensure_question(qn, page)
                or_route = False   # a new question leaves any OR route
            if labels:
                part, sub = _labels_of(labels if isinstance(labels, str) else "")
                if part is not None and (cur_part != part or sub != cur_sub):
                    cur_part = part
                    cur_sub = sub
                    cur_point = None

            if cur is None:
                if any(re.match(r"^[BMA]\d", t) and x >= pos["Mark"]
                       for x, t in toks):
                    buckets["unclassified"] += 1
                    unclassified.append({"page": page, "text": st[:120]})
                else:
                    buckets["continuation"] += 1
                continue

            # ---- Total-band digits: per-question total candidates ----
            # (captured on every row — the question total usually shares its
            # row with the question's first code)
            if cur is not None:
                for x, t in toks:
                    if re.match(r"^\d{1,3}$", t) and x >= pos["Sub-"]:
                        cur["total_candidates"].append(int(t))

            # ---- Mark-column codes -> points ----
            scan = _dep_sanitize(line)
            codes = []
            for m_ in MARK_CODE_RE.finditer(scan):
                if not (pos["Mark"] - MARK_WIN_LEFT
                        <= m_.start() < pos["Sub-"] + MARK_WIN_RIGHT):
                    continue  # Notes/Answer column mentions are not awards
                codes.append(m_)
            kept = []
            for m_ in codes:
                prev_end = kept[-1].end() if kept else 0
                between = scan[prev_end:m_.start()]
                if kept and DEP_RE.search(between):
                    continue
                kept.append(m_)
            codes = kept
            if codes and or_route:
                buckets["continuation"] += 1
                unclassified.append({
                    "page": page,
                    "text": "OR-ROUTE-CODE-SKIPPED q=%d: %s"
                            % (cur["number"] if cur else -1, st[:90])})
                continue
            if codes:
                first_x = codes[0].start()
                for i, cm in enumerate(codes):
                    seg_end = codes[i + 1].start() if i + 1 < len(codes) \
                        else len(scan)
                    add_point(int(cm.group(2)), scan[cm.end():seg_end], page)
                continue

            # ---- non-code rows ----
            if cur_point is not None and st:
                cur_point["notes"].append(_clean(st))
                buckets["continuation"] += 1
            elif any(k in ("Accept", "accept", "Allow", "allow", "Ignore",
                           "ignore") for k in st.split()[:2]):
                buckets["guidance"] += 1
                g = {"page": page, "text": _clean(st), "labels": []}
                cur["guidance"].append(g)
                cur["pages"].add(page)
            else:
                buckets["continuation"] += 1
    close_question(page if pages else 0)

    for q in questions:
        q["pages"] = sorted(q["pages"])
        q.pop("total_candidates", None)
    label_count = sum(len(q["points"]) for q in questions)
    return {"questions": questions, "label_count": label_count,
            "total_rows_found": sum(1 for q in questions
                                    if q["total_row"] is not None),
            "witnesses": [], "unclassified": unclassified,
            "buckets": buckets, "raw_label_count": None}
