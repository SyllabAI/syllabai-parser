"""Stage 0 intake: filename grammar, QP/MS pairing, sha256 freeze, census.

Normalizes messy raw-archive filenames like
  "June 2020 QP.pdf"
  "January 2021 (R) MS.pdf"
  "January 2013 MS - Paper 2C Edexcel Chemistry IGCSE.pdf"
into (qualification, board, subject, paper-code, session, variant) records,
pairs QP<->MS, and can copy pairs into the syllabai-pastpapers layout:

  <dest>/<QUAL>/<BOARD>/<SUBJECT>/<paper-slug>/<session>/QP.pdf + MS.pdf

Unparsable/unpairable files go to a quarantine report with reason codes —
never silently dropped (failsafe invariant 1).
"""
import argparse
import hashlib
import json
import os
import re
import shutil

FILENAME_RE = re.compile(
    r"^(?P<month>January|June|November|October|March|May|Specimen|Summer|Winter)\s+"
    r"(?:(?P<year>\d{4})\s+)?"
    r"(?P<tags>(?:(?:\([^)]{1,14}\))\s*)*)"
    r"(?:(?:-\s*)?(?P<predesc>(?:Unit|Paper)\s+\S+)\s+)?"
    r"(?P<kind>QP|MS|IN)"
    r"(?:_(?P<papervar>\d))?(?:_(?P<papervar2>\d))?"
    r"(?:\s+-\s*(?P<desc>.+?))?\.pdf$",
    re.I,
)

DESC_PAPER_RE = re.compile(r"(?:Paper|Unit)\s+([0-9][A-Z]?)", re.I)
FOLDER_PAPER_RE = re.compile(r"^(?:Paper|Unit)\s+(\d)", re.I)
QUALS = {"IGCSE", "IAL", "GCE", "GCSE"}

MONTH_ABBR = {"January": "Jan", "June": "Jun", "November": "Nov", "October": "Oct",
              "March": "Mar", "May": "May", "Specimen": "Spec", "Summer": "Jun",
              "Winter": "Nov"}


def parse_filename(name):
    m = FILENAME_RE.match(name)
    if not m:
        return None
    month = m.group("month").title()
    tags = (m.group("tags") or "").upper()
    variant = "R" if "(R)" in tags else ""
    kind = m.group("kind").upper()
    desc = m.group("predesc") or m.group("desc") or ""
    code = None
    dm = DESC_PAPER_RE.search(desc)
    if dm:
        code = dm.group(1).upper()
    year = m.group("year")
    if year:
        session = "%s-%s" % (year, MONTH_ABBR[month])
    else:
        session = MONTH_ABBR[month]  # e.g. year-less Specimen
    if variant == "R":
        session += "-R"
    pvar = m.group("papervar") or ""
    if m.group("papervar2"):
        pvar += "_" + m.group("papervar2")
    return {"month": month, "year": year, "variant": variant,
            "kind": kind, "paper_code": code, "papervar": pvar,
            "session": session}


def path_context(rel_parts):
    """Derive (qual, board, subject, folder_paper, unit_folder) from the path."""
    qual = board = subject = None
    folder_paper = None
    unit_folder = None
    for i, p in enumerate(rel_parts):
        up = p.upper()
        if up in QUALS:
            qual = up
            rest = rel_parts[i + 1:]
            if rest:
                board = rest[0]
            if len(rest) > 1:
                subject = rest[1]
            if len(rest) > 2:
                unit_folder = rest[2]
            break
    for p in rel_parts:
        fm = FOLDER_PAPER_RE.match(p)
        if fm:
            folder_paper = fm.group(1)
    return qual, board, subject, folder_paper, unit_folder


