"""Emit syllabai.pastpaper.atoms/1.1 from pdflane parse outputs (S5 v2 packaging).

Builds render-ready atoms (stem + parts + connected mark scheme) from the
deterministic QP block stream and the structured mark scheme (S2 accepted run
preferred, deterministic parse_ms fallback). The QP walk repeats parse_qp's
boundary discipline (expected sequence + total-closing) and is CROSS-CHECKED
against parse_qp.parse_blocks output — any divergence aborts the emit.

Determinism: identical inputs => byte-identical questions.json / ms.md.
No silent loss: unclassifiable lines degrade to para blocks; deficits surface
as atom flags and staging review rows, never as dropped content.
"""
import re

from pdflane import parse_qp

PART_OPENER_RE = re.compile(r"^\((?P<label>[a-z])\)\s*(?:\((?P<sub>[ivx]+)\))?\s*(?P<rest>.*)$")
# G1.2 (RC-C): rest may be EMPTY — old-spec QPs print the sub-part opener
# alone on its own line ((iii) above a diagram block). Requiring ".+" made
# every standalone "(ii)"/"(iii)"/"(iv)" a body line, so the sub-part never
# opened and its printed "(1)" filled the parent instead (evidence:
# 4CH0 1C June 2011 q2 — QP parts 4 vs MS 6 while the MS closes 6/6).
SUB_OPENER_PAREN_RE = re.compile(r"^\((?P<sub>[ivx]+)\)\s*(?P<rest>.*)$")
SUB_OPENER_BARE_RE = re.compile(r"^(?P<sub>[ivx]{1,4})\)\s*(?P<rest>.*)$")
STANDALONE_MARKS_RE = re.compile(r"^\((?P<n>\d{1,2})\)$")
TRAILING_MARKS_RE = re.compile(r"\s*\((?P<n>\d{1,2})\)$")
SELECT_STEM_RE = re.compile(
    r"(put a cross|place a cross|put a tick|place a tick|tick\s*\(|cross\s*\("
    r"|circle the (?:correct|letter)|one option)", re.I)
LETTER_OPTION_RE = re.compile(r"^(?P<label>[A-D])[.\)]\s*(?P<md>\S.*)$")
DOT_LINE_RE = re.compile(r"^(?P<idx>\d{1,2}\s+)?(?P<dots>[.\s]+)$")

NOTE_PREFIX_RULES = [
    ("do not accept", "reject"), ("do not allow", "reject"),
    ("reject", "reject"), ("accept", "allow"), ("allow", "allow"),
    ("ignore", "ignore"),
]

ATOM_FLAGS_ORDER = ["MS-ONLY-NO-QP", "QP-TOTAL-MISSING", "MS-QUESTION-MISSING",
                    "PRINTED-TOTAL-DISCREPANCY-QP-VS-MS", "MS-POINTS-DONT-CLOSE",
                    "PART-MARKS-MISMATCH",
                    "QP-STEM-MARKS-MARKER", "MS-PART-NO-POINTS", "MS-POINT-UNKNOWN-PART"]


class EmitError(Exception):
    pass


def is_furniture_image(bb):
    """True for edge-clipped margin strips that the raster extractor reports
    as figure XObjects but that carry no question content (page furniture).
    Observed population: 23.7x761.7pt strips clipped at the page edge (the
    June-2024 4CH1 QP prints 17 of them, all identical). Conservative shape
    rule: extreme aspect ratio AND at least 200pt long — real content figures
    never satisfy both."""
    if not isinstance(bb, dict):
        return False
    try:
        w = abs(float(bb["x1"]) - float(bb["x0"]))
        h = abs(float(bb["y1"]) - float(bb["y0"]))
    except (KeyError, TypeError, ValueError):
        return False
    short, long = min(w, h), max(w, h)
    return short > 0 and long >= 200.0 and long / short >= 8.0


def classify_note(text):
    t = text.strip()
    low = t.lower()
    for prefix, cat in NOTE_PREFIX_RULES:
        if low.startswith(prefix):
            rest = t[len(prefix):].lstrip(" :—-")
            return cat, rest
    return "notes", t


def tidy(s):
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def is_dot_line(s):
    return s.count(".") >= 6 and bool(DOT_LINE_RE.match(s.strip()))


def strip_dots_index(s):
    m = DOT_LINE_RE.match(s.strip())
    return m.group("idx"), m.group("dots")


class _Container:
    """Where blocks are currently being appended (stem or a part)."""

    def __init__(self):
        self.stem = []
        self.parts = []

    def new_part(self, label, sub, marks, page):
        p = {"id": None, "label": label, "sub": sub, "type": "open", "marks": marks,
             "commandWord": None, "prompt": [], "answerLines": 0, "pages": {page}}
        self.parts.append(p)
        return p

    @property
    def current(self):
        return self.parts[-1] if self.parts else None

    def add_block(self, blk, page):
        tgt = self.current
        if tgt is not None:
            tgt["prompt"].append(blk)
            tgt["pages"].add(page)
        else:
            self.stem.append(blk)

    def blocks_for_append(self):
        return self.current["prompt"] if self.current is not None else self.stem


def _finish_choices(pending_choices, container, page):
    if not pending_choices:
        return
    items = [{"label": lb, "md": tidy(md)} for lb, md in pending_choices]
    container.add_block({"type": "choices", "items": items}, page)
    pending_choices.clear()


