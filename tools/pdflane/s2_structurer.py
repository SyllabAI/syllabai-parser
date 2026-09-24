"""S2 agent-structuring harness (FAILSAFE_PLAN §3 Stage 2 — Phase 2).

The agent (LLM) acts as the STRUCTURING layer over the deterministic base:
it assigns marks, groups alternative rows, pools "any N for 1 each" groups,
splits questions in layout variants — but it NEVER authors content. Every
emitted row is grounded to numbered lines of the pdftotext -layout base
layer, every line of every question slice must be claimed (no silent loss),
row-initial mark labels must map bijectively onto structured rows, and
per-label marks must close against the printed total.

Invariants (deterministic checks in validate):
  I1 grounding    — every emitted token (len>=2) exists in the union of the
                    cited lines' tokens (no invention)
  I2 coverage     — every slice line claimed by exactly one question
                    (column interleaving may multi-claim within a question)
  I3 label bijection — every row-initial [MA]<n> instance in the slice
                    (incl. bare-label + digit-completion) maps to exactly
                    one structured point row with the same label
  I4 arithmetic   — sum(marks) - sum(pool_size - pool_cap) == printed total
                    (ms-printed | qp-printed); source discrepancies must be
                    declared and become warnings + review flags, never silent
  I5 consistency  — totalRow vs printed total row; pool labels exist

Agent run file schema:
  {"slug": ..., "questions": [{
      "number": 3, "totalRow": 11, "totalRowSource": "ms-printed",
      "pools": [{"labels": ["M1","M2"], "cap": 1,
                 "reason": "either condition scores the single mark"}],
      "discrepancy": {"agentSum": 13, "msTotalRow": 11, "qpPrinted": 13,
                      "reason": "MS total row prints 11; grid prints 13x1"},
      "points": [{"label": "M1", "part": "a", "sub": "i", "marks": 1,
                  "lines": [42], "text": "(hydrated) iron(III) oxide / Fe2O3",
                  "notes": [{"text": "Allow ...", "lines": [42,43]}],
                  "alternatives": [{"text": "...", "lines": [112]}]}],
      "guidance": [{"text": "M2 dependent on M1", "lines": [136]}],
      "residual": [{"text": "Answer Notes Marks", "lines": [128],
                    "class": "furniture"}],
      "slices": {"start": 40, "end": 52}}]}
"""
import argparse
import hashlib
import json
import os
import re
import sys

from pdflane import parse_ms

LABEL_TOKEN_RE = re.compile(r"\b[MA]\d{1,2}\b")


