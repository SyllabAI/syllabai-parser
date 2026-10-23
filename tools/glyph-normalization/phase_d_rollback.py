#!/usr/bin/env python3
"""T-MIG-141 Phase-D rollback driver (the spec §9 restore unit for the
re-embed leg — operator-gated, CI only).

Restores the pre-Phase-D state for a list of chunk ids from the
before-images archive of record: embedding <- archived old vector,
embedding_model <- archived model, embedded_at <- archived timestamp,
embed_rev <- 1 (stale marker). Guarded: only rows CURRENTLY at the post
state (embed_rev = 2) are touched; rowcount must be 1 per row.

The archive is byte-pinned: the uncompressed jsonl sha256 must equal
  101a3450dc409d8a20cee79e39ca40bb8375990855cedd7e92ac33a55fdcf558

Usage:
  phase_d_rollback.py --db-file F --before-images IMG.gz [--ids IDS.txt] --receipt R
  (--ids default: every id in the archive)
"""
import argparse
import base64
import gzip
import hashlib
import json
import struct
import sys

import psycopg2

RAW_SHA = "101a3450dc409d8a20cee79e39ca40bb8375990855cedd7e92ac33a55fdcf558"


def log(msg):
    print(f"[phase-d-rollback] {msg}", flush=True)


def resolve_db_url(args):
    db_url = args.db_url
    if not db_url and args.db_file:
        for line in open(args.db_file).read().strip().splitlines():
            line = line.strip()
            if "://" not in line:
                continue
            eq = line.find("=")
            if eq != -1 and line.find("://") > eq:
                line = line[eq + 1:]
            db_url = line
            break
    if not db_url:
        raise SystemExit("no --db-url / --db-file with a valid URL")
    return db_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=None)
    ap.add_argument("--db-file", default=None)
    ap.add_argument("--before-images", required=True)
    ap.add_argument("--ids", default=None)
    ap.add_argument("--receipt", required=True)
    args = ap.parse_args()

    raw = gzip.open(args.before_images, "rb").read()
    got = hashlib.sha256(raw).hexdigest()
    if got != RAW_SHA:
        raise SystemExit(f"before-images raw sha mismatch: {got}")
    rows = [json.loads(l) for l in raw.decode().splitlines() if l.strip()]
    by_id = {r["id"]: r for r in rows}
    log(f"archive: {len(rows)} rows, raw sha OK")

    want_ids = set(open(args.ids).read().split()) if args.ids else set(by_id)
    missing = want_ids - set(by_id)
    if missing:
        raise SystemExit(f"{len(missing)} requested ids not in the archive, e.g. {sorted(missing)[:3]}")
    log(f"rollback scope: {len(want_ids)} rows")

    receipt = {"run": "run-007-phase-d-rollback", "task": "T-MIG-141",
               "scope": len(want_ids), "written": 0, "verdict": None}
    conn = psycopg2.connect(resolve_db_url(args), connect_timeout=30, sslmode="require")
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ WRITE")
        for cid in sorted(want_ids):
            r = by_id[cid]
            vec = struct.unpack("<768f", base64.b64decode(r["vec_b64"]))
            lit = "[" + ",".join(repr(float(x)) for x in vec) + "]"
            cur.execute("""UPDATE document_chunks
                           SET embedding = %s::vector, embedding_model = %s,
                               embedded_at = %s, embed_rev = %s
                           WHERE id = %s::uuid AND embed_rev = 2""",
                        (lit, r["model"], r["embedded_at"], r["rev"], cid))
            if cur.rowcount != 1:
                raise SystemExit(f"guarded restore hit {cur.rowcount} rows for {cid} — ROLLING BACK")
            receipt["written"] += 1
        conn.commit()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT count(*) FROM document_chunks WHERE embedding IS NULL OR embed_rev < 2")
        receipt["selector_after"] = cur.fetchone()[0]
        conn.rollback()
        receipt["verdict"] = "GREEN"
        log(f"restored {receipt['written']} rows | selector now {receipt['selector_after']}")
    except SystemExit as e:
        conn.rollback()
        receipt["verdict"] = f"FAIL-CLOSED: {e}"
        raise
    finally:
        json.dump(receipt, open(args.receipt, "w"), indent=1)
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
