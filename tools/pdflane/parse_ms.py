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
    unclassified = []
    guidance = []          # {page, text, labels}
    witnesses = []
    buckets = {"point": 0, "guidance": 0, "unclassified": 0, "continuation": 0}

    def ensure_question(qn):
        nonlocal cur
        if cur is None or cur["number"] != qn:
            cur = {"number": qn, "total_row": None, "total_row_page": None,
                   "points": [], "guidance": [], "pages": set()}
            questions.append(cur)

    for p in pages:
        pageno = p["page"]
        for raw in p["text"].splitlines():
            line = clean_line(raw)
            if line is None:
                continue
            st = line.strip()
            lbl_n = len(re.findall(r"\b[MA]\d{1,2}\b", st))  # per-line accounting unit

            m = TOTAL_RE.match(line)
            if m:
                if cur is not None and cur["total_row"] is None:
                    cur["total_row"] = int(m.group(1))
                    cur["total_row_page"] = pageno
                    cur_point = None
                    pending_label = None
                else:
                    unclassified.append({"page": pageno, "text": st,
                                         "reason": "total-row-without-open-question"})
                    buckets["unclassified"] += len(re.findall(r"\b[MA]\d{1,2}\b", st))
                continue

            for w in WITNESS_RES:
                wm = w.search(st)
                if wm:
                    witnesses.append({"page": pageno, "value": int(wm.group(1)), "text": st})

            # --- pending bare-label digit completion: "M" ended previous line,
            #     this line starts with its digit(s) ---
            if pending_label is not None:
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

            # continuation line
            if cur_point is not None and raw[:2].strip() == "" and st:
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
        q["sum_points"] = sum(p["marks"] for p in q["points"] if p["marks"] is not None)
        q["label_count"] = len(q["points"])
        q["unresolved_marks"] = [p["label"] for p in q["points"] if p["marks"] is None]
        q["arithmetic_ok"] = (q["total_row"] is not None and not q["unresolved_marks"]
                              and q["sum_points"] == q["total_row"])
        for p in q["points"]:
            p["text"] = " ".join(p["text"]).strip()

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
