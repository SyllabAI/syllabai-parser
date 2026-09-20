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
TOTAL_IMPLICIT_RE = re.compile(r"^\s*total\s+for\s+question\s*=\s*(\d{1,3})\s*$", re.I)  # 4CH1 2024: 'total for question = 5' — no question number in row; assigned to the open question by sequence
TOTAL_SPLIT_RE = re.compile(r"^(?P<pre>.*?\S)?\s*Tota(?:l)?\s*$")  # 4CH1 2019: number on next line ('Tota' = clipped)
TOTAL_SPLIT_NUM_RE = re.compile(r"^(?P<pre>.*?\S)?\s{2,}(?P<n>\d{1,3})\s*$|^(?P<bare>\d{1,3})\s*$")
NOTE_KW_TAIL_RE = re.compile(r"\b(ALLOW|ACCEPT|REJECT|IGNORE)\s*$", re.I)
NOTE_KW_START_RE = re.compile(
    r"^\s*(ALLOW|ACCEPT|REJECT|IGNORE|Do not accept|Do not allow|"
    r"Ignore|Accept)\b", re.I)
# --- label-less grid rows (4CH1 style / label-less 4CH0 rows) ---
QPART_PAREN_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+\((?P<part>[a-z])\)\s+(?:\(\s*(?P<sub>[ivx]+)\s*\)\s*)?(?P<rest>\S.*)$")
QPART_BARE_RE = re.compile(
    r"^\s*(?P<qn>\d{1,2})\s+(?P<part>[a-z])\s+(?:(?P<sub>[ivx]{1,4})\s+)?(?P<rest>\S.*)$")
