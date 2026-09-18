"""Validate a syllabai.pastpaper.atoms/1.0 document (gates V1-V4).

V1 schema — jsonschema draft-07 validation against schema/atoms.schema.json.
V2 marks closure — per-atom point sums vs printed totals; part sums vs atom
   totals; envelope totalMarks vs sum of atom marks.
V3 label census — every MS point maps to a QP part; every part has >= 1 point
   (or a flag explains why); nothing silently dropped.
V4 assets — every image.src exists on disk; every asset file is referenced.

Exit code 0 = all green; 2 = any failure (deficits are printed, never swallowed).
"""
import json
import os
import re
import sys

from jsonschema import Draft7Validator

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema", "atoms.schema.json")


def validate_document(doc, assets_dir=None, strict_flags=False):
    failures = []

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    v = Draft7Validator(schema)
    for err in sorted(v.iter_errors(doc), key=lambda e: list(e.path)):
        failures.append("V1 schema: %s at %s" % (err.message, list(err.path)))

    if doc.get("schema") != "syllabai.pastpaper.atoms/1.0":
        failures.append("V1 schema: unexpected schema tag %r" % doc.get("schema"))

    total = 0
    numbers = []
    for atom in doc["questions"]:
        qn = atom["number"]
        numbers.append(qn)
        ms = atom["markScheme"]
        pools = ms.get("pools", [])

        def _pool_hit(p, pool):
            if p["id"] not in pool["labels"]:
                return False
            if not pool["part"]:
                return True
            m = re.match(r"^([a-z])(?:-([ivx]+))?$", pool["part"])
            if not m:
                return pool["part"][0:1] == (p["part"] or "")[0:1]
            if m.group(1) != (p["part"] or ""):
                return False
            return m.group(2) is None or p["sub"] == m.group(2)

        pt_sum = 0
        for p in ms["points"]:
            if not any(_pool_hit(p, pool) for pool in pools):
                pt_sum += p["marks"]
        pt_sum += sum(int(pool["cap"]) for pool in pools)
        printed = ms["totals"]["printed"]
        flagged_ok = {"PRINTED-TOTAL-DISCREPANCY-QP-VS-MS", "MS-POINTS-DONT-CLOSE",
                      "MS-QUESTION-MISSING"} & set(atom.get("flags", []))
        if printed is not None and printed != pt_sum and not flagged_ok:
            failures.append("V2 closure: q%d point sum %d != printed total %d"
                            % (qn, pt_sum, printed))
        if ms["totals"]["sum"] != pt_sum:
            failures.append("V2 closure: q%d recorded sum %d != recomputed %d"
                            % (qn, ms["totals"]["sum"], pt_sum))
        if printed is not None and atom["marks"] != printed \
                and not flagged_ok:
            failures.append("V2 closure: q%d atom marks %d != MS printed %d "
                            "(and no discrepancy flag)" % (qn, atom["marks"], printed))
        _lws = {p["label"] for p in atom["parts"] if p["sub"] is not None}
        part_sum = sum(p["marks"] for p in atom["parts"]
                       if not (p["sub"] is None and p["label"] in _lws))
        if atom["parts"] and part_sum != atom["marks"] \
                and "PART-MARKS-MISMATCH" not in atom.get("flags", []) \
                and ms["totals"]["verified"]:
            failures.append("V2 closure: q%d part sum %d != atom marks %d "
                            "(and no flag)" % (qn, part_sum, atom["marks"]))
        if not atom["parts"] and part_sum > 0:
            failures.append("V2 closure: q%d open/mcq atom carries part marks" % qn)
        total += atom["marks"]

        # V3 census (letter-level; MS may subdivide parts differently from the QP)
        atom_flags = set(atom.get("flags", []))
        part_letters = {p["label"] for p in atom["parts"]}
        for p in ms["points"]:
            if p["part"] is None:
                continue
            if part_letters and p["part"] not in part_letters \
                    and "MS-POINT-UNKNOWN-PART" not in atom_flags:
                failures.append("V3 census: q%d MS point %s targets unknown part "
                                "letter %r" % (qn, p["id"], p["part"]))
        if atom["parts"]:
            orphan_parts = [k for k in part_letters
                            if not any(p["part"] == k for p in ms["points"])]
            if orphan_parts and not (atom_flags & {"MS-PART-NO-POINTS",
                                                   "MS-QUESTION-MISSING"}):
                failures.append("V3 census: q%d parts without MS points: %s "
                                "(and no flag)" % (qn, orphan_parts))
        for flagname in atom.get("flags", []):
            if strict_flags:
                failures.append("V3 census: q%d carries flag %s (strict mode)"
                                % (qn, flagname))

    if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
        failures.append("V3 census: question numbers not unique/ordered: %s" % numbers)
    if doc["questionCount"] != len(doc["questions"]):
        failures.append("V2 closure: questionCount %d != %d atoms"
                        % (doc["questionCount"], len(doc["questions"])))
    if doc["totalMarks"] != total:
        failures.append("V2 closure: totalMarks %d != sum %d"
                        % (doc["totalMarks"], total))

    # V4 assets
    refs, asset_files = [], []
    def collect(blocks):
        for b in blocks:
            if b["type"] == "image":
                refs.append(b["src"])
    for atom in doc["questions"]:
        collect(atom["stem"])
        for p in atom["parts"]:
            collect(p["prompt"])
    if assets_dir is not None:
        asset_files = sorted(os.listdir(assets_dir)) if os.path.isdir(assets_dir) else []
        for r in refs:
            fn = r.split("/", 1)[1]
            if fn not in asset_files:
                failures.append("V4 assets: missing %s" % r)
        unreferenced = [f for f in asset_files if ("assets/" + f) not in refs]
        if unreferenced:
            failures.append("V4 assets: unreferenced files: %s" % unreferenced)

    return failures


def main():
    if len(sys.argv) < 2:
        print("usage: python3 -m pdflane.validate_atoms <questions.json> "
              "[--assets <dir>] [--strict-flags]")
        return 2
    path = sys.argv[1]
    assets_dir = None
    strict = "--strict-flags" in sys.argv
    if "--assets" in sys.argv:
        assets_dir = sys.argv[sys.argv.index("--assets") + 1]
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    failures = validate_document(doc, assets_dir, strict)
    if failures:
        for f in failures:
            print("FAIL", f)
        return 2
    print(json.dumps({
        "verdict": "PASS",
        "schema": doc["schema"],
        "questionCount": doc["questionCount"],
        "totalMarks": doc["totalMarks"],
        "marksVerified": doc["marksVerified"],
        "atoms_flagged": [q["number"] for q in doc["questions"] if q.get("flags")],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