def _seal(cur, container):
    for p in container.parts:
        pid = "%d%s" % (cur["number"], p["label"])
        if p["sub"]:
            pid += "-" + p["sub"]
        p["id"] = pid
        p["pages"] = sorted(p["pages"])
        if any(b["type"] == "choices" for b in p["prompt"]):
            p["type"] = "mcq"
    cur["stem"] = container.stem
    cur["parts"] = container.parts


def build_qp_atoms(qp_blocks):
    """Walk the pymupdf block stream with parse_qp's boundary discipline,
    emitting v2 atoms with stem/part segmentation and interleaved images.

    G1.2 (RC-F): the returned list carries .orphan_events — every question
    number whose total row did not close its own open atom (parse_qp records
    an orphan entry for exactly those events; kept or merged). crosscheck_qp
    uses it for parity."""
    atoms = []
    orphan_numbers = []  # G1.2 (RC-F): every total row that did not close its own open atom
    pending_part_openers = []  # G1.2 (RC-C): opener-shaped lines seen between atoms
    cur = None
    container = None
    expected = 1
    pending_choices = []

    def open_atom(qn, page):
        nonlocal cur, container, pending_choices
        cur = {"number": qn, "total": None, "pages": {page}, "_stem_marks": []}
        container = _Container()
        pending_choices = []
        atoms.append(cur)

    for b in qp_blocks:
        page = b["page"]
        if b["kind"] == "image":
            if cur is not None and cur["total"] is None:
                asset = b["text"].split("(")[1].rstrip(")") if "(" in b["text"] else b["text"]
                asset = asset.strip()
                if asset.startswith("assets/"):
                    asset = asset[len("assets/"):]
                _finish_choices(pending_choices, container, page)
                blk = {"type": "image", "src": "assets/" + asset, "pages": [page]}
                bb = b.get("bbox")
                if isinstance(bb, dict) and all(k in bb for k in ("x0", "y0", "x1", "y1")):
                    blk["bbox"] = {"page": page, "x0": round(float(bb["x0"]), 1),
                                   "y0": round(float(bb["y0"]), 1),
                                   "x1": round(float(bb["x1"]), 1),
                                   "y1": round(float(bb["y1"]), 1),
                                   "units": "pt"}
                container.add_block(blk, page)
                cur["pages"].add(page)
            continue
        if b["kind"] != "text":
            continue
        line = b["text"].strip()
        if not line:
            continue
        tm = parse_qp.TOTAL_FOR_Q_RE.search(line)
        if b.get("y0", 0.0) > parse_qp.FOOTER_Y_MIN and tm is None:
            # page-footer band. A printed question total row is QUESTION
            # furniture, never PAGE furniture — old-spec layouts sit it inside
            # the footer band (e.g. 4CH0 Jan-2016 1C Q3/Q9/Q10 at y0 792-801).
            continue
        if parse_qp.furniture(line):
            continue

        if tm:
            qn, val = int(tm.group(1)), int(tm.group(2))
            if cur is not None and cur["number"] == qn and cur["total"] is None:
                cur["total"] = val
                _seal(cur, container)
                cur = None
                expected = qn + 1
                continue
            if cur is None:
                match = [a for a in atoms if a["number"] == qn
                         and a["total"] is None and not a.get("orphan_total")]
                if match:
                    match[0]["total"] = val
                    expected = qn + 1
                    orphan_numbers.append(qn)  # parse_qp recorded an orphan+merge here
                    continue
            # G1.2 (RC-F): a total row whose question never opened (rasterized
            # opener page — e.g. 4CH1 1C June 2019 pages 1/2/4/12/16/18/20/26
            # carry no text layer — or out-of-sequence reprint) is an ORPHAN
            # total, never a hard abort. parse_qp.parse_blocks already tolerates
            # this (orphan atom + end-of-stream merge); the walk now mirrors it
            # so the two can never diverge. The orphan stays disclosed:
            # run_paper emits a QP-OPENER-UNSEEN review row and excludes the
            # stub from the product (the stem is deterministically unavailable).
            if cur is not None:
                _seal(cur, container)  # abandon-in-place: keep the open atom
                cur = None
            orphan_numbers.append(qn)
            atoms.append({"number": qn, "total": val, "prompt": [],
                          "pages": [page], "figures": [],
                          "stem": {"blocks": []}, "parts": [],
                          "orphan_total": True})
            expected = qn + 1
            continue

        can_open = (cur is None) or (cur.get("total") is not None)
        bm = parse_qp.BOUNDARY_RE.match(line)
        bn = parse_qp.BARE_NUM_RE.match(line)
        qn = first = None
        if bm and int(bm.group("qn")) == expected \
                and not parse_qp.DOTS_RE.match(bm.group("t")):
            qn, first = int(bm.group("qn")), bm.group("t")
        elif bn and int(bn.group("qn")) == expected:
            qn = int(bn.group("qn"))
        if qn is not None and can_open:
            open_atom(qn, page)
            expected = qn + 1
            for ppage, pline in pending_part_openers:
                if ppage == page:
                    _route_text(cur, container, pending_choices, pline, page)
            pending_part_openers = []
            if first is not None:
                _route_text(cur, container, pending_choices, first, page)
            continue

        if cur is None or cur["total"] is not None:
            # G1.2 (RC-C): some layouts print the part-opener text block BEFORE
            # the question-number block (PyMuPDF column order: '(a) Complete
            # the table...' then a separate '1' block). Buffer opener-shaped
            # lines seen between atoms; when the next atom opens on the same
            # page they route first, so part (a) is not lost.
            pom = PART_OPENER_RE.match(line)
            if pom and not is_dot_line(pom.group("rest") or ""):
                pending_part_openers.append((page, line))
            continue  # front matter / post-closing furniture
        cur["pages"].add(page)
        _route_text(cur, container, pending_choices, line, page)

    if cur is not None and cur["total"] is None:
        _seal(cur, container)
    # G1.2 (RC-F): mirror parse_qp's end-of-stream orphan merge — an orphan
    # total whose question materialized without a total closes that question.
    real = [a for a in atoms if not a.get("orphan_total")]
    kept_orphans = []
    for o in atoms:
        if not o.get("orphan_total"):
            continue
        match = [a for a in real if a["number"] == o["number"] and a["total"] is None]
        if match:
            match[0]["total"] = o["total"]
        else:
            kept_orphans.append(o)
    out = _AtomList(real + kept_orphans)
    out.orphan_events = orphan_numbers
    return out


