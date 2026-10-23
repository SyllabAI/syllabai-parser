#!/usr/bin/env python3
"""T-MIG-141 Phase-B real-write driver (FROZEN — deterministic, no LLM; spec §4.2).

The operator-gated act of record: in-place glyph normalization patch of
`document_chunks` over the wired exam-paper plane, behind the 133d/138 guard
protocol (COW branch proof, then production apply, both via the CI gate).

Modes:
  verify  — pre-write gates + in-memory simulation ONLY (every DB touch inside
            SET TRANSACTION READ FIRST... READ ONLY txns). Zero writes.
  apply   — pre-write gates, then ONE transaction per paper-batch with
            per-batch post-gates before commit; on any gate failure the
            already-committed batches are restored byte-exact from the
            before-images (spec §4.3 fail-closed law), receipt verdict FAIL.

Pins of record (all hard-fail):
  table.v1.json sha256 ........ 1fdd4b4a5ebede2e437473e55a2786dea1a9755d03b68d1eea78a39364e2094a
                                (syllabai-parser d9c1511, 84 entries + 5 sequence_rules,
                                 pending_register EMPTY, U+F0CF -> U+2209 per run-004 ruling)
  C9 id-set sha256 ............ 4014404b365f21b49e03997c53903a0145189c66ac58a9de38c56d3843c1c037
  before-images sha256 ........ 9d9d84c632cba7236680696e4128bc94636dd8f7f6928347bf2e06ee90984e3b
                                (sha over the UNCOMPRESSED 2,949-row jsonl bytes, 13 fields/row,
                                 run-003 archive semantics as re-verified byte-identical in run-004)
  run-003 .gz artifact sha256 . a542c75ef9c9995a6e78c7439af5f80b7dc2b3a670601e81fd83ac9d33c4aafb
                                (rollback artifact-of-record integrity, from the v2 checkout)
  control-group file sha256 ... a05652a91aedb540726798eba56173537ec7f1df054dca5c5930b561ae62300d
                                (run-003/control-group.json, 200 rows, derivation re-run + equality)

Gate pins (run-004 full-bank re-sim, EXACT):
  subs 20,033 (F0CF 2) / drop 5,146 / seq runs {A1 15, A2 30, A3 1, B4 7, B5 2} = 220 chars /
  ctl spaced 2,000 / len_delta -5,311 / residual PUA ZERO / G-B 0 / idempotence 0.
"""
import argparse
import gzip
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter

import psycopg2
from psycopg2.extras import execute_values

# ---------------------------------------------------------------- pins ----
TABLE_SHA256 = "1fdd4b4a5ebede2e437473e55a2786dea1a9755d03b68d1eea78a39364e2094a"
C9_PIN = "4014404b365f21b49e03997c53903a0145189c66ac58a9de38c56d3843c1c037"
BEFORE_IMAGES_SHA256 = "9d9d84c632cba7236680696e4128bc94636dd8f7f6928347bf2e06ee90984e3b"
RUN003_BGZ_SHA256 = "a542c75ef9c9995a6e78c7439af5f80b7dc2b3a670601e81fd83ac9d33c4aafb"
CONTROL_GROUP_SHA256 = "a05652a91aedb540726798eba56173537ec7f1df054dca5c5930b561ae62300d"

EXPECT = {
    "union_rows": 2949,
    "pua_rows": 2765,
    "ctl_only_rows": 184,
    "pua_by_prefix": {"4MA1": 2572, "4CH1": 135, "4CH0": 58},
    "pua_instances": 25399,
    "pua_distinct": 85,
    "ctl_instances": 2000,
    "subs": 20033,
    "f0cf_subs": 2,
    "drop": 5146,
    "seq_runs": {"SEQ-A1": 15, "SEQ-A2": 30, "SEQ-A3": 1, "SEQ-B4": 7, "SEQ-B5": 2},
    "seq_chars": 220,
    "ctl_spaced": 2000,
    "len_delta": -5311,
    "embed_pre": {"2": 2949},
    "embed_pre_no_vec": 273,
}
CARRIER_IDS = {"e2a2b4c2-ef7b-4756-820a-e7978dba76b5", "9cba1315-c47a-48f4-a0c8-cdd673e5463a"}
MAX_BATCH_ROWS = 400

