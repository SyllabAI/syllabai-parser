#!/usr/bin/env python3
"""T-MIG-141 Phase-D re-embed fold-in driver (deterministic, no LLM in the
patch loop — the "LLM" here is the embedding provider of record only).

Spec §6: re-embed the Phase-D selector (`embedding IS NULL OR embed_rev < 2`)
in deterministic tranches, flip each row to embed_rev=2 on success, behind a
HARD drift gate: cosine(old vector, new vector) median >= 0.85 over every
re-embedded row that carries an old vector (a full per-tranche census —
stronger than the spec's "stratified sample of >= 300"). Below the gate the
tranche aborts with ZERO writes and exit 3 -> operator ruling, never silent
accept.

WHY A NEW DRIVER (spec deviation, disclosed): the frozen T-MIG-133d port
embedDocument() only touches `embedding IS NULL` rows and never writes
embed_rev — it physically cannot re-embed the 2,676 stale-marked (rev=1,
vector kept serving) rows that Phase D exists to refresh. This driver adds
the minimal write law on top of the frozen semantics: same provider model
(gemini-embedding-001, 768-dim, plain embedContent, outputDimensionality
768), same pacing/backoff constants, embed-validate-everything-first, then
one transaction of row updates. mode=backfill-sharded is superseded by
T-MIG-138 run-003's empirical finding of record (operator pool keys carry no
legacy 1000-RPD embedding class) — the sharded LAW (RPD-wall honesty, skipped
rows recorded, exit 0 on rate walls) is preserved here in single-key
sequential form.

Pins of record (all hard-fail; from the run-007 pre-flight census,
t0_readonly, zero writes):
  C9-D selector id-set sha256 .. eb43f28cf405817db5bc14c7f744003130f7b9b9d1a116f2d45d0e37503a2720
                                 (sha256 over "\\n".join(document_row_id || '/' || id), ordered)
  selector-ids.txt sha256 ...... 1a1bc83d20891c1a3efe7eb13b64a28408446a0b26c2f526c3f13f8a6e8e201d
                                 (4,006 lines, born-clean subset anchor)
  before-manifest sha256 ....... a12b1d418af7c359fa084d458abe07a6b3309c65756980dbdbfb62a03f3b4ee8
                                 (2,676 rows: id/doc/rev/model/vec_sha256)
  before-images .gz sha256 ..... 2e021ce651e20b057289d79c10ebc54ac09c24ce0d8bf55ad8e24a11276b83c5
                                 (8,348,334 B, deterministic mtime=0 container)
  before-images raw sha256 ..... 101a3450dc409d8a20cee79e39ca40bb8375990855cedd7e92ac33a55fdcf558
                                 (sha over the UNCOMPRESSED jsonl bytes)

Bank pins (run-006 of record): 13,765 chunks, embed_hist {1: 2949, 2: 10816},
no_vec 1,330; selector 4,006 = stale_with_vec 2,676 + stale_no_vec 273 +
nullvec_rev2 1,057; every embedded row's model = gemini-embedding-001.

Modes:
  verify — READ ONLY (SET TRANSACTION READ ONLY on every txn). Bank pins,
           selector pins, C9-D recompute, born-clean subset check, per-row
           vec-sha proof over ALL current stale-with-vec rows (bank-undrifted),
           model law, tranche preview. ZERO writes, ZERO embedding-API calls.
  apply  — verify block first (fail-closed), then: tranche = first N rows of
           the live selector (ORDER BY document_row_id, id — the live DB is
           the resume pointer; wall-hit rows simply remain for the next
           dispatch), embed ALL with 90-RPM pacing + 429 backoff (30s * 2^k,
           4 retries), validate EVERY vector (dim 768) before ANY write,
           HARD drift gate (census over the tranche's old-vector rows),
           soft neighbor-Jaccard report (up to 300 rows, serving plane), then
           ONE transaction of guarded updates (WHERE ... AND (embedding IS NULL
           OR embed_rev < 2); rowcount must be 1 per row). RPD-wall honesty:
           on a 429 surviving the retry chain the row + every not-attempted
           row are recorded to the skipped artifact and the run exits 0 after
           writing what it already embedded (a NON-rate failure exits 1; a
           red drift gate exits 3 with zero writes).

Region law: the Gemini embedding API is IP-region-gated — apply runs where
egress is supported (GitHub Actions), never the sandbox. verify never calls
the API.

Secrets: SYLLABAI_EMBEDDING_GEMINI_API_KEY (apply; never printed).
Usage:
  phase_d_reembed.py verify --db-file F --manifest M --selector-ids S --receipt R
  phase_d_reembed.py apply  --db-file F --manifest M --selector-ids S \
                            --tranche-size 1000 --receipt R --artifacts-dir D
"""
import argparse
import base64
import hashlib
import json
import os
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request