def paper_slug(r):
    """Resolve the paper identifier for pairing:
    desc-code > folder(U#) > unit folder name > '?'."""
    base = (r.get("paper_code") or
            ("U" + r["folder_paper"] if r.get("folder_paper") else None) or
            (re.sub(r"[^A-Za-z0-9]", "", r["unit_folder"] or "").lower() or None) or
            "?")
    if r.get("papervar"):
        base += "v" + r["papervar"]
    return base


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root):
    """Return (records, quarantine). Records carry full provenance."""
    records, quarantine = [], []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(".pdf"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            parts = rel.split(os.sep)
            pf = parse_filename(fn)
            qual, board, subject, folder_paper, unit_folder = path_context(parts)
            if pf is None:
                quarantine.append({"file": rel, "reason": "UNPARSED_FILENAME"})
                continue
            if qual is None or subject is None:
                quarantine.append({"file": rel, "reason": "MISSING_PATH_CONTEXT",
                                   "context": {"qual": qual, "subject": subject}})
                continue
            pf["file"] = rel
            pf["qual"] = qual
            pf["board"] = board or ""
            pf["subject"] = subject
            pf["folder_paper"] = folder_paper
            pf["unit_folder"] = unit_folder
            records.append(pf)
    return records, quarantine


def pair_key(r):
    return (r["qual"], r["board"], r["subject"], paper_slug(r), r["session"])


def pair(records):
    pairs, unpaired, inserts = {}, [], []
    by_key, dup_copies = {}, 0
    for r in records:
        if r["kind"] == "IN":  # inserts (resource booklets) are recorded, not paired
            inserts.append(r)
            continue
        by_key.setdefault(pair_key(r), []).append(r)
    for k, rs in by_key.items():
        # byte-level dedupe: the archive holds duplicate copies under variant
        # tags like (IAL) vs untagged; identical bytes are one logical document
        qp = dedupe([r for r in rs if r["kind"] == "QP"])
        ms = dedupe([r for r in rs if r["kind"] == "MS"])
        dup_copies += (len([r for r in rs if r["kind"] == "QP"]) - len(qp))
        dup_copies += (len([r for r in rs if r["kind"] == "MS"]) - len(ms))
        if len(qp) == 1 and len(ms) == 1:
            pairs[k] = {"QP": qp[0], "MS": ms[0]}
        else:
            reason = "UNPAIRED_%s"
            if len(qp) > 1 or len(ms) > 1:
                reason = "DUAL_COPY_CONFLICT_%s"
            for r in qp + ms:
                unpaired.append({"file": r["file"],
                                 "reason": reason % r["kind"],
                                 "key": "|".join(str(x) for x in k)})
    return pairs, unpaired, inserts, dup_copies


def dedupe(rs):
    """Drop byte-identical duplicates; keep first by filename."""
    seen, out = set(), []
    for r in sorted(rs, key=lambda x: x["file"]):
        h = sha256(r["_abs"])
        if h in seen:
            continue
        seen.add(h)
        out.append(r)
    return out


def slug_for(key):
    qual, board, subject, paper, session = key
    pslug = paper if paper != "?" else "unknown"
    pslug = re.sub(r"[^A-Za-z0-9._-]", "", pslug.lower()) or "unknown"
    sslug = re.sub(r"[^A-Za-z0-9._-]", "", session.lower())
    return "/".join([qual, (board or "unknown").lower(), re.sub(r"[^A-Za-z0-9._-]", "", subject.lower()), pslug, sslug])


def normalize(pairs, dest, limit=None):
    """Copy pairs into the normalized layout. Returns intake.json records."""
    out = []
    for i, (key, p) in enumerate(sorted(pairs.items())):
        if limit is not None and i >= limit:
            break
        base = os.path.join(dest, slug_for(key))
        os.makedirs(base, exist_ok=True)
        rec = {"key": "|".join(str(x) for x in key), "dest": base, "files": {}}
        for kind in ("QP", "MS"):
            dstp = os.path.join(base, kind + ".pdf")
            shutil.copyfile(p[kind]["_abs"], dstp)
            rec["files"][kind] = {"from": p[kind]["file"], "sha256": sha256(dstp)}
        with open(os.path.join(base, "intake.json"), "w") as f:
            json.dump(rec, f, indent=1)
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser(description="pdflane intake census/normalizer")
    ap.add_argument("--root", required=True, help="raw archive root")
    ap.add_argument("--dest", help="optional: copy paired QP/MS into this normalized tree")
    ap.add_argument("--limit", type=int, default=None, help="max pairs to normalize")
    ap.add_argument("--out", required=True, help="census output JSON")
    args = ap.parse_args()

    records, quarantine = scan(args.root)
    for r in records:
        r["_abs"] = os.path.join(args.root, r["file"])
    pairs, unpaired, inserts, dup_copies = pair(records)
    census = {
        "root": args.root,
        "total_pdfs": len(records) + len([q for q in quarantine if q["reason"] == "UNPARSED_FILENAME"]),
        "parsed_records": len(records),
        "pairs": len(pairs),
        "unpaired": len(unpaired),
        "inserts": len(inserts),
        "duplicate_copies_deduped": dup_copies,
        "quarantine": quarantine,
        "by_qual_subject": {},
        "unpaired_list": unpaired,
    }
    for k in pairs:
        slot = "%s/%s" % (k[0], k[2])
        census["by_qual_subject"][slot] = census["by_qual_subject"].get(slot, 0) + 1
    if args.dest:
        done = normalize(pairs, args.dest, args.limit)
        census["normalized"] = len(done)
    with open(args.out, "w") as f:
        json.dump(census, f, indent=1)
    print(json.dumps({k: v for k, v in census.items()
                      if k in ("total_pdfs", "parsed_records", "pairs", "unpaired",
                               "inserts", "duplicate_copies_deduped", "normalized")},
                     indent=1))
    print("quarantine=%d" % len(quarantine))


if __name__ == "__main__":
    main()