PART_PAREN_RE = re.compile(r"^\s*\((?P<part>[a-z])\)\s+(?:\(\s*(?P<sub>[ivx]+)\s*\)\s*)?(?P<rest>\S.*)$")
PART_BARE_RE = re.compile(r"^\s{1,8}(?P<part>[a-z])\s+(?:(?P<sub>[ivx]{1,4})\s+)?(?P<rest>\S.*)$")
SUB_PAREN_RE = re.compile(r"^\s*\(\s*(?P<sub>[ivx]+)\s*\)\s+(?P<rest>\S.*)$")
SUB_BARE_RE = re.compile(r"^\s{1,8}(?P<sub>[ivx]{1,4})\s{2,}(?P<rest>\S.*)$")
ROMAN_RE_MS = re.compile(r"^[ivx]{1,4}$")


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
    artifacts (table numbers), not marks."""
    mt = MARKS_TAIL_RE.match(rest)
    if not mt:
        return None, None
    v = int(mt.group("mk"))
    return mt, (v if v <= MARKS_CELL_MAX else None)


LABEL_RE = re.compile(
    r"^(?P<lead>[\s.(]*)"
    r"(?:(?P<qn>\d{1,2})[\s().]*)?"
    r"(?:(?P<part>[a-z])[\s().]*)?"
    r"(?:(?P<sub>i{1,3}|iv|v)[\s().]*)?"
    r"(?P<labelbase>[MA])(?P<labelnum>\d{0,2})"
    r"(?P<rest>.*)$")
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
    return t


def parse_pages(pages):
    """pages: [{"page": n, "text": str}] from pdftotext -layout split."""
    questions = []
    cur = None
    cur_point = None
    pending_label = None   # (part, sub) when a bare M/A awaits its digit
    pending_total = False  # 'Total' seen; the number sits on the next line
    last_part = None       # last explicit part letter (for sub-row inheritance)
    point_seq = 0          # per-question synthesized label counter
    unclassified = []
    guidance = []          # {page, text, labels}
    witnesses = []
    buckets = {"point": 0, "guidance": 0, "unclassified": 0, "continuation": 0}

    def ensure_question(qn):
        nonlocal cur, last_part, point_seq
        closed = any(x["number"] == qn and x["total_row"] is not None
                     for x in questions)
        if closed:
            return  # a closed question number never reopens (layout artifacts
            # can reprint a question row after later questions)
        if cur is None or cur["number"] != qn:
            cur = {"number": qn, "total_row": None, "total_row_page": None,
                   "points": [], "guidance": [], "pages": set()}
            questions.append(cur)
            last_part = None
            point_seq = 0

    def new_point(part, sub, chunks, marks, pageno):
        nonlocal cur_point, point_seq
        point_seq += 1
        pt = {"label": "P%d" % point_seq, "part": part, "sub": sub,
              "text": chunks[:1], "notes": chunks[1:],
              "marks": marks, "page": pageno}
        cur["points"].append(pt)
        cur["pages"].add(pageno)
        cur_point = pt
        return pt

    for p in pages:
        pageno = p["page"]
        raw_lines = p["text"].splitlines()
        for idx, raw in enumerate(raw_lines):
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
                if QPART_PAREN_RE.match(line) or QPART_BARE_RE.match(line):
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
                            cur["points"].append(pt)
                            cur["pages"].add(pageno)
                            buckets["point"] += lbl_n
                            cur_point = pt
                        else:
                            buckets["unclassified"] += lbl_n
                        continue
                    pending_label = None  # pattern broken; fall through

            lm = LABEL_RE.match(line)
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
                mt = MARKS_TAIL_RE.match(rest)

                if num == "":
                    # bare M/A: digit arrives on the next line; marks may be
                    # at this line's end or still pending
                    buckets["point"] += lbl_n  # line consumed by point handling
                    if mt:
                        body = (mt.group("body") or "").strip()
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body) if c.strip()]
                        pending_label = (part, sub, {"base": base,
                                                     "text": [chunks[0]] if chunks else [],
                                                     "notes": chunks[1:] if len(chunks) > 1 else [],
                                                     "marks": int(mt.group("mk"))})
                    else:
                        pending_label = (part, sub, {"base": base, "text": [],
                                                     "notes": [], "marks": None})
                    continue

                label = base + num
                if part:
                    last_part = part
                if mt:
                    body = mt.group("body") or ""
                    marks = int(mt.group("mk"))
                    chunks = [c.strip() for c in re.split(r"\s{2,}", body) if c.strip()]
                    pt = {"label": label, "part": part, "sub": sub,
                          "text": [chunks[0]] if chunks else [],
                          "notes": chunks[1:] if len(chunks) > 1 else [],
                          "marks": marks, "page": pageno}
                    cur["points"].append(pt)
                    cur["pages"].add(pageno)
                    buckets["point"] += lbl_n
                    cur_point = pt
                    continue

                # no marks column on this line
                if GUIDANCE_RE.search(st):
                    cur["guidance"].append({"page": pageno, "text": st})
                    buckets["guidance"] += lbl_n
                    cur_point = None
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
                if part is None and cur_point is not None \
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
                chunks = [c.strip() for c in re.split(r"\s{2,}", rest) if c.strip()]
                pt = {"label": label, "part": part, "sub": sub,
                      "text": [chunks[0]] if chunks else [],
                      "notes": chunks[1:] if len(chunks) > 1 else [],
                      "marks": None, "page": pageno}
                cur["points"].append(pt)
                cur["pages"].add(pageno)
                buckets["point"] += lbl_n
                cur_point = pt
                continue

            # --- label-less grid rows (4CH1 style / label-less 4CH0 rows) ---
            gp = None
            qpm = QPART_PAREN_RE.match(line) or QPART_BARE_RE.match(line)
            if qpm:
                qn = int(qpm.group("qn"))
                if qn <= MAX_QN:
                    ensure_question(qn)
                    part = qpm.group("part")
                    sub = qpm.group("sub")
                    rest = qpm.group("rest")
                    mt, mk = tail_marks(rest)
                    marks = mk
                    body = mt.group("body") if mt else rest
                    chunks = [c.strip() for c in re.split(r"\s{2,}", body or "") if c.strip()]
                    gp = new_point(part, sub, chunks, marks, pageno)
                    last_part = part
                    buckets["point"] += lbl_n
            elif cur is not None:
                prm = PART_PAREN_RE.match(line)
                brm = None if prm else PART_BARE_RE.match(line)
                if prm or brm:
                    mm = prm or brm
                    part = mm.group("part")
                    sub = mm.group("sub")
                    rest = mm.group("rest")
                    mt, mk = tail_marks(rest)
                    if prm or mt:  # bare-letter rows require a marks tail
                        marks = mk
                        body = mt.group("body") if mt else rest
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body or "") if c.strip()]
                        gp = new_point(part, sub, chunks, marks, pageno)
                        last_part = part
                        buckets["point"] += lbl_n
                else:
                    sm = SUB_PAREN_RE.match(line) or SUB_BARE_RE.match(line)
                    if sm and last_part:
                        sub = sm.group("sub")
                        rest = sm.group("rest")
                        mt, mk = tail_marks(rest)
                        marks = mk
                        body = mt.group("body") if mt else rest
                        chunks = [c.strip() for c in re.split(r"\s{2,}", body or "") if c.strip()]
                        gp = new_point(last_part, sub, chunks, marks, pageno)
                        buckets["point"] += lbl_n
            if gp is not None:
                continue

            # continuation line
            if cur_point is not None and raw[:2].strip() == "" and st:
                mt0, mk0 = tail_marks(st)
                if (mt0 and mk0 is not None and cur_point["marks"] is not None
                        and (mt0.group("body") or "").strip()
                        and not NOTE_KW_START_RE.match(mt0.group("body"))):
                    # a further answer row of the same part carrying its own
                    # marks cell (alternative answers / multi-row parts) —
                    # never absorb it into the previous point's notes
                    body = mt0.group("body").strip()
                    chunks = [c.strip() for c in re.split(r"\s{2,}", body) if c.strip()]
                    new_point(cur_point["part"], cur_point["sub"], chunks,
                              mk0, pageno)
                    buckets["point"] += lbl_n
                    continue
                buckets["continuation"] += lbl_n
                if cur_point["marks"] is None:
                    mt = MARKS_TAIL_RE.match(st)
                    if mt and (mt.group("body") or "").strip():
                        # wrapped marks recovered
                        cur_point["text"].append(mt.group("body").strip())
                        cur_point["marks"] = int(mt.group("mk"))
                        continue
                (cur_point["notes"] if cur_point["text"] else cur_point["text"]).append(st)
                continue
            if st:
                if GUIDANCE_RE.search(st) and cur is not None:
                    cur["guidance"].append({"page": pageno, "text": st})
                    buckets["guidance"] += lbl_n
                else:
                    unclassified.append({"page": pageno, "text": st, "reason": "unclassified"})
                    buckets["unclassified"] += lbl_n

    for q in questions:
        q["pages"] = sorted(q["pages"])
        # merged-cell recovery: when exactly ONE point lacks a printed marks
        # cell and the question's total row is known, the missing value is
        # fully determined (total - resolved sum). Never guesses otherwise.
        unresolved = [p for p in q["points"] if p["marks"] is None]
        resolved_sum = sum(p["marks"] for p in q["points"] if p["marks"] is not None)
        if q["total_row"] is not None and len(unresolved) == 1:
            diff = q["total_row"] - resolved_sum
            if diff > 0:
                unresolved[0]["marks"] = diff
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
        q["points"] = kept
        q["sum_points"] = sum(p["marks"] for p in q["points"])
        q["label_count"] = len(q["points"])
        q["unresolved_marks"] = []
        q["arithmetic_ok"] = (q["total_row"] is not None and not q["unresolved_marks"]
                              and q["sum_points"] == q["total_row"])
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