class _AtomList(list):
    """List of atoms with a .orphan_events side-channel (G1.2 RC-F parity)."""
    orphan_events = None


ROMAN_RE = re.compile(r"^[ivx]{1,4}$")
ID_SHAPE_RE = re.compile(r"^(?P<part>[a-z])(?:-(?P<rest>[a-z0-9]+))?$")
LEVEL_BAND_RE = re.compile(
    r"level\s*(?P<lvl>\d{1,2})\s*\(\s*(?P<lo>\d{1,2})\s*[\u2013\u2014-]\s*(?P<hi>\d{1,2})\s*marks?\s*\)",
    re.I)

MCQ_BARE_RE = re.compile(r"^\(?([A-Ea-e])\)?[.:]?$")
MCQ_IS_CORRECT_RE = re.compile(
    r"^(?:the\s+)?(?:only\s+)?correct\s+(?:answer\s+)?is[:\s]*\(?([A-Ea-e])\)?\)?[.:]?$", re.I)
MCQ_ANSWER_IS_RE = re.compile(
    r"^(?:the\s+)?answer\s+is[:\s]*\(?([A-Ea-e])\)?\)?[.:]?$", re.I)


def _mcq_letters(md):
    """Correct-choice letters deterministically readable from an MS point md.
    Conservative: only bare labels and 'answer is X' phrasings count."""
    s = (md or "").strip()
    if not s:
        return []
    for rx in (MCQ_BARE_RE, MCQ_IS_CORRECT_RE, MCQ_ANSWER_IS_RE):
        m = rx.match(s)
        if m:
            return [m.group(1)]
    return []


def _detect_levels(guidance):
    """Conservative levels-marking detection from printed band headers.

    Edexcel levels grids print 'Level N (x\u2013y marks)' rows; >= 2 distinct
    levels promote the mark scheme to style=levels. Verbatim guidance text is
    preserved regardless (no silent loss); continuation lines between band
    headers attach to the preceding band as its descriptor.
    """
    bands = []
    for g in guidance:
        m = LEVEL_BAND_RE.search(g)
        if m:
            lvl, lo, hi = int(m.group("lvl")), int(m.group("lo")), int(m.group("hi"))
            desc = tidy(g[m.end():].lstrip(" :\u2014\u2013-"))
            for b in bands:
                if b["level"] == lvl:
                    if desc:
                        b["descriptor"] = (b["descriptor"] + " " + desc).strip()
                    break
            else:
                bands.append({"level": lvl, "markRange": {"min": lo, "max": hi},
                              "descriptor": desc or ("level %d" % lvl)})
        elif bands and g.strip():
            bands[-1]["descriptor"] = (bands[-1]["descriptor"] + " " + tidy(g)).strip()
    if len(bands) < 2:
        return None
    return {"maxMarks": max(b["markRange"]["max"] for b in bands), "bands": bands}


def _norm_ms_image(im):
    """Normalize a vision-attached MS figure to the msImage shape (or None)."""
    if not isinstance(im, dict):
        return None
    src = im.get("src")
    pages = im.get("pages") or []
    if not src or not pages:
        return None
    if not src.startswith("assets/"):
        src = "assets/" + str(src).lstrip("/")
    out = {"src": src, "pages": [int(x) for x in pages]}
    if im.get("alt"):
        out["alt"] = str(im["alt"])
    return out


def _map_id_shape(pt):
    """Phase-2 id-shape points (id like 'a', 'a-key', 'a-ii', 'c-b1') -> (part, sub)."""
    pid = pt.get("id") or ""
    m = ID_SHAPE_RE.match(pid)
    if not m:
        return None, None
    rest = m.group("rest")
    if rest is None:
        return m.group("part"), None
    sub = rest if ROMAN_RE.match(rest) else None
    return m.group("part"), sub