PUA_RE = "[\ue000-\uf8ff]"
CTL_RE = "[\x01-\x08\x0b\x0c\x0e-\x1f]"
HEADER_RE = re.compile(r"[43]C[HMB]\d \| (Jan|Jun|Nov) \d{4} \|")

WIRE = """JOIN documents d ON d.id = c.document_row_id
          JOIN exam_papers ep ON d.document_id::text = ep.question_paper_document_id
                              OR d.document_id::text = ep.mark_scheme_document_id"""

SNAPSHOT_FIELDS = ["id", "chunk_index", "kind", "page_start", "page_end", "atom_number",
                   "paper_code", "series", "year", "subject_id", "content", "embed_rev",
                   "embedding_is_null"]


class FailClosed(Exception):
    pass


def log(msg):
    print(f"[phase-b] {msg}", flush=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def load_table(path):
    raw = open(path, "rb").read()
    got = sha256_bytes(raw)
    if got != TABLE_SHA256:
        raise FailClosed(f"table sha256 drift: got {got}, pin {TABLE_SHA256}")
    t = json.loads(raw)
    if len(t["entries"]) != 84:
        raise FailClosed(f"table entries {len(t['entries'])} != 84")
    if len(t.get("sequence_rules", [])) != 5:
        raise FailClosed("table sequence_rules != 5")
    if t.get("pending_register", {}).get("items", None) not in ([], None):
        raise FailClosed("pending_register not EMPTY")
    f0cf = [e for e in t["entries"] if e["from"] == "U+F0CF"]
    if len(f0cf) != 1 or f0cf[0].get("to") != "U+2209":
        raise FailClosed("U+F0CF entry missing or wrong target (run-004 ruling pin)")
    return t


def normalize_factory(table):
    seqs = sorted(table["sequence_rules"], key=lambda s: -len(s["from"]))
    singles = {e["from"]: e for e in table["entries"]}

    def normalize(text):
        out, i, n = [], 0, len(text)
        while i < n:
            ch = text[i]
            if "\ue000" <= ch <= "\uf8ff":
                hit = None
                for s in seqs:
                    L = len(s["from"])
                    if all(text[i + j] == chr(int(s["from"][j][2:], 16)) for j in range(L)):
                        hit = s
                        break
                if hit:
                    out.append(chr(int(hit["to"][2:], 16)))
                    i += len(hit["from"])
                    continue
                m = singles.get(f"U+{ord(ch):04X}")
                if m is None:
                    out.append(ch)
                elif m.get("to") in ("DROP", None):
                    pass
                else:
                    out.append(chr(int(m["to"][2:], 16)))
                i += 1
            elif "\x00" <= ch < "\x20" and ch not in "\t\n\r":
                out.append(" ")
                i += 1
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    return normalize, seqs, singles


def accounting(snapshot, seqs, singles):
    """G-C bounded-delta census over the pre-content (canonical run-003/004 method)."""
    seq_runs_used, drop_counts, sub_counts = Counter(), Counter(), Counter()
    ctl_instances = 0
    for s in snapshot:
        pre, i = s["content"], 0
        while i < len(pre):
            ch = pre[i]
            if "\ue000" <= ch <= "\uf8ff":
                hit = None
                for sq in seqs:
                    L = len(sq["from"])
                    if all(pre[i + j] == chr(int(sq["from"][j][2:], 16)) for j in range(L)):
                        hit = sq
                        break
                if hit:
                    seq_runs_used[hit["id"]] += 1
                    i += len(hit["from"])
                    continue
                m = singles.get(f"U+{ord(ch):04X}")
                if m is None:
                    pass
                elif m.get("to") in ("DROP", None):
                    drop_counts[m["from"]] += 1
                else:
                    sub_counts[m["from"]] += 1
                i += 1
            else:
                if "\x00" <= ch < "\x20" and ch not in "\t\n\r":
                    ctl_instances += 1
                i += 1
    return seq_runs_used, drop_counts, sub_counts, ctl_instances


def seq_chars_total(seqs, seq_runs_used):
    return sum(seq_runs_used[sq["id"]] * len(sq["from"]) for sq in seqs if sq["id"] in seq_runs_used)


def derive_scope(cur):
    cur.execute(
        f"""SELECT DISTINCT c.id, c.chunk_index, c.kind, c.page_start, c.page_end,
                c.atom_number, c.paper_code, c.series, c.year, c.subject_id, c.content,
                c.embed_rev, (c.embedding IS NULL) AS no_vec,
                (c.content ~ %s) AS has_pua, (c.content ~ %s) AS has_ctl
                FROM document_chunks c {WIRE}
                WHERE c.content ~ %s OR c.content ~ %s""",
        (PUA_RE, CTL_RE, PUA_RE, CTL_RE))
    rows = cur.fetchall()
    snapshot = [{"id": str(r[0]), "chunk_index": r[1], "kind": r[2], "page_start": r[3],
                 "page_end": r[4], "atom_number": r[5], "paper_code": r[6], "series": r[7],
                 "year": r[8], "subject_id": r[9], "content": r[10], "embed_rev": r[11],
                 "embedding_is_null": r[12]} for r in rows]
    pua_rows = sum(1 for r in rows if r[13])
    ctl_only = sum(1 for r in rows if not r[13])
    prefix = Counter((s["paper_code"] or "?").split("/")[0] for s in snapshot if any(
        "\ue000" <= ch <= "\uf8ff" for ch in s["content"]))
    ids = sorted(s["id"] for s in snapshot)
    c9 = sha256_bytes("\n".join(ids).encode())
    pua_inst = sum(sum(1 for ch in s["content"] if "\ue000" <= ch <= "\uf8ff") for s in snapshot)
    pua_distinct = len({ch for s in snapshot for ch in s["content"] if "\ue000" <= ch <= "\uf8ff"})
    return snapshot, {"union_rows": len(snapshot), "pua_rows": pua_rows, "ctl_only_rows": ctl_only,
                      "pua_by_prefix": dict(prefix), "c9": c9,
                      "pua_instances": pua_inst, "pua_distinct": pua_distinct}


def serialize_snapshot(snapshot):
    return "\n".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in snapshot).encode()