# ----------------------------------------------------------------- helpers
def norm(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return [t for t in norm(s).split() if len(t) >= 2]


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_cleaned_lines(ms_pages):
    lines = []
    for p in ms_pages:
        for raw in p["text"].splitlines():
            ln = parse_ms.clean_line(raw)
            if ln is not None and ln.strip():
                lines.append({"n": len(lines) + 1, "page": p["page"],
                              "text": ln.strip()})
    return lines


def row_initial_instances(lines, lo, hi):
    """Row-initial label instances in [lo,hi]: full [MA]<n> at row start, or
    bare [MA] completed by digits on the next line (parse_ms rule)."""
    insts = []
    sub = [l for l in lines if lo <= l["n"] <= hi]
    for i, l in enumerate(sub):
        st = l["text"]
        if parse_ms.TOTAL_RE.match(st):
            continue
        lm = parse_ms.LABEL_RE.match(st)
        if not (lm and lm.group("labelbase")):
            continue
        q = lm.group("qn")
        if q is not None and q.isdigit() and int(q) > parse_ms.MAX_QN:
            continue  # answer value like "28", not a question number
        if lm.group("labelnum"):
            insts.append({"label": lm.group("labelbase") + lm.group("labelnum"),
                          "line": l["n"]})
            continue
        rest = lm.group("rest") or ""
        if rest and not rest[0].isspace():
            continue  # mid-word match (e.g. "Answer" -> A + "nswer")
        # bare label: completion on the next line
        if i + 1 < len(sub):
            dm = re.match(r"^(\d{1,2})(\s{2,}.*)?$", sub[i + 1]["text"])
            if dm and not LABEL_TOKEN_RE.search(sub[i + 1]["text"]):
                insts.append({"label": lm.group("labelbase") + dm.group(1),
                              "line": l["n"]})
    return insts


def deterministic_slices(lines):
    """Question slices: open on a qn-labelled row, close on a Total row.
    Bare-label rows with qn open questions (parse_ms semantics); a pending
    bare label makes the next digit line a completion, never an opener."""
    slices, cur, start = {}, None, None
    leftover = []
    pending_bare = False
    for l in lines:
        st = l["text"]
        m = parse_ms.TOTAL_RE.match(st)
        if m:
            if cur is not None:
                slices[cur] = {"start": start, "end": l["n"]}
            else:
                leftover.append(l["n"])
            cur = None
            pending_bare = False
            continue
        lm = parse_ms.LABEL_RE.match(st)
        opener = None
        if lm and lm.group("labelbase"):
            q = lm.group("qn")
            is_bare = lm.group("labelnum") == ""
            if pending_bare and re.match(r"^\d{1,2}(\s{2,}.*)?$", st) \
                    and not LABEL_TOKEN_RE.search(st):
                pending_bare = False
                continue
            pending_bare = is_bare or st.rstrip().endswith(("M", "A"))
            if q is not None and q.isdigit() and 1 <= int(q) <= parse_ms.MAX_QN:
                opener = int(q)
        else:
            pending_bare = False
        if opener is not None:
            if cur is None:
                cur, start = opener, l["n"]
            elif opener != cur:
                slices[cur] = {"start": start, "end": l["n"] - 1}
                cur, start = opener, l["n"]
        elif cur is None and st:
            leftover.append(l["n"])
    if cur is not None:
        slices[cur] = {"start": start, "end": lines[-1]["n"]}
    return slices, leftover


# ------------------------------------------------------------- emit-units
def cmd_emit_units(args):
    with open(args.ms_pages, encoding="utf-8") as f:
        ms_pages = json.load(f)
    lines = load_cleaned_lines(ms_pages)
    raw_labels = parse_ms.raw_label_count(ms_pages)
    mode = "whole" if args.mode == "whole" else "slices"
    if mode == "slices":
        slices, leftover = deterministic_slices(lines)
        for qn, s in slices.items():
            s["label_instances"] = len(row_initial_instances(lines, s["start"], s["end"]))
    else:
        slices, leftover = {}, [l["n"] for l in lines]
    units = {"slug": args.slug, "mode": mode,
             "total_line_labels": raw_labels, "lines": lines,
             "slices": slices, "slice_leftover_lines": leftover}
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, "units-%s.json" % args.slug)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(units, f, indent=1, ensure_ascii=False)
    txt = os.path.join(args.out, "lines-%s.txt" % args.slug)
    with open(txt, "w", encoding="utf-8") as f:
        for l in lines:
            f.write("%4d | p%02d | %s\n" % (l["n"], l["page"], l["text"]))
    print(json.dumps({"units": out, "lines": len(lines), "mode": mode,
                      "slices": {k: {kk: vv for kk, vv in v.items()}
                                 for k, v in slices.items()},
                      "leftover_n": len(leftover)}))
    return 0


# ---------------------------------------------------------------- validate
def find_line(lines, n):
    for l in lines:
        if l["n"] == n:
            return l
    return None


def grounded(text, line_refs, lines):
    """I1: every emitted token (len>=2) must exist in the union of cited
    lines' tokens; at least one cited line; cited lines must exist."""
    if not norm(text):
        return True, None
    if not line_refs:
        return False, "no lines cited"
    union = set()
    for n in line_refs:
        l = find_line(lines, n)
        if l is None:
            return False, "line %d does not exist" % n
        union |= set(tokens(l["text"]))
    tk = set(tokens(text))
    missing = tk - union
    if missing:
        return False, "tokens not on cited lines: %s" % sorted(missing)[:6]
    return True, None


def effective_sum(q):
    s = sum(p["marks"] for p in q.get("points", [])
            if p.get("marks") is not None)
    for pool in q.get("pools", []):
        n_members = len(pool.get("labels", [])) + len(pool.get("ids", []))
        s -= max(0, n_members - pool["cap"])
    return s