def _route_text(cur, container, pending_choices, line, page):
    m = PART_OPENER_RE.match(line)
    if m and not is_dot_line(m.group("rest") or ""):
        rest = m.group("rest") or ""
        label = m.group("label")
        # '(i)' standalone is a roman sub-opener when a letter part is open
        if ROMAN_RE.match(label) and container.parts:
            sub = label
            label = container.parts[-1]["label"]
            marks = None
            tm = TRAILING_MARKS_RE.search(rest)
            if tm:
                marks = int(tm.group("n"))
                rest = rest[:tm.start()].rstrip()
            _finish_choices(pending_choices, container, page)
            p = container.new_part(label, sub, marks, page)
            if rest:
                _route_body(cur, container, pending_choices, rest, page)
            return
        marks = None
        tm = TRAILING_MARKS_RE.search(rest)
        if tm:
            marks = int(tm.group("n"))
            rest = rest[:tm.start()].rstrip()
        _finish_choices(pending_choices, container, page)
        p = container.new_part(label, m.group("sub"), marks, page)
        if rest:
            _route_body(cur, container, pending_choices, rest, page)
        return

    for rx in (SUB_OPENER_PAREN_RE, SUB_OPENER_BARE_RE):
        m = rx.match(line)
        if m and not is_dot_line(m.group("rest")):
            if not container.parts:
                break  # cannot attach a sub-part without a part letter
            _finish_choices(pending_choices, container, page)
            rest = m.group("rest")
            marks = None
            tm = TRAILING_MARKS_RE.search(rest)
            if tm:
                marks = int(tm.group("n"))
                rest = rest[:tm.start()].rstrip()
            label = container.parts[-1]["label"]
            p = container.new_part(label, m.group("sub"), marks, page)
            if rest:
                _route_body(cur, container, pending_choices, rest, page)
            return

    sm = STANDALONE_MARKS_RE.match(line)
    if sm:
        _finish_choices(pending_choices, container, page)
        n = int(sm.group("n"))
        tgt = container.current
        if tgt is not None and tgt["marks"] is None:
            tgt["marks"] = n
        else:
            cur["_stem_marks"].append(n)
        return

    _route_body(cur, container, pending_choices, line, page)


def _route_body(cur, container, pending_choices, line, page):
    if is_dot_line(line):
        _finish_choices(pending_choices, container, page)
        blocks = container.blocks_for_append()
        tgt = container.current
        if blocks and blocks[-1]["type"] == "answer_lines":
            blocks[-1]["count"] += 1
            if tgt is not None:
                tgt["answerLines"] += 1
        else:
            blocks.append({"type": "answer_lines", "count": 1})
            if tgt is not None:
                tgt["answerLines"] += 1
        return

    tgt = container.current
    select_blocks = tgt["prompt"] if tgt is not None else container.stem
    in_select = _in_select_context(select_blocks)

    lm = LETTER_OPTION_RE.match(line)
    if in_select and lm:
        pending_choices.append((lm.group("label"), lm.group("md")))
        return
    if in_select and _looks_like_option(line):
        pending_choices.append((str(len(pending_choices) + 1), line))
        return

    tm = TRAILING_MARKS_RE.search(line)
    if tm:
        marks = int(tm.group("n"))
        body = line[:tm.start()].rstrip()
        if body:
            _add_para(container, body, page)
        if tgt is not None and tgt["marks"] is None:
            tgt["marks"] = marks
        else:
            cur["_stem_marks"].append(marks)
        return

    _add_para(container, line, page)


def _in_select_context(blocks):
    for blk in reversed(blocks):
        if blk["type"] == "para":
            return bool(SELECT_STEM_RE.search(blk["md"]))
        if blk["type"] in ("choices", "answer_lines", "table", "image"):
            continue
    return False


def _looks_like_option(line):
    if len(line) > 42:
        return False
    if line.endswith((".", "?", "!", ":")):
        return False
    if line.startswith("("):
        return False
    if is_dot_line(line):
        return False
    return 0 < len(line.split()) <= 6


def _add_para(container, text, page):
    md = tidy(text)
    if not md:
        return
    container.add_block({"type": "para", "md": md}, page)


def crosscheck_qp(atoms, qp_parse):
    """The v2 walk must agree with the proven deterministic parser.

    G1.2 (RC-F): orphan totals are compared too — parse_qp records an orphan
    entry for every total row that did not close its own open atom (merged or
    not), so the walk must have seen the same events in the same order of
    question numbers. Merged orphans are recorded via orphan_numbers at the
    moment of synthesis/late-close, so both sides list them."""
    real = [q for q in qp_parse["questions"] if not q.get("orphan_total")]
    walk = [a for a in atoms if not a.get("orphan_total")]
    if len(real) != len(walk):
        raise EmitError("question count divergence: v2=%d parse_qp=%d"
                        % (len(walk), len(real)))
    walk_orphans = sorted(getattr(atoms, "orphan_events", None) or [])
    parse_orphans = sorted(qp_parse.get("orphan_totals") or [])
    if walk_orphans != parse_orphans:
        raise EmitError("orphan-total divergence: v2=%s parse_qp=%s"
                        % (walk_orphans, parse_orphans))
    for a, q in zip(walk, real):
        if a["number"] != q["number"]:
            raise EmitError("number divergence: v2=%d parse_qp=%d"
                            % (a["number"], q["number"]))
        if a["total"] != q["total"]:
            raise EmitError("total divergence q%d: v2=%r parse_qp=%r"
                            % (a["number"], a["total"], q["total"]))
        if sorted(a["pages"]) != sorted(q["pages"]):
            raise EmitError("page divergence q%d: v2=%r parse_qp=%r"
                            % (a["number"], sorted(a["pages"]), sorted(q["pages"])))