def embed_pre_state(cur):
    cur.execute(f"""SELECT c.embed_rev, count(*), sum(CASE WHEN c.embedding IS NULL THEN 1 ELSE 0 END)
                    FROM document_chunks c {WIRE}
                    WHERE c.content ~ %s OR c.content ~ %s GROUP BY 1 ORDER BY 1""",
                (PUA_RE, CTL_RE))
    rows = cur.fetchall()
    return {str(r[0]): r[1] for r in rows}, {r[0]: int(r[2]) for r in rows}


def derive_control_group(cur, v2_repo):
    """Verbatim run-003/004 derivation (random.seed(141)); compared vs the pinned file."""
    cg_path = os.path.join(v2_repo, ".syllabai/receipts/T-MIG-141/run-003/control-group.json")
    raw = open(cg_path, "rb").read()
    got = sha256_bytes(raw)
    if got != CONTROL_GROUP_SHA256:
        raise FailClosed(f"control-group.json sha drift: got {got}, pin {CONTROL_GROUP_SHA256}")
    r3_control = json.loads(raw)

    cur.execute(f"""SELECT c.id, c.content FROM document_chunks c
                    WHERE c.content !~ %s AND c.content !~ %s
                    ORDER BY c.id LIMIT 200""", (PUA_RE, CTL_RE))
    clean_pool = cur.fetchall()
    random.seed(141)
    clean_100 = random.sample(clean_pool, min(100, len(clean_pool)))
    cur.execute(f"""SELECT c.id, c.content FROM document_chunks c
                    WHERE c.content ~ %s
                      AND NOT EXISTS (SELECT 1 FROM documents d JOIN exam_papers ep
                                      ON d.document_id::text = ep.question_paper_document_id
                                         OR d.document_id::text = ep.mark_scheme_document_id
                                      WHERE d.id = c.document_row_id)
                    ORDER BY c.id""", (PUA_RE,))
    unwired_pool = cur.fetchall()
    unwired_100 = random.sample(unwired_pool, min(100, len(unwired_pool)))
    control = [{"id": str(i), "content_sha256": sha256_bytes(c.encode()), "class": "clean"}
               for i, c in clean_100] + \
              [{"id": str(i), "content_sha256": sha256_bytes(c.encode()), "class": "unwired-pua"}
               for i, c in unwired_100]
    return control, r3_control, len(unwired_pool)