import psycopg2

# ---------- pins of record (hard-fail) ----------
C9D_SHA = "eb43f28cf405817db5bc14c7f744003130f7b9b9d1a116f2d45d0e37503a2720"
SELECTOR_IDS_SHA = "1a1bc83d20891c1a3efe7eb13b64a28408446a0b26c2f526c3f13f8a6e8e201d"
MANIFEST_SHA = "a12b1d418af7c359fa084d458abe07a6b3309c65756980dbdbfb62a03f3b4ee8"
BANK_TOTAL = 13765
EMBED_HIST = {"1": 2949, "2": 10816}
NO_VEC_BANK = 1330
SEL_TOTAL_MAX = 4006
STALE_VEC_PIN = 2676
STALE_NOVEC_PIN = 273
NULLVEC_REV2_PIN = 1057
MODEL = "gemini-embedding-001"
EMBED_DIM = 768
DRIFT_MEDIAN_MIN = 0.85
RPM_FLOOR_MS = 667          # 90 RPM — the executor-of-record pacing constant
MAX_429_RETRIES = 4
EMBED_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "gemini-embedding-001:embedContent")


class FailClosed(Exception):
    pass


def log(msg):
    print(f"[phase-d] {msg}", flush=True)


def sha256_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def resolve_db_url(args):
    db_url = args.db_url
    if not db_url and args.db_file:
        for line in open(args.db_file).read().strip().splitlines():
            line = line.strip()
            if "://" not in line:
                continue
            eq = line.find("=")
            if eq != -1 and line.find("://") > eq:
                line = line[eq + 1:]  # KEY=URL form (env-style creds file)
            db_url = line
            break
    if not db_url:
        raise FailClosed("no --db-url / --db-file with a valid URL")
    return db_url


def load_manifest(path):
    if sha256_file(path) != MANIFEST_SHA:
        raise FailClosed(f"manifest sha mismatch: {path}")
    m = {}
    for line in open(path):
        r = json.loads(line)
        m[r["id"]] = r["vec_sha256"]
    if len(m) != STALE_VEC_PIN:
        raise FailClosed(f"manifest rows {len(m)} != {STALE_VEC_PIN}")
    return m


def load_selector_ids(path):
    if sha256_file(path) != SELECTOR_IDS_SHA:
        raise FailClosed(f"selector-ids sha mismatch: {path}")
    return set(line.strip() for line in open(path) if line.strip())


def vec_pack(vec):
    return struct.pack("<768f", *[float(x) for x in vec])


def vec_sha(vec):
    return hashlib.sha256(vec_pack(vec)).hexdigest()