def build_mark_scheme(s2q, parse_ms_q, line_page=None):
    """markScheme object from the S2 accepted run (preferred) or parse_ms."""
    if s2q is not None:
        points, guidance = [], []
        for pt in s2q.get("points", []):
            pages = set()
            if "label" in pt:
                pid, part, sub = pt["label"], pt.get("part"), pt.get("sub")
            else:
                pid = pt.get("id")
                part, sub = _map_id_shape(pt)
            if line_page:
                for n in pt.get("lines", []):
                    if n in line_page:
                        pages.add(line_page[n])
            cat_map = {"allow": [], "reject": [], "ignore": [], "notes": []}
            for note in pt.get("notes", []):
                cat, rest = classify_note(note["text"])
                cat_map[cat].append(rest)
                if line_page:
                    for n in note.get("lines", []):
                        if n in line_page:
                            pages.add(line_page[n])
            entry = {
                "id": pid, "part": part, "sub": sub,
                "marks": int(pt["marks"]), "md": tidy(pt.get("text") or ""),
                "allow": cat_map["allow"], "reject": cat_map["reject"],
                "ignore": cat_map["ignore"], "notes": cat_map["notes"],
                "pages": sorted(pages),
            }
            if pt.get("image"):
                im = _norm_ms_image(pt["image"])
                if im:
                    entry["image"] = im
            if pid and pid.endswith("-key") and not entry["md"] \
                    and entry["marks"] >= 2:
                entry["pool"] = {"rule": "any-%d-for-1-each" % entry["marks"]}
            points.append(entry)
        for g in s2q.get("guidance", []):
            guidance.append(tidy(g["text"] if isinstance(g, dict) else g))
        printed = s2q.get("totalRow")
        provenance = "llm-structured"
        pools = [_norm_pool(p) for p in (s2q.get("pools") or [])]
        ms_images = [im for im in (_norm_ms_image(x)
                                   for x in (s2q.get("images") or [])) if im]
    else:
        points = []
        for pt in (parse_ms_q or {}).get("points", []):
            text = pt["text"] if isinstance(pt["text"], str) \
                else " ".join(pt["text"])
            text = text.strip()
            cat_map = {"allow": [], "reject": [], "ignore": [], "notes": []}
            for note in pt.get("notes", []):
                cat, rest = classify_note(note)
                cat_map[cat].append(rest)
            points.append({
                "id": pt["label"], "part": pt.get("part"), "sub": pt.get("sub"),
                "marks": int(pt["marks"]), "md": tidy(text),
                "allow": cat_map["allow"], "reject": cat_map["reject"],
                "ignore": cat_map["ignore"], "notes": cat_map["notes"],
                "pages": [pt["page"]],
            })
        guidance = [tidy(g["text"]) for g in (parse_ms_q or {}).get("guidance", [])]
        printed = (parse_ms_q or {}).get("total_row")
        provenance = "pdf-parsed"
        # G1 upgrade: deterministic capped alternative groups ('Any N for M
        # each') become pools with position indices — same collapse semantics
        # as the S2-lane pools (members contribute their cap, not their sum).
        # Member points are matched by identity to survive the 1:1 point list
        # built above.
        pools = []
        ms_pts = (parse_ms_q or {}).get("points", []) or []
        for cg in (parse_ms_q or {}).get("capped_groups", []) or []:
            # indices are resolved post-demotion by parse_ms; identity match
            # against ms_pts remains as the fallback for raw groups
            idxs = cg.get("indices")
            if idxs is None:
                idxs = [i for i, p in enumerate(ms_pts)
                        if any(p is m for m in cg.get("_members", []))]
            if not idxs:
                continue
            pools.append({"part": _pool_part_key(points[idxs[0]]),
                          "labels": [points[i]["id"] for i in idxs],
                          "cap": int(cg["anyN"]) * int(cg["per"]),
                          "indices": idxs,
                          "reason": "any-%d-for-%d-each" % (cg["anyN"], cg["per"])})
        ms_images = []
    levels = _detect_levels(guidance) if guidance else None
    if levels:
        # Levels-based award: the ceiling is the highest band, not a point sum.
        # Point entries (if any printed) are preserved verbatim but not summed.
        total_sum = int(levels["maxMarks"])
    else:
        total_sum = _closable_sum(points, pools)
    ms = {"totals": {"printed": printed, "sum": total_sum,
                     "verified": bool(printed is not None and printed == total_sum)},
          "guidance": guidance, "points": points, "provenance": provenance}
    if levels:
        ms["style"] = "levels"
        ms["levels"] = levels
    if pools:
        ms["pools"] = pools
    if ms_images:
        ms["images"] = ms_images
    return ms


POOL_PART_RE = re.compile(r"^(?P<letter>[a-z])(?:-(?P<sub>[ivx]+))?$")