def make_batches(snapshot):
    """One transaction per paper-batch (spec §4.2): key = (paper_code, series, year);
    oversized keys split into <=400-row sub-batches ordered by chunk id."""
    groups = {}
    for s in snapshot:
        key = (s["paper_code"] or "", s["series"] if s["series"] is not None else "",
               s["year"] if s["year"] is not None else "")
        groups.setdefault(key, []).append(s)
    batches = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], str(k[2]))):
        rows = sorted(groups[key], key=lambda s: s["id"])
        for j in range(0, len(rows), MAX_BATCH_ROWS):
            batches.append({"key": key, "rows": rows[j:j + MAX_BATCH_ROWS],
                            "batch_id": f"{key[0]}|{key[1]}|{key[2]}#{j // MAX_BATCH_ROWS + 1}"})
    return batches


def gB_header_ok(pre, post):
    mh, mp = HEADER_RE.search(pre), HEADER_RE.search(post)
    return (not mh) or (bool(mp) and pre[mh.start():mh.end()] == post[mp.start():mp.end()])


def artifacts_clean(content):
    return not any("\ue000" <= ch <= "\uf8ff" for ch in content) and not re.search(CTL_RE, content)


def preflight(conn, table, v2_repo):
    """Pre-write gates (fail-closed). Everything inside READ ONLY txns."""
    gates = {}
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")

    snapshot, scope = derive_scope(cur)
    if scope["union_rows"] != EXPECT["union_rows"]:
        raise FailClosed(f"scope union {scope['union_rows']} != {EXPECT['union_rows']}")
    if scope["pua_rows"] != EXPECT["pua_rows"] or scope["ctl_only_rows"] != EXPECT["ctl_only_rows"]:
        raise FailClosed(f"scope split drift: {scope['pua_rows']}/{scope['ctl_only_rows']}")
    if scope["pua_by_prefix"] != EXPECT["pua_by_prefix"]:
        raise FailClosed(f"paper-code census drift: {scope['pua_by_prefix']}")
    if scope["c9"] != C9_PIN:
        raise FailClosed(f"C9 id-set drift: {scope['c9']}")
    if scope["pua_instances"] != EXPECT["pua_instances"] or scope["pua_distinct"] != EXPECT["pua_distinct"]:
        raise FailClosed(f"PUA instance census drift: {scope['pua_instances']}/{scope['pua_distinct']}")
    gates["C9_id_set"] = {"sha256": scope["c9"], "pin_exact": True}
    gates["scope"] = {k: v for k, v in scope.items() if k != "c9"}

    raw = serialize_snapshot(snapshot)
    bi_sha = sha256_bytes(raw)
    if bi_sha != BEFORE_IMAGES_SHA256:
        raise FailClosed(f"before-images content drift vs run-003/004 pin: {bi_sha}")
    gates["before_images"] = {"rows": len(snapshot), "uncompressed_sha256": bi_sha, "pin_exact": True}

    # run-003 archived .gz rollback artifact integrity (from the v2 checkout)
    bgz_path = os.path.join(v2_repo, ".syllabai/receipts/T-MIG-141/run-003/before-images.jsonl.gz")
    bgz_sha = sha256_bytes(open(bgz_path, "rb").read())
    if bgz_sha != RUN003_BGZ_SHA256:
        raise FailClosed(f"run-003 before-images .gz artifact drift: {bgz_sha}")
    gates["run003_bgz_artifact"] = {"sha256": bgz_sha, "pin_exact": True}

    rev_map, novec_map = embed_pre_state(cur)
    if rev_map != EXPECT["embed_pre"] or novec_map.get(2) != EXPECT["embed_pre_no_vec"]:
        raise FailClosed(f"embed pre-state drift: {rev_map} / no_vec {novec_map}")
    gates["embed_pre_state"] = {"rev": rev_map, "no_vec": novec_map.get(2)}

    control, r3_control, unwired_pool_n = derive_control_group(cur, v2_repo)
    if control != r3_control:
        raise FailClosed("G-E control group derivation DRIFT vs run-003 pin")
    gates["G-E_control_group"] = {"pinned": len(control), "identical_to_run003": True,
                                  "unwired_pool_size": unwired_pool_n}
    conn.commit()
    return snapshot, gates, control