def cmd_validate(args):
    with open(args.units, encoding="utf-8") as f:
        units = json.load(f)
    lines = units["lines"]
    with open(args.run, encoding="utf-8") as f:
        run = json.load(f)
    qptotals = {}
    if args.qp_totals and os.path.exists(args.qp_totals):
        with open(args.qp_totals, encoding="utf-8") as f:
            qptotals = {int(k): v for k, v in json.load(f).items()}
    problems, warnings, review = [], [], []
    covered = {}
    qs = run.get("questions", [])

    for q in qs:
        qn = q["number"]
        if q.get("slices"):
            lo, hi = q["slices"]["start"], q["slices"]["end"]
        elif units["mode"] == "slices" and str(qn) in units["slices"]:
            s = units["slices"][str(qn)]
            lo, hi = s["start"], s["end"]
        else:
            problems.append("q%s: no slice (mode %s)" % (qn, units["mode"]))
            continue

        # I3 bijection: instances vs point rows
        insts = row_initial_instances(lines, lo, hi)
        by_label = {}
        for it in insts:
            by_label.setdefault(it["label"], []).append(it["line"])
        point_cited = set()
        for pt in q.get("points", []):
            point_cited |= set(pt.get("lines", []))
        seen = set()
        for pt in q.get("points", []):
            lab = pt.get("label") or ""
            if lab and not re.fullmatch(r"[MA]\d{1,2}", lab):
                problems.append("q%d: bad label %r" % (qn, lab))
                continue
            # labels restart per part in real mark schemes; uniqueness key is
            # (part, sub, label); marks-implicit points carry no label
            key = (pt.get("part"), pt.get("sub"), lab)
            if lab and key in seen:
                problems.append("q%d: duplicate point %s (merge via alternatives)" % (qn, key,))
            seen.add(key)
            if not pt.get("lines"):
                problems.append("q%d: %s cites no lines" % (qn, lab))
            for n in pt.get("lines", []):
                if n in covered and covered[n] != qn:
                    problems.append("I2 line %d claimed by q%d and q%d" % (n, covered[n], qn))
                covered[n] = qn
            # I3: consume one same-label instance whose line the point cites
            if lab:
                cands = [l for l in by_label.get(lab, []) if l in set(pt.get("lines", []))]
                if not cands:
                    problems.append("I3 q%d: %s %s cites none of its row-initial instances %s"
                                    % (qn, pt.get("part"), lab, by_label.get(lab, [])))
                else:
                    by_label[lab].remove(cands[0])
                    if not by_label[lab]:
                        del by_label[lab]
            ok, why = grounded(pt.get("text", ""), pt.get("lines", []), lines)
            if not ok:
                problems.append("I1 q%d %s text: %s" % (qn, lab, why))
            for nt in pt.get("notes", []):
                ok, why = grounded(nt.get("text", ""), nt.get("lines", []), lines)
                if not ok:
                    problems.append("I1 q%d %s note %r: %s" % (qn, lab, nt.get("text", "")[:40], why))
                for n in nt.get("lines", []):
                    if n in covered and covered[n] != qn:
                        problems.append("I2 line %d claimed by q%d and q%d" % (n, covered[n], qn))
                    covered[n] = qn
                    for lab2 in [k for k, v in by_label.items() if n in v]:
                        # wrapped guidance fragment line (e.g. "M2 can score"):
                        # consume only if the note's own text carries the label
                        # token — never steal a later point's row label
                        if lab2.lower() not in tokens(nt.get("text", "")):
                            continue
                        if n in point_cited:
                            continue
                        by_label[lab2].remove(n)
                        if not by_label[lab2]:
                            del by_label[lab2]
            for alt in pt.get("alternatives", []):
                ok, why = grounded(alt.get("text", ""), alt.get("lines", []), lines)
                if not ok:
                    problems.append("I1 q%d %s alt %r: %s" % (qn, lab, alt.get("text", "")[:40], why))
                for n in alt.get("lines", []):
                    if n in covered and covered[n] != qn:
                        problems.append("I2 line %d claimed by q%d and q%d" % (n, covered[n], qn))
                    covered[n] = qn
                    for lab2 in [k for k, v in by_label.items() if n in v]:
                        # alternative rows carry the same mark label
                        by_label[lab2].remove(n)
                        if not by_label[lab2]:
                            del by_label[lab2]
            if pt.get("marks") is None:
                problems.append("q%d: %s marks unresolved" % (qn, lab))
        # guidance + residual (rows may legitimately open with a label,
        # e.g. "M2 dependent on M1" — such rows consume the instance)
        for row in list(q.get("guidance", [])) + list(q.get("residual", [])):
            for n in row.get("lines", []):
                for lab in [k for k, v in by_label.items() if n in v]:
                    if lab.lower() not in tokens(row.get("text", "")):
                        continue
                    by_label[lab].remove(n)
                    if not by_label[lab]:
                        del by_label[lab]
            ok, why = grounded(row.get("text", ""), row.get("lines", []), lines)
            if not ok:
                problems.append("I1 q%d row %r: %s" % (qn, row.get("text", "")[:40], why))
            for n in row.get("lines", []):
                if n in covered and covered[n] != qn:
                    problems.append("I2 line %d claimed by q%d and q%d" % (n, covered[n], qn))
                covered[n] = qn
        for lab, ls in by_label.items():
            problems.append("I3 q%d: instance(s) %s at lines %s unmatched by any row"
                            % (qn, lab, ls))
        # pools consistency (labels or synthetic point ids)
        labels = {p["label"] for p in q.get("points", []) if p.get("label")}
        pids = {p.get("id") for p in q.get("points", []) if p.get("id")}
        for pool in q.get("pools", []):
            unknown = [x for x in pool.get("labels", []) if x not in labels]
            unknown += [x for x in pool.get("ids", []) if x not in pids]
            if unknown:
                problems.append("I5 q%d pool members not points: %s" % (qn, unknown))
            if not pool.get("labels") and not pool.get("ids"):
                problems.append("I5 q%d empty pool" % qn)
        # I4 arithmetic
        src = q.get("totalRowSource", "ms-printed")
        total = q.get("totalRow")
        es = effective_sum(q)
        # printed total row inside slice (ms-printed cross-check)
        printed_total = None
        total_variant_re = re.compile(r"^Total\s+(\d{1,3})\s*$", re.I)
        for l in lines:
            if lo <= l["n"] <= hi:
                m = parse_ms.TOTAL_RE.match(l["text"]) or total_variant_re.match(l["text"])
                if m:
                    printed_total = int(m.group(1))
        if src == "ms-printed":
            if printed_total is not None and total is not None and total != printed_total:
                problems.append("I5 q%d totalRow %s != printed total row %s"
                                % (qn, total, printed_total))
            if printed_total is None:
                problems.append("q%d: totalRowSource ms-printed but no total row in slice" % qn)
        disc = q.get("discrepancy")
        if es != total:
            if disc and disc.get("agentSum") == es:
                review.append({"code": "PRINTED-MS-TOTAL-ROW-DISCREPANCY",
                               "taxonomy": "SOURCE-DISCREPANCY", "question": qn,
                               "detail": disc})
                warnings.append({"code": "PRINTED-MS-TOTAL-ROW-DISCREPANCY", "q": qn,
                                 "agentSum": es, "msTotalRow": total,
                                 "qpPrinted": disc.get("qpPrinted")})
            else:
                problems.append("I4 q%d: effective sum %d != totalRow %s" % (qn, es, total))
        elif src == "qp-printed" and qn in qptotals and total != qptotals[qn]:
            warnings.append({"code": "TOTALROW-VS-QP", "q": qn,
                             "agent": total, "qp": qptotals[qn]})
        # I2 unclaimed (total rows are auto-claimed structural closures)
        for l in lines:
            if lo <= l["n"] <= hi and l["n"] not in covered:
                if parse_ms.TOTAL_RE.match(l["text"]) or \
                        re.match(r"^Total\s+(\d{1,3})\s*$", l["text"], re.I):
                    covered[l["n"]] = "total-row"
                    continue
                problems.append("I2 q%d line %d unclaimed: %r" % (qn, l["n"], l["text"][:60]))

    # slice overlap (multi-question runs)
    spans = []
    for q in qs:
        if q.get("slices"):
            spans.append((q["number"], q["slices"]["start"], q["slices"]["end"]))
        elif units["mode"] == "slices" and str(q["number"]) in units["slices"]:
            s = units["slices"][str(q["number"])]
            spans.append((q["number"], s["start"], s["end"]))
    spans.sort(key=lambda x: x[1])
    for (qa, _, ea), (qb, sb, _) in zip(spans, spans[1:]):
        if ea >= sb:
            problems.append("I2 slices overlap: q%d ends %d, q%d starts %d" % (qa, ea, qb, sb))
    if units["mode"] == "slices":
        for n in units.get("slice_leftover_lines", []):
            if n not in covered:
                l = find_line(lines, n)
                warnings.append({"code": "LEFTOVER-LINE", "line": n,
                                 "text": l["text"][:60] if l else "?"})
    # run-level residual (front matter, end matter, page furniture outside
    # every question)
    for r in run.get("residual", []):
        if not r.get("verify", True):
            pass  # bulk furniture classification: claim only, no token check
        else:
            ok, why = grounded(r.get("text", ""), r.get("lines", []), lines)
            if not ok:
                problems.append("I1 run-residual %r: %s" % (r.get("text", "")[:40], why))
        for n in r.get("lines", []):
            if n in covered:
                problems.append("I2 line %d claimed by q%s and run-residual" % (n, covered[n]))
            covered[n] = -1
    else:
        for l in lines:
            if l["n"] not in covered:
                problems.append("I2 whole-file line %d unclaimed: %r" % (l["n"], l["text"][:60]))
    rep = {"run": os.path.basename(args.run), "problems": problems,
           "warnings": warnings, "review": review, "ok": not problems,
           "questions": len(qs)}
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    print(json.dumps({"ok": rep["ok"], "problems": len(problems),
                      "warnings": len(warnings), "review": len(review),
                      "report": args.report}))
    return 0 if rep["ok"] else 2