def _pool_part_key(pt):
    """G1 upgrade: deterministic-lane pools carry the member block's part in
    the S2 dash form ('b-i') so the letter-level cross-check adds the pool cap
    to the right letter."""
    part = (pt or {}).get("part") or ""
    sub = (pt or {}).get("sub")
    return "%s-%s" % (part, sub) if (part and sub) else part


def _pool_letter(s):
    return (s or "")[0:1]


def _pool_matches(pt, pool, idx=None):
    if "indices" in pool:
        # G1 upgrade: deterministic-lane pools carry position indices (member
        # labels repeat across parts in old-spec mark schemes)
        return idx is not None and idx in pool["indices"]
    if pt["id"] not in pool["labels"]:
        return False
    if not pool["part"]:
        return True  # id-only pool: ids are unique (e.g. c-b1..c-b6)
    m = POOL_PART_RE.match(pool["part"])
    if not m:
        return _pool_letter(pool["part"]) == (pt["part"] or "")
    if m.group("letter") != (pt["part"] or ""):
        return False
    return m.group("sub") is None or pt["sub"] == m.group("sub")


def _norm_pool(pool):
    """Normalize the two S2 pool encodings to {part, labels, cap, reason}."""
    labels = pool.get("labels") or pool.get("ids") or []
    part = pool.get("part")
    if not part and labels:
        letters = set()
        for x in labels:
            m = ID_SHAPE_RE.match(x)
            if m:
                letters.add(m.group("part"))
        part = letters.pop() if len(letters) == 1 else ""
    return {"part": part or "", "labels": list(labels),
            "cap": int(pool["cap"]),
            **({"reason": pool["reason"]} if pool.get("reason") else {})}


def _closable_sum(points, pools):
    """Max awardable marks: pool members collapse to the pool cap.

    Pool membership is scoped: when the pool carries a part (letter form or
    'b-i' dash form), only points under that letter match; id-only pools match
    globally (their ids are unique, e.g. c-b1..c-b6).
    """
    total = 0
    for pool in pools or []:
        total += int(pool["cap"])
    for i, p in enumerate(points):
        if not any(_pool_matches(p, pool, i) for pool in pools or []):
            total += p["marks"]
    return total