def simulate(snapshot, normalize, seqs, singles):
    """In-memory gate simulation over the pre-content (the apply expectation)."""
    expected, idem_fail, len_delta = {}, 0, 0
    gB_fail, gD_fail = [], []
    residual = Counter()
    for s in snapshot:
        pre = s["content"]
        post = normalize(pre)
        expected[s["id"]] = post
        if normalize(post) != post:
            idem_fail += 1
        len_delta += len(post) - len(pre)
        if not gB_header_ok(pre, post):
            gB_fail.append(s["id"])
        if not artifacts_clean(post):
            gD_fail.append(s["id"])
            for ch in post:
                if "\ue000" <= ch <= "\uf8ff":
                    residual[ch] += 1
    seq_runs_used, drop_counts, sub_counts, ctl_instances = accounting(snapshot, seqs, singles)
    return {"expected": expected, "idem_fail": idem_fail, "len_delta": len_delta,
            "gB_fail": gB_fail, "gD_fail": gD_fail, "residual": residual,
            "seq_runs_used": seq_runs_used, "drop_counts": drop_counts,
            "sub_counts": sub_counts, "ctl_instances": ctl_instances}


def assert_accounting(sim, table):
    seq_runs_used = sim["seq_runs_used"]
    for sq in table["sequence_rules"]:
        if seq_runs_used.get(sq["id"], 0) != sq["runs"]:
            raise FailClosed(f"SEQ {sq['id']}: used {seq_runs_used.get(sq['id'], 0)} != pinned {sq['runs']}")
    subs = sum(sim["sub_counts"].values())
    drop = sum(sim["drop_counts"].values())
    seq_chars = seq_chars_total(table["sequence_rules"], seq_runs_used)
    if subs != EXPECT["subs"] or sim["sub_counts"].get("U+F0CF", 0) != EXPECT["f0cf_subs"]:
        raise FailClosed(f"G-C subs pin FAIL: {subs} (F0CF {sim['sub_counts'].get('U+F0CF', 0)})")
    if drop != EXPECT["drop"] or seq_chars != EXPECT["seq_chars"]:
        raise FailClosed(f"G-C drop/seq pins FAIL: drop {drop}, seq_chars {seq_chars}")
    if sim["ctl_instances"] != EXPECT["ctl_spaced"] or sim["len_delta"] != EXPECT["len_delta"]:
        raise FailClosed(f"G-C ctl/len_delta pins FAIL: ctl {sim['ctl_instances']}, len_delta {sim['len_delta']}")
    if sim["idem_fail"] != 0 or sim["gB_fail"] or sim["gD_fail"]:
        raise FailClosed(f"sim gates FAIL: idem {sim['idem_fail']}, G-B {len(sim['gB_fail'])}, G-D {len(sim['gD_fail'])}")
    return {"substitution_instances": subs, "F0CF_subs": sim["sub_counts"].get("U+F0CF", 0),
            "drop_instances": drop, "seq_runs": {k: v for k, v in seq_runs_used.items()},
            "seq_chars": seq_chars, "ctl_spaced": sim["ctl_instances"],
            "len_delta": sim["len_delta"], "insertions": 0}