# ----------------------------------------------------------------- compare
def canon(q):
    def pts(ps):
        return sorted(({"label": p.get("label") or "", "id": p.get("id"), "marks": p.get("marks"),
                        "text": norm(p.get("text", "")),
                        "notes": sorted(norm(n.get("text", "")) for n in p.get("notes", [])),
                        "alts": sorted(norm(a.get("text", "")) for a in p.get("alternatives", []))}
                       for p in ps), key=lambda x: x["label"])
    d = q.get("discrepancy") or {}
    return {"number": q["number"], "totalRow": q.get("totalRow"),
            "points": pts(q.get("points", [])),
            "guidance": sorted(norm(g.get("text", "")) for g in q.get("guidance", [])),
            "pools": sorted(([sorted(p["labels"]), p["cap"]] for p in q.get("pools", []))),
            "disc": (d.get("agentSum"), d.get("msTotalRow"), d.get("qpPrinted")) if d else None}


def cmd_compare(args):
    runs = []
    for r in args.runs:
        with open(r, encoding="utf-8") as f:
            runs.append(json.load(f))
    cans = [{"questions": [canon(q) for q in sorted(run["questions"],
                                                     key=lambda x: x["number"])]}
            for run in runs]
    identical = all(c == cans[0] for c in cans[1:])
    diffs = []
    if not identical:
        for i, c in enumerate(cans[1:], 2):
            bq = {q["number"]: q for q in cans[0]["questions"]}
            for q in c["questions"]:
                if bq.get(q["number"]) != q:
                    diffs.append({"run": i, "question": q["number"]})
    verdict = {"k": len(runs), "identical": identical, "stable": identical,
               "diffs": diffs[:20], "runs": args.runs}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=1)
    print(json.dumps({"identical": identical, "diffs": len(diffs), "out": args.out}))
    return 0 if identical else 3