def build_document(atoms, ms_questions, line_page=None, source_qp="qp.pdf",
                   source_ms="ms.pdf", s2_by_num=None, corrections=None):
    """Assemble the envelope; attach mark schemes; compute flags.

    Mark scheme source: S2 accepted run preferred; deterministic parse_ms
    fallback per question (either source alone is enough — the union of both
    question number sets is covered).

    corrections: operator-authorized printed-error fixes {qnum: corrected
    total-row value}, applied ONLY to a parsed total row (never to missing
    mark schemes); the correction file lives in lane _meta, the product stays
    clean.
    """
    ms_by_num = {q["number"]: q for q in ms_questions}
    s2_by_num = s2_by_num or {}
    out_atoms = []
    verified_all = True
    for a in atoms:
        flags = set()
        qnum = a["number"]
        if a["total"] is None:
            flags.add("QP-TOTAL-MISSING")
        s2q = s2_by_num.get(qnum)
        pmsq = ms_by_num.get(qnum)
        if s2q is None and pmsq is None:
            flags.add("MS-QUESTION-MISSING")
            ms = {"totals": {"printed": None, "sum": 0, "verified": False},
                  "guidance": [], "points": [], "provenance": "pdf-parsed"}
        else:
            ms = build_mark_scheme(s2q, pmsq, line_page)
        # G1 upgrade: a sum that closes against the QP printed total (but not
        # the MS total row — old-spec misprints) still counts as verified
        if s2q is None and not ms["totals"]["verified"] \
                and a["total"] is not None \
                and ms["totals"]["sum"] == a["total"]:
            ms["totals"]["verified"] = True
            ms["totals"]["verifiedAgainst"] = "qp-printed"
        if corrections and qnum in corrections and "MS-QUESTION-MISSING" not in flags:
            corrected = int(corrections[qnum])
            if ms["totals"]["printed"] is not None \
                    and ms["totals"]["printed"] != corrected:
                ms["totals"]["printed"] = corrected
                ms["totals"]["verified"] = (ms["totals"]["sum"] == corrected)
        printed = ms["totals"]["printed"]
        marks = a["total"]
        if marks is None and printed is not None:
            marks = printed
        if marks is None:
            raise EmitError("q%d: no QP total and no MS total row" % qnum)
        if a["total"] is not None and printed is not None and a["total"] != printed:
            flags.add("PRINTED-TOTAL-DISCREPANCY-QP-VS-MS")
        # G1 upgrade: the point sum must close to a printed source — the MS
        # total row OR the QP printed total (old-spec MSs carry misprinted
        # total rows; the QP/MS conflict stays flagged above for disclosure)
        if printed is not None and ms["totals"]["sum"] != printed \
                and ms["totals"]["sum"] != a["total"]:
            flags.add("MS-POINTS-DONT-CLOSE")
        # letter-level part cross-check (robust to MS/QP sub-structure divergence:
        # e.g. QP (a)(ii) worth 2 = MS a/ii + a/iii); pool members collapse to
        # their pool cap within their letter
        part_sums = {}
        exact_sub_sums = {}
        for pidx, p in enumerate(ms["points"]):
            if p["part"] is None:
                continue
            if not any(_pool_matches(p, pool, pidx) for pool in ms.get("pools", [])):
                part_sums[p["part"]] = part_sums.get(p["part"], 0) + p["marks"]
            key = (p["part"], p["sub"])
            exact_sub_sums[key] = exact_sub_sums.get(key, 0) + p["marks"]
        for pool in ms.get("pools", []):
            m = POOL_PART_RE.match(pool["part"] or "")
            if m:
                letter = m.group("letter")
                part_sums[letter] = part_sums.get(letter, 0) + int(pool["cap"])
        qp_letter_marks = {}
        letter_parts_count = {}
        for p in a["parts"]:
            letter_parts_count[p["label"]] = letter_parts_count.get(p["label"], 0) + 1
        letters_with_subs = {p["label"] for p in a["parts"] if p["sub"] is not None}

        def _is_parent(p):
            return p["sub"] is None and p["label"] in letters_with_subs

        # fill LEAF parts first (parents take their leaves' sum afterwards)
        for p in a["parts"]:
            if _is_parent(p):
                continue
            if p["marks"] is None:
                # fill only from unambiguous sources, never the letter sum when
                # the letter owns several parts (that would double-count)
                if (p["label"], p["sub"]) in exact_sub_sums:
                    p["marks"] = exact_sub_sums[(p["label"], p["sub"])]
                elif letter_parts_count[p["label"]] == 1 and p["sub"] is None:
                    p["marks"] = part_sums.get(p["label"], 1)
                else:
                    p["marks"] = 1
        for p in a["parts"]:
            if _is_parent(p):
                leaf_sum = sum(x["marks"] for x in a["parts"]
                               if x["label"] == p["label"] and x["sub"] is not None)
                p["marks"] = leaf_sum if leaf_sum else 1
        for p in a["parts"]:
            qp_letter_marks[p["label"]] = qp_letter_marks.get(p["label"], 0) + p["marks"]
            if ms.get("style") != "levels" \
                    and not any(pt["part"] == p["label"] for pt in ms["points"]):
                flags.add("MS-PART-NO-POINTS")
        # letter-level compare uses LEAF marks only (parents are containers)
        leaf_letter_marks = {}
        for p in a["parts"]:
            if _is_parent(p):
                continue
            leaf_letter_marks[p["label"]] = leaf_letter_marks.get(p["label"], 0) + p["marks"]
        for letter, qm in leaf_letter_marks.items():
            sm = part_sums.get(letter)
            if sm is not None and qm and sm != qm:
                flags.add("PART-MARKS-MISMATCH")
        # v1.1: structured correct-choice labels for MCQ parts (Target Test
        # auto-scoring). Conservative extraction: only when the MS point md
        # IS a bare choice label or an 'answer is X' phrasing; omitted entirely
        # when not derivable (never guessed).
        for p in a["parts"]:
            if p.get("type") != "mcq":
                continue
            choice_labels = []
            for blk in p["prompt"]:
                if blk["type"] == "choices":
                    choice_labels.extend(it["label"] for it in blk["items"])
            if not choice_labels:
                continue
            labset = set(choice_labels)
            corr = []
            for pt in ms["points"]:
                if pt["part"] != p["label"]:
                    continue
                if (pt["sub"] or None) != (p["sub"] or None):
                    continue
                for letter in _mcq_letters(pt["md"]):
                    u = letter.upper()
                    if u in labset and u not in corr:
                        corr.append(u)
            if corr:
                p["correct"] = corr
        for pt in ms["points"]:
            if pt["part"] is None:
                continue
            if pt["part"] not in qp_letter_marks:
                flags.add("MS-POINT-UNKNOWN-PART")
        parts_sum = sum(p["marks"] for p in a["parts"] if not _is_parent(p))
        stem_marks_sum = sum(a.get("_stem_marks", []))
        ms_closes = ms["totals"]["verified"]
        if a["parts"] and stem_marks_sum == 0 and parts_sum != marks and ms_closes:
            # letter-level check above is the primary cross-check; this catches
            # a QP-internal disagreement (leaf parts don't sum to the printed
            # total) and is only raised when the MS itself closes arithmetically
            flags.add("PART-MARKS-MISMATCH")
        if stem_marks_sum and not a["parts"] and stem_marks_sum != marks:
            flags.add("QP-STEM-MARKS-MARKER")
        if not ms["totals"]["verified"]:
            verified_all = False
        # G1 upgrade: the atom's marks come from the QP printed total — they
        # count as verified only when the MS point arithmetic supports that
        # value (closes to the printed row or to the QP total itself)
        if a["total"] is not None and ms["totals"]["sum"] != a["total"]:
            verified_all = False
        # PRINTED-TOTAL-DISCREPANCY-QP-VS-MS is disclosure-only since the G1
        # upgrade: a one-sided MS total-row misprint whose arithmetic closes
        # against the QP total is still verified marks (evidence: 4CH0 1C
        # jan2012 q3 — MS prints 'Total 11 marks', cells and QP both say 13)
        if flags & {"QP-TOTAL-MISSING",
                    "MS-QUESTION-MISSING", "MS-POINTS-DONT-CLOSE"}:
            verified_all = False

        atom = {
            "number": qnum,
            "type": "structured" if a["parts"] else (
                "mcq" if any(b["type"] == "choices" for b in a["stem"]) else "open"),
            "marks": marks,
            "commandWord": None,
            "stem": a["stem"],
            "parts": a["parts"],
            "markScheme": ms,
            "provenance": "pdf-parsed",
        }
        if flags:
            atom["flags"] = [f for f in ATOM_FLAGS_ORDER if f in flags]
        out_atoms.append(atom)
    doc = {
        "schema": "syllabai.pastpaper.atoms/1.1",
        "source": {"qp": source_qp, "ms": source_ms},
        "questionCount": len(out_atoms),
        "totalMarks": sum(x["marks"] for x in out_atoms),
        "marksVerified": verified_all,
        "questions": out_atoms,
    }
    return doc