def apply_batches(conn, snapshot, expected, receipt):
    batches = make_batches(snapshot)
    log(f"APPLY: {len(batches)} paper-batches (max {MAX_BATCH_ROWS} rows each)")
    committed = []
    cur = conn.cursor()
    for b in batches:
        rows = [(s["id"], s["content"], expected[s["id"]]) for s in b["rows"]]
        try:
            execute_values(cur,
                           """UPDATE document_chunks c SET content = data.nc, embed_rev = 1
                              FROM (VALUES %s) AS data(id, oc, nc)
                              WHERE c.id = data.id::uuid AND c.content = data.oc""",
                           rows, template="(%s, %s, %s)", page_size=MAX_BATCH_ROWS)
            if cur.rowcount != len(rows):
                raise FailClosed(f"guard rowcount {cur.rowcount} != {len(rows)} (concurrent drift or content mismatch)")
            ids = [r[0] for r in rows]
            cur.execute("""SELECT c.id, c.chunk_index, c.kind, c.page_start, c.page_end,
                           c.atom_number, c.paper_code, c.series, c.year, c.subject_id,
                           c.content, c.embed_rev, (c.embedding IS NULL)
                           FROM document_chunks c WHERE c.id = ANY(%s::uuid[])""", (ids,))
            post = {str(r[0]): r for r in cur.fetchall()}
            by_id = {s["id"]: s for s in b["rows"]}
            for i in ids:
                r = post.get(i)
                s = by_id[i]
                if r is None:
                    raise FailClosed(f"row vanished post-update: {i}")
                exp = expected[i]
                if (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]) != \
                   (s["chunk_index"], s["kind"], s["page_start"], s["page_end"], s["atom_number"],
                    s["paper_code"], s["series"], s["year"], s["subject_id"]):
                    raise FailClosed(f"G-A identity drift on {i}")
                if r[10] != exp:
                    raise FailClosed(f"G-C byte-exact FAIL on {i}")
                if r[11] != 1:
                    raise FailClosed(f"embed_rev stale-marker missing on {i}")
                if not gB_header_ok(s["content"], r[10]):
                    raise FailClosed(f"G-B header drift on {i}")
                if not artifacts_clean(r[10]):
                    raise FailClosed(f"G-D residual artifact on {i}")
            conn.commit()
            committed.append(b)
            receipt["batches"].append({"batch_id": b["batch_id"], "rows": len(rows), "committed": True})
            log(f"  batch {b['batch_id']}: {len(rows)} rows COMMITTED")
        except Exception as e:
            conn.rollback()
            log(f"  batch {b['batch_id']}: FAILED ({e}) — restoring {len(committed)} committed batches")
            restored = restore_committed(cur, committed, expected)
            conn.commit()
            receipt["restore"] = {"attempted": True, "batches": len(committed), "verified": restored}
            if not restored:
                receipt["disclosures"].append(
                    "RESTORE COULD NOT VERIFY — before-images artifact of record required for manual recovery")
            raise
    receipt["restore"] = {"attempted": False}
    return len(committed)


def restore_committed(cur, committed, expected):
    """Byte-exact rollback from before-images (spec §4.3): content + embed_rev restored."""
    ok = True
    for b in committed:
        rows = [(s["id"], s["content"], s["embed_rev"], expected[s["id"]]) for s in b["rows"]]
        execute_values(cur,
                       """UPDATE document_chunks c SET content = data.oc, embed_rev = data.er
                          FROM (VALUES %s) AS data(id, oc, er, nc)
                          WHERE c.id = data.id::uuid AND c.content = data.nc""",
                       rows, template="(%s, %s, %s, %s)", page_size=MAX_BATCH_ROWS)
        if cur.rowcount != len(rows):
            log(f"  restore guard rowcount {cur.rowcount} != {len(rows)} on {b['batch_id']}")
            ok = False
            continue
        ids = [r[0] for r in rows]
        cur.execute("SELECT c.id, c.content, c.embed_rev FROM document_chunks c WHERE c.id = ANY(%s::uuid[])",
                    (ids,))
        by_id = {s["id"]: s for s in b["rows"]}
        for i, c, er in cur.fetchall():
            if c != by_id[i]["content"] or er != by_id[i]["embed_rev"]:
                log(f"  restore verify FAIL on {i}")
                ok = False
    return ok