def vec_literal(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def connect_ro(db_url):
    conn = psycopg2.connect(db_url, connect_timeout=30, sslmode="require")
    return conn


def verify_block(conn, manifest, pinned_sel_ids, receipt):
    """All read-only pins. Raises FailClosed on ANY drift. Runs inside
    SET TRANSACTION READ ONLY. Drain-aware: the pins hold EXACTLY at the
    pre-drain estate; mid-drain the invariants are the monotonic-shrink and
    identity laws (selector only shrinks, rev-1 rows are exactly the
    not-yet-drained selector rows, no_vec identity holds)."""
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")

    cur.execute("SELECT count(*) FROM document_chunks")
    bank_total = cur.fetchone()[0]
    cur.execute("SELECT embed_rev, count(*) FROM document_chunks GROUP BY 1 ORDER BY 1")
    hist = {str(r): n for r, n in cur.fetchall()}
    cur.execute("SELECT count(*) FROM document_chunks WHERE embedding IS NULL")
    no_vec = cur.fetchone()[0]
    cur.execute("""SELECT count(*),
                          count(*) FILTER (WHERE embed_rev < 2 AND embedding IS NOT NULL),
                          count(*) FILTER (WHERE embed_rev < 2 AND embedding IS NULL),
                          count(*) FILTER (WHERE embed_rev = 2 AND embedding IS NULL)
                   FROM document_chunks WHERE embedding IS NULL OR embed_rev < 2""")
    sel_total, stale_vec, stale_novec, nullvec_rev2 = cur.fetchone()

    # drain-aware bank invariants
    if bank_total != BANK_TOTAL:
        raise FailClosed(f"bank total drifted: {bank_total} != {BANK_TOTAL}")
    if set(hist) != {"1", "2"}:
        raise FailClosed(f"embed_rev domain drifted: {hist}")
    if hist["1"] + hist["2"] != BANK_TOTAL:
        raise FailClosed(f"embed_hist inconsistent: {hist}")
    if hist["1"] + nullvec_rev2 != sel_total:
        raise FailClosed(f"selector law violated: rev-1 {hist['1']} + nullvec_rev2 "
                         f"{nullvec_rev2} != selector {sel_total}")
    if no_vec != stale_novec + nullvec_rev2:
        raise FailClosed(f"no_vec identity violated: {no_vec} != "
                         f"{stale_novec} + {nullvec_rev2}")
    if sel_total > SEL_TOTAL_MAX:
        raise FailClosed(f"selector grew: {sel_total} > {SEL_TOTAL_MAX}")
    if sel_total == SEL_TOTAL_MAX:
        if hist != EMBED_HIST or no_vec != NO_VEC_BANK:
            raise FailClosed(f"pre-drain bank pins drifted: hist {hist}, no_vec {no_vec}")
        if (stale_vec, stale_novec, nullvec_rev2) != (STALE_VEC_PIN, STALE_NOVEC_PIN, NULLVEC_REV2_PIN):
            raise FailClosed(f"selector breakdown drifted at full size: "
                             f"{(stale_vec, stale_novec, nullvec_rev2)}")
    if stale_vec + stale_novec + nullvec_rev2 != sel_total:
        raise FailClosed("selector breakdown inconsistent")

    cur.execute("""SELECT document_row_id::text || '/' || id::text FROM document_chunks
                   WHERE embedding IS NULL OR embed_rev < 2
                   ORDER BY document_row_id, id""")
    live_ids = [r[0] for r in cur.fetchall()]
    live_c9d = hashlib.sha256("\n".join(live_ids).encode()).hexdigest()
    new_entries = set(live_ids) - pinned_sel_ids
    if new_entries:
        raise FailClosed(f"BORN-CLEAN VIOLATION: {len(new_entries)} selector rows "
                         f"are not in the pinned pre-drain set, e.g. {sorted(new_entries)[:3]}")
    c9d_state = ("EXACT" if live_c9d == C9D_SHA else
                 f"SHRUNK ({len(live_ids)}/{SEL_TOTAL_MAX} remain — drain in progress, subset law GREEN)")

    cur.execute("""SELECT embedding_model, count(*) FROM document_chunks
                   WHERE embed_rev < 2 AND embedding IS NOT NULL GROUP BY 1""")
    models = dict(cur.fetchall())
    if set(models) != {MODEL}:
        raise FailClosed(f"stale-vec model law violated: {models}")

    # bank-undrifted proof: every CURRENT stale-with-vec row's vector must
    # hash to its pinned pre-drain sha (drained rows have left the set)
    cur.execute("""SELECT id::text, embedding::real[] FROM document_chunks
                   WHERE embed_rev < 2 AND embedding IS NOT NULL""")
    checked, mismatches = 0, []
    for cid, vec in cur.fetchall():
        want = manifest.get(cid)
        if want is None:
            mismatches.append((cid, "not-in-manifest"))
            continue
        if vec_sha(vec) != want:
            mismatches.append((cid, "sha-mismatch"))
        checked += 1
    if mismatches:
        raise FailClosed(f"OLD-VECTOR SHA PROOF RED (bank drifted or manifest stale): {len(mismatches)} mismatches, "
                         f"e.g. {mismatches[:3]}")
    if checked != stale_vec:
        raise FailClosed(f"undrifted census incomplete: {checked} != {stale_vec}")

    conn.rollback()
    rep = {
        "bank": {"total": bank_total, "embed_hist": hist, "no_vec": no_vec},
        "selector": {"total": sel_total, "stale_with_vec": stale_vec,
                     "stale_no_vec": stale_novec, "nullvec_rev2": nullvec_rev2,
                     "c9d": c9d_state, "born_clean_subset": "GREEN",
                     "undrifted_vec_rows_checked": checked},
        "stale_vec_models": models,
    }
    log(f"verify GREEN: bank {bank_total} | selector {sel_total} "
        f"(stale_vec {stale_vec}, no_vec {stale_novec}+{nullvec_rev2}) | "
        f"C9-D {c9d_state} | undrifted shas {checked}/{len(manifest)} checked")
    return rep, sel_total


def embed_one(api_key, text):
    """The frozen provider's request shape, verbatim (plain embedContent,
    outputDimensionality 768, no taskType, no failover)."""
    body = json.dumps({
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": EMBED_DIM,
    }).encode()
    req = urllib.request.Request(EMBED_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    })
    last_err = None
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                data = json.loads(res.read())
            values = (data.get("embedding") or {}).get("values")
            if not values or len(values) != EMBED_DIM:
                raise FailClosed(f"provider returned {None if values is None else len(values)} "
                                 f"dims, expected {EMBED_DIM}")
            return values
        except urllib.error.HTTPError as e:
            msg = f"embedding provider request failed with status {e.code} — no failover by design"
            if e.code == 429 and attempt < MAX_429_RETRIES:
                backoff = 30_000 * 2 ** attempt / 1000.0
                log(f"429 rate-limited — backoff {backoff}s (attempt {attempt + 1}/{MAX_429_RETRIES})")
                time.sleep(backoff)
                last_err = (e.code, msg)
                continue
            raise RuntimeError(msg) from e
        except FailClosed:
            raise
    raise RuntimeError(last_err[1] if last_err else "embedding failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["verify", "apply"])
    ap.add_argument("--db-url", default=None)
    ap.add_argument("--db-file", default=None)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--selector-ids", required=True)
    ap.add_argument("--tranche-size", type=int, default=1000)
    ap.add_argument("--jaccard-rows", type=int, default=300)
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--artifacts-dir", default=".")
    args = ap.parse_args()

    receipt = {
        "run": "run-007-phase-d-fold-in",
        "task": "T-MIG-141",
        "driver": "phase_d_reembed.py",
        "mode": args.mode,
        "tranche_size": args.tranche_size,
        "verdict": None,
        "operator_gate": "workflow_dispatch fire order = operator go (Proceed, trace 1a16aeddae71c715)",
        "pins": {"C9D": C9D_SHA, "selector_ids": SELECTOR_IDS_SHA, "manifest": MANIFEST_SHA,
                 "drift_median_min": DRIFT_MEDIAN_MIN, "model": MODEL},
        "disclosures": [
            "frozen 133d port cannot re-embed stale rows (embedding-is-null-only, "
            "never writes embed_rev) — this driver adds the minimal Phase-D write law "
            "(same provider shape, same pacing constants), disclosed in the run-007 receipt",
            "mode=backfill-sharded superseded by T-MIG-138 run-003 empirical finding "
            "(pool keys lack the legacy 1000-RPD class); sharded RPD-wall LAW preserved "
            "in single-key sequential form",
            "drift gate = FULL per-tranche census over old-vector rows (>= the spec's "
            "stratified sample of 300); neighbor Jaccard = soft report (spec season 1)",
        ],
    }

    manifest = load_manifest(args.manifest)
    pinned_sel_ids = load_selector_ids(args.selector_ids)
    log(f"pins loaded: manifest {len(manifest)} rows, selector anchor {len(pinned_sel_ids)} ids")

    db_url = resolve_db_url(args)
    conn = connect_ro(db_url)
    try:
        rep, sel_total = verify_block(conn, manifest, pinned_sel_ids, receipt)
        receipt["verify"] = rep

        if args.mode == "verify":
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("""SELECT id::text, document_row_id::text,
                                  (embed_rev < 2 AND embedding IS NOT NULL)
                           FROM document_chunks
                           WHERE embedding IS NULL OR embed_rev < 2
                           ORDER BY document_row_id, id LIMIT %s""", (args.tranche_size,))
            preview = cur.fetchall()
            conn.rollback()
            receipt["tranche_preview"] = {
                "size": len(preview),
                "with_old_vec": sum(1 for r in preview if r[2]),
            }
            receipt["verdict"] = "GREEN (read-only)"
            json.dump(receipt, open(args.receipt, "w"), indent=1)
            log(f"verify mode complete — ZERO writes, ZERO API calls")
            return 0

        # ---------------- apply ----------------
        api_key = os.environ.get("SYLLABAI_EMBEDDING_GEMINI_API_KEY", "").strip()
        if not api_key:
            raise FailClosed("SYLLABAI_EMBEDDING_GEMINI_API_KEY is blank — abort")

        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("""SELECT id::text, content, embedding::real[], embed_rev
                       FROM document_chunks
                       WHERE embedding IS NULL OR embed_rev < 2
                       ORDER BY document_row_id, id LIMIT %s""", (args.tranche_size,))
        tranche = cur.fetchall()
        conn.rollback()
        if not tranche:
            receipt["verdict"] = "GREEN (selector already drained — nothing to do)"
            json.dump(receipt, open(args.receipt, "w"), indent=1)
            log("selector EMPTY — drain complete")
            return 0
        log(f"tranche: {len(tranche)} rows "
            f"({sum(1 for r in tranche if r[2] is not None)} with old vector)")

        # embed-validate-EVERYTHING-first (a provider outage stores nothing)
        embedded = []          # (id, new_vec)
        skipped = []           # rows not attempted (RPD wall)
        wall = False
        t0 = time.monotonic()
        for i, (cid, content, old_vec, rev) in enumerate(tranche):
            if wall:
                skipped.append(cid)
                continue
            wait = RPM_FLOOR_MS / 1000.0
            time.sleep(wait)  # constant floor pacing between API calls
            try:
                vec = embed_one(api_key, content)
            except RuntimeError as e:
                if "status 429" in str(e):
                    wall = True
                    skipped.append(cid)
                    log(f"RPD/429 wall at row {cid} ({i + 1}/{len(tranche)}) — "
                        f"key budget drained; remaining rows skipped honestly")
                    continue
                raise
            embedded.append((cid, vec, old_vec, rev))
        elapsed = time.monotonic() - t0
        log(f"embedded {len(embedded)}/{len(tranche)} in {elapsed:.0f}s "
            f"(wall={wall}, skipped={len(skipped)})")

        os.makedirs(args.artifacts_dir, exist_ok=True)
        if skipped:
            sp = os.path.join(args.artifacts_dir, "skipped-rows.txt")
            open(sp, "w").write("\n".join(skipped) + "\n")
            receipt["skipped_artifact"] = sp
        receipt["embed"] = {"embedded": len(embedded), "wall": wall,
                            "skipped": len(skipped), "secs": round(elapsed, 1)}

        if not embedded:
            receipt["verdict"] = "GREEN (RPD wall at row 0 — honest no-op, zero writes)"
            json.dump(receipt, open(args.receipt, "w"), indent=1)
            log("wall at first row — zero writes, exit 0 (resume on next dispatch)")
            return 0

        # dimension law re-assert (validate-everything-first)
        for cid, vec, _, _ in embedded:
            if len(vec) != EMBED_DIM:
                raise FailClosed(f"dim law violated for {cid}: {len(vec)}")

        # HARD drift gate: full census over the tranche's old-vector rows
        cosines = []
        for cid, vec, old_vec, _ in embedded:
            if old_vec is not None:
                cosines.append({"id": cid, "cosine": cosine(old_vec, vec)})
        drift = {"n": len(cosines)}
        if cosines:
            vals = [c["cosine"] for c in cosines]
            drift.update({
                "min": round(min(vals), 6),
                "median": round(statistics.median(vals), 6),
                "p10": round(sorted(vals)[max(0, len(vals) // 10)], 6),
                "gate": "PENDING",
            })
            gate_ok = statistics.median(vals) >= DRIFT_MEDIAN_MIN
            drift["gate"] = "GREEN" if gate_ok else "RED"
            cp = os.path.join(args.artifacts_dir, "drift-cosines.json")
            json.dump(cosines, open(cp, "w"), indent=0)
            receipt["drift_artifact"] = cp
            receipt["drift"] = drift
            log(f"drift census n={drift['n']}: median {drift['median']} "
                f"(min {drift['min']}, p10 {drift['p10']}) -> gate {drift['gate']}")
            if not gate_ok:
                receipt["verdict"] = ("FAIL-CLOSED: drift gate RED — ZERO writes, "
                                      "operator ruling required (exit 3)")
                json.dump(receipt, open(args.receipt, "w"), indent=1)
                log(receipt["verdict"])
                return 3
        else:
            receipt["drift"] = {"n": 0, "note": "no old-vector rows in this tranche "
                                "(never-embedded residual only) — gate vacuous, disclosed"}
            log("drift gate vacuous (n=0, no old-vector rows in tranche)")

        # soft neighbor-Jaccard report on the serving plane (up to N rows)
        jac_rows = [(cid, vec, old_vec) for cid, vec, old_vec, _ in embedded
                    if old_vec is not None][:args.jaccard_rows]
        jac_stats = {"n": len(jac_rows)}
        if jac_rows:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            js = []
            for cid, vec, old_vec in jac_rows:
                cur.execute("""SELECT id::text FROM document_chunks
                               WHERE embed_rev = 2 AND id <> %s::uuid
                               ORDER BY embedding <=> %s::vector LIMIT 10""",
                            (cid, vec_literal(old_vec)))
                old_nb = {r[0] for r in cur.fetchall()}
                cur.execute("""SELECT id::text FROM document_chunks
                               WHERE embed_rev = 2 AND id <> %s::uuid
                               ORDER BY embedding <=> %s::vector LIMIT 10""",
                            (cid, vec_literal(vec)))
                new_nb = {r[0] for r in cur.fetchall()}
                union = old_nb | new_nb
                js.append(len(old_nb & new_nb) / len(union) if union else 1.0)
            conn.rollback()
            jac_stats.update({"mean": round(sum(js) / len(js), 4),
                              "min": round(min(js), 4)})
            receipt["neighbor_jaccard"] = jac_stats
            log(f"neighbor Jaccard (soft): n={jac_stats['n']} mean {jac_stats['mean']} "
                f"min {jac_stats['min']}")

        # ONE transaction of guarded updates
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ WRITE")
        written = 0
        for cid, vec, _, _ in embedded:
            cur.execute("""UPDATE document_chunks
                           SET embedding = %s::vector, embedding_model = %s,
                               embedded_at = now(), embed_rev = 2
                           WHERE id = %s::uuid
                             AND (embedding IS NULL OR embed_rev < 2)""",
                        (vec_literal(vec), MODEL, cid))
            if cur.rowcount != 1:
                raise FailClosed(f"guarded update hit {cur.rowcount} rows for {cid} "
                                 f"(expected 1) — ROLLING BACK")
            written += 1
        conn.commit()
        log(f"txn committed: {written} rows -> embed_rev=2")

        # post-txn verify
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("""SELECT count(*) FILTER (WHERE embed_rev <> 2 OR embedding IS NULL
                                              OR embedding_model <> %s
                                              OR array_length(embedding::real[], 1) <> 768)
                       FROM document_chunks WHERE id = ANY(%s::uuid[])""",
                    (MODEL, [e[0] for e in embedded]))
        bad = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM document_chunks
                       WHERE embedding IS NULL OR embed_rev < 2""")
        sel_after = cur.fetchone()[0]
        conn.rollback()
        if bad:
            raise FailClosed(f"post-txn verify RED: {bad} rows not at the of-record state")
        receipt["write"] = {"written": written, "post_bad_rows": bad,
                            "selector_after": sel_after}
        receipt["verdict"] = "GREEN"
        json.dump(receipt, open(args.receipt, "w"), indent=1)
        log(f"apply GREEN: {written} written | selector {sel_after} remaining "
            f"(expect {SEL_TOTAL_MAX - (SEL_TOTAL_MAX - sel_total)})")
        return 0

    except FailClosed as e:
        conn.rollback()
        receipt["verdict"] = f"FAIL-CLOSED: {e}"
        json.dump(receipt, open(args.receipt, "w"), indent=1)
        log(receipt["verdict"])
        return 1
    except Exception as e:  # honest red — never a silent partial
        conn.rollback()
        receipt["verdict"] = f"FAIL: {type(e).__name__}: {e}"
        json.dump(receipt, open(args.receipt, "w"), indent=1)
        log(receipt["verdict"])
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
