"""Printed-identity extraction + check — the G6 identity gate (F10 cure).

The 2026-09-11 baseline resolver bucketed "X QP" and "X (R) QP" into one
identity slot and pinned regional-variant bytes under base identities
(AUDIT-2026-09-12 §F10; corpus repaired 2026-09-25, docs/REPAIR-2026-09-25.md
in SyllabAI/syllabai-pastpapers). This gate closes the ingestion-side hole:
the printed Paper Reference on the PDF cover must agree with the identity the
operator claims (--paper-code), and the printed exam date must not contradict
the claimed session.

Deterministic: regex extraction over pdftotext page-1 text only; no
timestamps; identical input text produces identical output.

Verdict rules (gate G6):
  FAIL               printed refs contradict the expected reference
                     (expected ref absent, or a same-unit different-variant
                     ref printed — e.g. expected 4CH1/1C, printed 4CH1/1CR)
  PASS_WITH_FLAGS    refs agree but session drifts (e.g. June-printed QP in a
                     November session — the COVID June/Nov reuse pairing) or
                     the MS cover token disagrees
  PASS               refs + session agree
  PASS (+flag)       cover carries no readable refs (scanned cover):
                     IDENTITY-COVER-UNREADABLE review flag — surfaced, never
                     silently treated as verified
When no expected identity is supplied (--paper-code empty) the gate is not
emitted at all, preserving byte-identical reports for existing callers.
"""
import re

REF_RE = re.compile(r"\b(\d[A-Z]{2}\d{1,2}|[A-Z]{3}\d{2})/([0-9]{1,2}[A-Z]{0,2})\b")
PAPER_TOKEN_RE = re.compile(r"Paper:\s*([0-9][A-Z]{0,2})")
MS_PAPER_TOKEN_RE = re.compile(r"Paper\s+([0-9][A-Z]{0,2})[:\s]")
DATE_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday)\s+(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{4})")
MS_SESSION_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{4})")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def extract(text):
    """Printed identity from one cover page's text.

    Returns {"refs": ["4CH1/1C", ...], "paper": "1C"|None,
             "date": "YYYY-MM-DD"|None, "session_hint": "January 2020"|None}.
    """
    refs = [f"{a}/{b}" for a, b in REF_RE.findall(text)]
    pm = PAPER_TOKEN_RE.search(text)
    dm = DATE_RE.search(text)
    sm = MS_SESSION_RE.search(text)
    date = None
    if dm:
        date = f"{dm.group(4)}-{MONTHS[dm.group(3)]:02d}-{int(dm.group(2)):02d}"
    return {"refs": refs, "paper": pm.group(1) if pm else None, "date": date,
            "session_hint": f"{sm.group(1)} {sm.group(2)}" if sm else None}


def _variant_conflict(expected, refs):
    """Same unit, different variant printed (e.g. expect 4CH1/1C, see 4CH1/1CR)."""
    unit = expected.split("/")[0]
    exp_variant = expected.split("/")[1]
    out = []
    for r in refs:
        if r.split("/")[0] == unit and r.split("/")[1] != exp_variant:
            out.append(r)
    return out


def check_qp(expected_paper_code, expected_session, printed):
    """QP cover check -> (ok, detail) where ok False means gate FAIL."""
    exp_ref = expected_paper_code
    detail = {"expected_ref": exp_ref, "printed_refs": printed["refs"],
              "printed_paper": printed["paper"], "printed_date": printed["date"]}
    if not printed["refs"]:
        return None, detail  # unreadable cover — flag, not fail
    conflict = _variant_conflict(exp_ref, printed["refs"])
    if conflict:
        return False, {**detail, "mismatch": "VARIANT-CONFLICT", "conflicting_refs": conflict}
    if exp_ref not in printed["refs"]:
        return False, {**detail, "mismatch": "REF-ABSENT"}
    return True, detail


def _printed_ym(printed):
    """(month, year) from the printed date or the MS session header, else None."""
    if printed.get("date"):
        dy, dm_, _ = printed["date"].split("-")
        return int(dm_), int(dy)
    hint = printed.get("session_hint")
    if hint:
        try:
            m, y = hint.split()
            return MONTHS[m], int(y)
        except (ValueError, KeyError):
            return None
    return None


def check_session(expected_session, printed):
    """Session/date cross-check -> flag dict or None (drift is a flag, not a fail:
    the COVID June-print/November-administration pairing prints June dates on
    November-session papers by design)."""
    if not expected_session or not printed:
        return None
    try:
        m, y = expected_session.split()
        exp = (MONTHS[m], int(y))
    except (ValueError, KeyError):
        return None
    got = _printed_ym(printed)
    if got and got != exp:
        return {"code": "IDENTITY-SESSION-DRIFT", "taxonomy": "SOURCE-DISCREPANCY",
                "detail": {"expected_session": expected_session,
                           "printed_date": printed.get("date"),
                           "printed_session_hint": printed.get("session_hint"),
                           "note": "month/year of printed exam date differs from the "
                                   "claimed session (COVID June/Nov reuse precedent, "
                                   "P-code pairing) — confirm pairing before ingest"}}
    return None


def check_ms(expected_paper_code, printed_ms):
    """MS cover token check (MSs rarely print full refs). Returns flag or None."""
    tok = printed_ms.get("paper")
    if not tok:
        return None
    exp_variant = expected_paper_code.split("/")[1] if "/" in expected_paper_code else None
    if exp_variant and tok != exp_variant:
        return {"code": "IDENTITY-MS-PAPER-TOKEN-MISMATCH", "taxonomy": "SOURCE-DISCREPANCY",
                "detail": {"expected_variant": exp_variant, "printed_paper_token": tok}}
    return None


def build(expected_paper_code, expected_session, printed_qp, printed_ms,
          qp_present=True):
    """Assemble the G6 gate block + review flags. Caller supplies extracted
    printed identities (extract()) and the operator-claimed identity.

    qp_present=False (MS-only products) skips the QP check entirely — there
    is no QP cover to read, and absence of a QP is not an identity finding.

    Returns {"gate": {...}, "flags": [...]} — gate None when not applicable.
    """
    if not expected_paper_code:
        return None
    g6 = {"checks": {}}
    flags = []
    ok_qp = None
    if qp_present:
        ok_qp, qp_detail = check_qp(expected_paper_code, expected_session, printed_qp)
        if ok_qp is None:
            g6["checks"]["qp_printed_ref"] = {"ok": True, "indeterminate": True,
                                              "detail": qp_detail}
            flags.append({"code": "IDENTITY-COVER-UNREADABLE", "taxonomy": "SOURCE-DISCREPANCY",
                          "detail": {"unit": "QP", "cover": qp_detail}})
        else:
            g6["checks"]["qp_printed_ref"] = {"ok": ok_qp, "detail": qp_detail}
        sess_flag = check_session(expected_session, printed_qp)
        if sess_flag:
            flags.append(sess_flag)
    ms_flag = check_ms(expected_paper_code, printed_ms)
    if ms_flag:
        flags.append(ms_flag)
    ms_sess_flag = check_session(expected_session, printed_ms)
    if ms_sess_flag:
        flags.append(ms_sess_flag)
    hard_fail = qp_present and ok_qp is False
    g6["verdict"] = ("FAIL" if hard_fail
                     else "PASS_WITH_FLAGS" if flags else "PASS")
    return {"gate": g6, "flags": flags}