# ------------------------------------------------------------------- freeze
def cmd_freeze(args):
    with open(args.units, encoding="utf-8") as f:
        units = json.load(f)
    lines = {l["n"]: l for l in units["lines"]}
    with open(args.run, encoding="utf-8") as f:
        run = json.load(f)
    with open(args.validation, encoding="utf-8") as f:
        val = json.load(f)
    with open(args.kverdict, encoding="utf-8") as f:
        kv = json.load(f)
    if not val["ok"]:
        print(json.dumps({"error": "refusing freeze: validation problems present"}))
        return 2
    if not kv.get("stable"):
        print(json.dumps({"error": "refusing freeze: k-run comparison not stable"}))
        return 2
    tree = args.tree
    qdir = os.path.join(tree, "questions")
    paper_path = os.path.join(tree, "paper.json")
    with open(paper_path, encoding="utf-8") as f:
        paper = json.load(f)
    qptotals = {}
    if args.qp_totals and os.path.exists(args.qp_totals):
        with open(args.qp_totals, encoding="utf-8") as f:
            qptotals = {int(k): v for k, v in json.load(f).items()}
    touched = []
    for q in run["questions"]:
        qn = q["number"]
        path = os.path.join(qdir, "q%02d.json" % qn)
        created = not os.path.exists(path)
        es = effective_sum(q)
        strict_arith = (es == q.get("totalRow")) if q.get("totalRow") is not None else False
        if created:
            atom = {"atomId": "%s-q%02d" % (paper["paper"]["slug"], qn),
                    "paper": paper["paper"], "number": qn,
                    "marks": {"total": qptotals.get(qn), "msTotalRow": q.get("totalRow"),
                              "arithmeticVerified": strict_arith, "agentSum": es},
                    "prompt": {"text": "", "pages": [], "provenance": "pdf-parsed"},
                    "commandWord": None, "figures": [],
                    "confidence": "MEDIUM", "flags": ["S2-ATOM-CREATED"],
                    "provenance": {"lane": "pdflane-v%s" % __import__("pdflane").__version__,
                                   "engines": ["pdftotext-layout"]}}
        else:
            with open(path, encoding="utf-8") as f:
                atom = json.load(f)
            atom["marks"]["msTotalRow"] = q.get("totalRow")
            atom["marks"]["arithmeticVerified"] = strict_arith
            atom["marks"]["agentSum"] = es
            atom["flags"] = [f for f in atom.get("flags", [])
                             if f not in ("MS-QUESTION-MISSING",)]
        pages = sorted({lines[n]["page"] for p in q.get("points", [])
                        for n in p.get("lines", []) if n in lines})
        atom["markScheme"] = {
            "points": [{"label": p.get("label"), "id": p.get("id"), "part": p.get("part"),
                        "sub": p.get("sub"), "marks": p.get("marks"),
                        "text": p.get("text", ""),
                        "notes": [n.get("text", "") for n in p.get("notes", [])],
                        "alternatives": [a.get("text", "") for a in p.get("alternatives", [])],
                        "pages": sorted({lines[n]["page"] for n in p.get("lines", []) if n in lines})}
                       for p in q.get("points", [])],
            "pools": [{"labels": p.get("labels", []), "ids": p.get("ids", []),
                       "cap": p["cap"],
                       "marksContributed": p["cap"],
                       "reason": p.get("reason", "")} for p in q.get("pools", [])],
            "totalRow": q.get("totalRow"),
            "totalRowSource": q.get("totalRowSource", "ms-printed"),
            "discrepancy": q.get("discrepancy"),
            "guidance": [g.get("text", "") for g in q.get("guidance", [])],
            "pages": pages,
            "reconciled": True,
            "provenance": "llm-structured",
            "structuredBy": "agent-s2",
            "grounding": "pdftotext-layout-numbered-lines",
            "validation": {"run": val["run"], "k": kv["k"], "k_run_identical": kv["identical"]},
        }
        if qn in qptotals and atom["marks"].get("total") is None:
            atom["marks"]["total"] = qptotals[qn]
        atom.setdefault("provenance", {})
        atom["provenance"]["classes"] = ["pdf-parsed", "llm-structured"]
        if q.get("discrepancy"):
            atom["flags"] = sorted(set(atom.get("flags", []) +
                                       ["PRINTED-MS-TOTAL-ROW-DISCREPANCY"]))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(atom, f, indent=1, ensure_ascii=False)
        # generated md sidecar (canonical is questions/q%02d.json)
        md = ["# Question %d — %s" % (qn, paper["paper"].get("slug", "")), "",
              "**Total: %s marks** (%s)" % (q.get("totalRow"),
                                            q.get("totalRowSource", "ms-printed")), "",
              "## Mark scheme", ""]
        for p in atom["markScheme"]["points"]:
            lab = p["label"] or "\u2014"
            md.append("- **%s** (%s mark%s) %s" % (lab, p["marks"],
                                                   "" if p["marks"] == 1 else "s",
                                                   p["text"]))
            for a in p["alternatives"]:
                md.append("  - *or* %s" % a)
            for n in p["notes"]:
                md.append("  - note: %s" % n)
        for pool in atom["markScheme"]["pools"]:
            members = "/".join(pool["labels"] + pool["ids"])
            md.append("- pool %s: any %d for 1 each (%s)" %
                      (members, pool["cap"], pool["reason"]))
        if atom["markScheme"]["guidance"]:
            md += ["", "### Guidance"] + ["- " + g for g in atom["markScheme"]["guidance"]]
        if atom["markScheme"]["discrepancy"]:
            md += ["", "> SOURCE DISCREPANCY: %s" %
                   json.dumps(atom["markScheme"]["discrepancy"])]
        md += ["", "*Generated view; canonical: questions/q%02d.json; provenance: "
                   "pdf-parsed + llm-structured (grounded, k-run stable)*" % qn]
        with open(os.path.join(qdir, "q%02d.md" % qn), "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
        touched.append({"q": qn, "created": created})
    # paper.json v2 — G1 arithmetic verdict distinguishes strict closure from
    # recorded source discrepancies (flags, never silent)
    arith_bad, src_disc = [], []
    for q in run["questions"]:
        es = effective_sum(q)
        if es != q.get("totalRow"):
            d = q.get("discrepancy") or {}
            if d.get("agentSum") == es:
                src_disc.append({"question": q["number"], "agentSum": es,
                                 "msTotalRow": q.get("totalRow"),
                                 "qpPrinted": d.get("qpPrinted"),
                                 "reason": d.get("reason")})
            else:
                arith_bad.append(q["number"])
    paper["s2"] = {
        "stage": "agent-structuring",
        "accepted_run": val["run"],
        "k_run": {"k": kv["k"], "identical": kv["identical"], "stable": kv["stable"]},
        "validation": {"ok": val["ok"], "problems": val["problems"],
                       "warnings": val["warnings"], "review": val.get("review", [])},
        "g1_ms_point_arithmetic": {
            "ok": not arith_bad,
            "strict_verified": [q["number"] for q in run["questions"]
                                if q["number"] not in arith_bad and
                                effective_sum(q) == q.get("totalRow")],
            "source_discrepancy": src_disc,
            "unresolved": arith_bad},
        "questions_structured": sorted(q["number"] for q in run["questions"]),
        "provenance_classes": ["pdf-parsed", "llm-structured"],
        "model": args.model,
        "anti_role": "agent never transcribes born-digital text; every row grounded to "
                     "numbered layout lines; line coverage + label bijection enforced",
    }
    if run.get("pairingDefect"):
        paper["pairingDefect"] = run["pairingDefect"]
        paper.setdefault("escalations", []).append({
            "unit": "PAPER", "code": "QP-MS-PAIRING-DEFECT",
            "taxonomy": "SOURCE-DISCREPANCY",
            "detail": run["pairingDefect"]})
    paper["provenance"]["provenance_classes"] = sorted(
        set(paper.get("provenance", {}).get("provenance_classes", []) + ["llm-structured"]))
    with open(paper_path, "w", encoding="utf-8") as f:
        json.dump(paper, f, indent=1, ensure_ascii=False)
    s2meta = os.path.join(tree, "_meta", "s2")
    os.makedirs(s2meta, exist_ok=True)
    sums = []
    for fn in sorted(os.listdir(qdir)):
        h = sha256_text(open(os.path.join(qdir, fn), encoding="utf-8").read())
        sums.append("%s  %s" % (h, fn))
    with open(os.path.join(s2meta, "SHA256SUMS"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    for src, dst in ((args.run, "accepted-run.json"), (args.validation, "validation.json"),
                     (args.kverdict, "k-verdict.json"), (args.units, "units.json")):
        with open(src, encoding="utf-8") as f:
            c = f.read()
        with open(os.path.join(s2meta, dst), "w", encoding="utf-8") as f:
            f.write(c)
    print(json.dumps({"frozen": True, "touched": touched,
                      "g1_arithmetic_ok": not arith_bad,
                      "sha_file": os.path.join(s2meta, "SHA256SUMS")}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit-units")
    e.add_argument("--ms-pages", required=True)
    e.add_argument("--slug", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--mode", default="slices", choices=["slices", "whole"])
    v = sub.add_parser("validate")
    v.add_argument("--units", required=True)
    v.add_argument("--run", required=True)
    v.add_argument("--report", required=True)
    v.add_argument("--qp-totals", default="")
    c = sub.add_parser("compare")
    c.add_argument("--runs", nargs="+", required=True)
    c.add_argument("--out", required=True)
    fz = sub.add_parser("freeze")
    fz.add_argument("--tree", required=True)
    fz.add_argument("--units", required=True)
    fz.add_argument("--run", required=True)
    fz.add_argument("--validation", required=True)
    fz.add_argument("--kverdict", required=True)
    fz.add_argument("--qp-totals", default="")
    fz.add_argument("--model", default="agent:glm-main")
    args = ap.parse_args()
    sys.exit({"emit-units": cmd_emit_units, "validate": cmd_validate,
              "compare": cmd_compare, "freeze": cmd_freeze}[args.cmd](args))


if __name__ == "__main__":
    main()