def build_document_ms_only(ms_questions, line_page=None, source_ms="ms.pdf"):
    """MS-only envelope (COVID-session papers ship ms.pdf without a QP).

    No QP atoms exist: stem/parts stay empty, the atom type is "ms-only",
    marks come from the MS printed total row, and marksVerified stays False
    by construction — the printed-QP closure the G1 verifier needs is
    impossible without a QP. The mark scheme is still real parsed content
    (the paper-axis search substrate); only the arithmetic cross-check is
    absent, and that honesty is carried as the MS-ONLY-NO-QP flag.
    """
    out_atoms = []
    for q in ms_questions:
        qnum = q["number"]
        ms = build_mark_scheme(None, q, line_page)
        flags = {"MS-ONLY-NO-QP"}
        if ms["totals"]["printed"] is None:
            raise EmitError("q%d: MS-only and no printed total row" % qnum)
        if ms["totals"]["sum"] != ms["totals"]["printed"]:
            flags.add("MS-POINTS-DONT-CLOSE")
        atom = {
            "number": qnum,
            "type": "ms-only",
            "marks": ms["totals"]["printed"],
            "commandWord": None,
            "stem": [],
            "parts": [],
            "markScheme": ms,
            "provenance": "pdf-parsed",
        }
        ordered = [f for f in ATOM_FLAGS_ORDER if f in flags]
        if ordered:
            atom["flags"] = ordered
        out_atoms.append(atom)
    doc = {
        "schema": "syllabai.pastpaper.atoms/1.1",
        "source": {"qp": None, "ms": source_ms},
        "questionCount": len(out_atoms),
        "totalMarks": sum(x["marks"] for x in out_atoms),
        "marksVerified": False,
        "questions": out_atoms,
    }
    return doc


def render_ms_md(doc):
    """Atom-derived mark scheme sidecar (deterministic)."""
    lines = ["# Mark Scheme", ""]
    for atom in doc["questions"]:
        ms = atom["markScheme"]
        lines.append("## Q%d (%d marks)" % (atom["number"], atom["marks"]))
        lines.append("")
        cur_part = ("__unset__",)
        for p in ms["points"]:
            if (p["part"], p["sub"]) != cur_part:
                cur_part = (p["part"], p["sub"])
                head = "%d" % atom["number"] if p["part"] is None \
                    else "%d(%s)" % (atom["number"], p["part"])
                if p["sub"]:
                    head += "(%s)" % p["sub"]
                if lines and lines[-1] != "":
                    lines.append("")
                lines.append("### %s" % head)
                lines.append("")
            tail = " — %s" % p["md"] if p["md"] else ""
            if p["marks"] == 0:
                lines.append("- **%s** (alternative answer, not scored)%s" %
                             (p["id"], tail))
            else:
                lines.append("- **%s** (%d mark%s)%s" %
                             (p["id"], p["marks"], "" if p["marks"] == 1 else "s", tail))
            if p.get("pool"):
                lines.append("  - Pool: %s" % p["pool"]["rule"])
                for item in p["notes"]:
                    lines.append("  - %s" % item)
            else:
                for cat, tag in (("allow", "Allow"), ("reject", "Reject"),
                                 ("ignore", "Ignore")):
                    for item in p[cat]:
                        lines.append("  - %s: %s" % (tag, item))
                for item in p["notes"]:
                    lines.append("  - Note: %s" % item)
            if p.get("image"):
                lines.append("  - ![%s](%s)"
                             % (p["image"].get("alt", ""), p["image"]["src"]))
        if ms.get("style") == "levels":
            lv = ms["levels"]
            lines.append("")
            lines.append("**Levels-based marking (max %d marks)**" % lv["maxMarks"])
            lines.append("")
            for b in lv["bands"]:
                mr = b["markRange"]
                rng = "%d" % mr["max"] if mr["min"] == mr["max"] \
                    else "%d\u2013%d" % (mr["min"], mr["max"])
                lines.append("- **Level %d** (%s marks): %s"
                             % (b["level"], rng, b["descriptor"]))
            for ic in lv.get("indicativeContent", []):
                lines.append("- Indicative content: %s" % ic)
        for im in ms.get("images", []):
            lines.append("")
            lines.append("![%s](%s)" % (im.get("alt", ""), im["src"]))
        for g in ms["guidance"]:
            lines.append("")
            lines.append("*Guidance: %s*" % g)
        if ms["totals"]["printed"] is not None:
            lines.append("")
            lines.append("**Total for Question %d: %d marks**"
                         % (atom["number"], ms["totals"]["printed"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