def postgates(conn, snapshot, expected, control, receipt):
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    gates = {}

    cur.execute(f"""SELECT DISTINCT c.id FROM document_chunks c {WIRE}
                    WHERE c.content ~ %s OR c.content ~ %s""", (PUA_RE, CTL_RE))
    residual_scope = len(cur.fetchall())
    gates["G-D_zero_artifact_post_state"] = {"scope_regex_hits": residual_scope, "must_be_zero": residual_scope == 0}
    if residual_scope != 0:
        raise FailClosed(f"G-D global FAIL: {residual_scope} rows still match artifact regexes")

    ids = [s["id"] for s in snapshot]
    cur.execute("""SELECT c.id, c.chunk_index, c.kind, c.page_start, c.page_end, c.atom_number,
                   c.paper_code, c.series, c.year, c.subject_id, c.content, c.embed_rev,
                   (c.embedding IS NULL) FROM document_chunks c WHERE c.id = ANY(%s::uuid[])""", (ids,))
    post = {str(r[0]): r for r in cur.fetchall()}
    if len(post) != EXPECT["union_rows"]:
        raise FailClosed(f"C9 post: {len(post)} rows present != {EXPECT['union_rows']}")
    by_id = {s["id"]: s for s in snapshot}
    drift = []
    for i in ids:
        r, s = post[i], by_id[i]
        if (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]) != \
           (s["chunk_index"], s["kind"], s["page_start"], s["page_end"], s["atom_number"],
            s["paper_code"], s["series"], s["year"], s["subject_id"]):
            drift.append(("identity", i))
        if r[10] != expected[i]:
            drift.append(("content", i))
        if r[11] != 1:
            drift.append(("embed_rev", i))
    if drift:
        raise FailClosed(f"C9 post drift: {drift[:10]}{'...' if len(drift) > 10 else ''}")
    no_vec = sum(1 for r in post.values() if r[12])
    gates["C9_post_id_set"] = {"rows": len(post), "identity+content+embed_rev": "EXACT vs before-images+expected"}
    gates["embed_post_state"] = {"rev": {1: len(post)}, "no_vec": no_vec,
                                 "vectors_kept": len(post) - no_vec}
    if no_vec != EXPECT["embed_pre_no_vec"]:
        raise FailClosed(f"embedding IS NULL count changed: {no_vec} != {EXPECT['embed_pre_no_vec']}")

    cur.execute("""SELECT c.id, c.content FROM document_chunks c WHERE c.id = ANY(%s::uuid[])""",
                ([c["id"] for c in control],))
    ge_ok, ge_bad = 0, []
    for i, c in cur.fetchall():
        pin = next(x for x in control if x["id"] == i)
        if sha256_bytes(c.encode()) == pin["content_sha256"]:
            ge_ok += 1
        else:
            ge_bad.append(i)
    gates["G-E_control_group"] = {"pinned": len(control), "byte_identical": ge_ok, "violations": ge_bad}
    if ge_bad:
        raise FailClosed(f"G-E control group VIOLATED: {ge_bad[:5]}")

    cur.execute("""SELECT count(*) FROM document_chunks
                   WHERE id = ANY(%s::uuid[]) AND content_tsv IS DISTINCT FROM to_tsvector('english', content)""",
                (ids,))
    tsv_mismatch = cur.fetchone()[0]
    gates["content_tsv_generated_always"] = {"mismatches": tsv_mismatch}
    if tsv_mismatch != 0:
        raise FailClosed(f"content_tsv mismatch {tsv_mismatch} (GENERATED ALWAYS guarantee broken)")

    cur.execute(f"""SELECT count(*) FROM document_chunks c
                    WHERE (c.content ~ %s OR c.content ~ %s)
                      AND NOT EXISTS (SELECT 1 FROM documents d JOIN exam_papers ep
                                      ON d.document_id::text = ep.question_paper_document_id
                                         OR d.document_id::text = ep.mark_scheme_document_id
                                      WHERE d.id = c.document_row_id)""", (PUA_RE, CTL_RE))
    unwired_residual = cur.fetchone()[0]
    gates["unwired_plane_untouched"] = {"artifact_regex_rows": unwired_residual, "note": "OUT of spec scope; G-E covers 100 sampled"}

    cur.execute("""SELECT count(*) FROM document_chunks c
                   WHERE (c.embedding IS NULL OR c.embed_rev < 2)
                     AND EXISTS (SELECT 1 FROM documents d JOIN exam_papers ep
                                 ON d.document_id::text = ep.question_paper_document_id
                                    OR d.document_id::text = ep.mark_scheme_document_id
                                 WHERE d.id = c.document_row_id)""")
    selector_scope = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM document_chunks WHERE embedding IS NULL OR embed_rev < 2")
    selector_estate = cur.fetchone()[0]
    gates["phase_D_selector_precursor"] = {"scope_rows": selector_scope, "estate_rows": selector_estate}
    conn.commit()
    return gates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["verify", "apply"], required=True)
    ap.add_argument("--db-url", default=None)
    ap.add_argument("--db-file", default=None)
    ap.add_argument("--table", required=True, help="path to table.v1.json (sha-pinned)")
    ap.add_argument("--v2-repo", required=True, help="syllabai-v2 checkout (run-003 pins)")
    ap.add_argument("--target", default="verify", help="label: cow | prod | verify")
    ap.add_argument("--artifacts-dir", default=".")
    ap.add_argument("--receipt", required=True)
    args = ap.parse_args()

    receipt = {"run": "run-005-phase-b-realwrite", "task": "T-MIG-141", "driver": "phase_b_apply.py (FROZEN)",
               "mode": args.mode, "target": args.target, "verdict": None,
               "operator_gate": "workflow_dispatch fire order = operator go (trace 1a169fc63e946759)",
               "disclosures": [], "batches": [], "restore": {"attempted": False}}

    table = load_table(args.table)
    normalize, seqs, singles = normalize_factory(table)
    log(f"table pinned OK ({len(table['entries'])} entries + {len(table['sequence_rules'])} seq rules)")

    db_url = args.db_url
    if not db_url and args.db_file:
        for line in open(args.db_file).read().strip().splitlines():
            val = line.split("=", 1)[1] if "=" in line and "://" in line else line
            if "://" in val:
                db_url = val.strip()
                break
    if not db_url:
        raise FailClosed("no --db-url / --db-file with a valid URL")

    conn = psycopg2.connect(db_url, connect_timeout=30, sslmode="require")
    try:
        snapshot, pre_gates, control = preflight(conn, table, args.v2_repo)
        receipt["pre_gates"] = pre_gates
        log(f"pre-write gates GREEN: scope {pre_gates['scope']['union_rows']} rows, C9 pin-exact, "
            f"before-images pin-exact, control group identical")

        sim = simulate(snapshot, normalize, seqs, singles)
        acc = assert_accounting(sim, table)
        receipt["G-C_bounded_delta"] = acc
        log(f"G-C simulation EXACT: {json.dumps(acc, sort_keys=True)}")

        os.makedirs(args.artifacts_dir, exist_ok=True)
        raw = serialize_snapshot(snapshot)
        gz_path = os.path.join(args.artifacts_dir, "before-images.jsonl.gz")
        with gzip.open(gz_path, "wb") as f:
            f.write(raw)
        receipt["before_images_artifact"] = {"path": os.path.basename(gz_path), "rows": len(snapshot),
                                             "uncompressed_sha256": sha256_bytes(raw)}

        if args.mode == "verify":
            receipt["verdict"] = "GREEN-VERIFY (zero writes)"
            receipt["sim_gates"] = {"G-B_violations": len(sim["gB_fail"]), "G-D_exceptions": len(sim["gD_fail"]),
                                    "residual_pua": dict(sim["residual"]), "idempotence_failures": sim["idem_fail"]}
        else:
            apply_conn = psycopg2.connect(db_url, connect_timeout=30, sslmode="require")
            try:
                n = apply_batches(apply_conn, snapshot, sim["expected"], receipt)
                log(f"APPLY complete: {n}/{len(receipt['batches'])} batches committed")
            finally:
                apply_conn.close()
            post_conn = psycopg2.connect(db_url, connect_timeout=30, sslmode="require")
            try:
                receipt["post_gates"] = postgates(post_conn, snapshot, sim["expected"], control, receipt)
                log(f"post-write gates: {json.dumps(receipt['post_gates'], default=str)[:400]}...")
            finally:
                post_conn.close()
            receipt["verdict"] = "GREEN-APPLY"
    except FailClosed as e:
        receipt["verdict"] = "FAIL-CLOSED"
        receipt["failure"] = str(e)
        log(f"FAIL-CLOSED: {e}")
    finally:
        conn.close()

    with open(args.receipt, "w") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=1, default=str)
    log(f"receipt -> {args.receipt}")
    if receipt["verdict"] not in ("GREEN-VERIFY (zero writes)", "GREEN-APPLY"):
        sys.exit(1)
    log("VERDICT GREEN")


if __name__ == "__main__":
    main()
