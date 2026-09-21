"""Deterministic QP question segmentation over the PyMuPDF block stream.

Atom = TOP-LEVEL question (operator decision), parts stay inside prompt text
for Phase 1 (agent refinement is Phase 2). Boundaries are accepted only in
the expected sequence (1, 2, 3, ...) and each question closes on its printed
total line ("Total for Question N = X marks" / "... is X marks"). This
expected-sequence + total-closing discipline is what prevents the 27-spillover
failure mode of the old regex extractor.

Deterministic. Unresolved deficits go to the caller as flags — never dropped.
"""
import json
import re

TOTAL_FOR_Q_RE = re.compile(
    r"Total\s+for\s+Question\s*(\d{1,2})\s*(?:=|is)\s*(\d{1,3})\s*marks?", re.I)
WITNESS_RES = [
    re.compile(r"total\s+marks?\s+for\s+this\s+paper\s+is\s+(\d{2,3})", re.I),
    re.compile(r"TOTAL\s+FOR\s+PAPER\s*=\s*(\d{2,3})\s*MARKS", re.I),
]
BOUNDARY_RE = re.compile(r"^\s*(?P<qn>\d{1,2})(?:[\.\)]\s+|\s+)(?P<t>\S.*)$")
BARE_NUM_RE = re.compile(r"^\s*(?P<qn>\d{1,2})\s*$")
FURNITURE_RES = [
    re.compile(r"^\*P[0-9A-Z]+\*$"),
    re.compile(r"^PMT$"),
    re.compile(r"^Turn over$", re.I),
    re.compile(r"^BLANK PAGE$", re.I),
]
FOOTER_Y_MIN = 780.0  # page-footer band: page numbers / Turn over sit at y0>=798
DOTS_RE = re.compile(r"^[.\s]+$")  # dotted answer lines are not stems


def furniture(s):
    for r in FURNITURE_RES:
        if r.match(s):
            return True
    return False


def parse_blocks(blocks):
    """blocks: list of {"page","kind","text",...} (text + image + total-row)."""
    atoms = []
    cur = None
    expected = 1
    witnesses = []
    paper_figures = []

    def open_atom(qn, page, first_line=None):
        nonlocal cur
        cur = {"number": qn, "total": None, "prompt": [], "pages": set(),
               "figures": []}
        if first_line is not None:
            cur["prompt"].append(first_line)
        cur["pages"].add(page)
        atoms.append(cur)

    for b in blocks:
        page = b["page"]
        if b["kind"] == "image":
            fig = {"asset": b["text"].split("(")[1].rstrip(")") if "(" in b["text"] else b["text"],
                   "page": page}
            if cur is not None:
                cur["figures"].append(fig)
                cur["pages"].add(page)
            else:
                paper_figures.append(fig)
            continue
        if b["kind"] != "text":
            continue
        line = b["text"].strip()
        if not line:
            continue
        tm = TOTAL_FOR_Q_RE.search(line)
        if b.get("y0", 0.0) > FOOTER_Y_MIN and tm is None:
            continue  # page footer band (page numbers, Turn over). A printed
            # question total row is QUESTION furniture, never PAGE furniture —
            # old-spec layouts sit it inside the footer band (4CH0 Jan-2016 1C).
        if furniture(line):
            continue

        if tm:
            qn = int(tm.group(1))
            val = int(tm.group(2))
            if cur is not None and cur["number"] == qn and cur["total"] is None:
                cur["total"] = val
                cur = None  # closed
                expected = qn + 1
            else:
                # total without matching open atom -> record for review by caller
                atoms.append({"number": qn, "total": val, "orphan_total": True,
                              "prompt": [], "pages": {page}, "figures": []})
                cur = None
                expected = qn + 1
            continue

        for w in WITNESS_RES:
            wm = w.search(line)
            if wm:
                witnesses.append({"page": page, "value": int(wm.group(1)), "text": line})

        can_open = (cur is None) or (cur.get("total") is not None)
        bm = BOUNDARY_RE.match(line)
        bn = BARE_NUM_RE.match(line)
        qn = None
        first = None
        if bm and int(bm.group("qn")) == expected and not DOTS_RE.match(bm.group("t")):
            qn = int(bm.group("qn"))
            first = bm.group("t")
        elif bn and int(bn.group("qn")) == expected:
            qn = int(bn.group("qn"))
            first = None
        if qn is not None and can_open:
            open_atom(qn, page, first)
            expected = qn + 1
            continue

        if cur is not None:
            cur["prompt"].append(line)
            cur["pages"].add(page)

    for a in atoms:
        a["pages"] = sorted(a["pages"])
        a.setdefault("orphan_total", False)

    # merge orphan totals into real atoms if one matches by number without total
    real = [a for a in atoms if not a.get("orphan_total")]
    orphans = [a for a in atoms if a.get("orphan_total")]
    for o in orphans:
        match = [a for a in real if a["number"] == o["number"] and a["total"] is None]
        if match:
            match[0]["total"] = o["total"]
    return {"questions": real, "witnesses": witnesses,
            "paper_figures": paper_figures,
            "orphan_totals": [o["number"] for o in orphans]}


def load_blocks(blocks_json):
    with open(blocks_json, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    r = parse_blocks(load_blocks(sys.argv[1]))
    print(json.dumps({"n_questions": len(r["questions"]),
                      "questions": [{"number": q["number"], "total": q["total"],
                                     "pages": q["pages"], "figures": len(q["figures"]),
                                     "prompt_lines": len(q["prompt"])}
                                    for q in r["questions"]],
                      "witnesses": r["witnesses"],
                      "orphan_totals": r["orphan_totals"]}, indent=1))
