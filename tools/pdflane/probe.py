"""Stage 0 text-layer probe: classify each PDF DIGITAL_NATIVE / MIXED / SCANNED.

Deterministic (PyMuPDF only). Per page: text chars, raster coverage, image
count. Routing rule (FAILSAFE_PLAN §4): scanned-like page = image coverage
> 0.55 AND text chars < 250. Paper verdict SCANNED if a majority of content
pages are scanned-like, MIXED if any are, else DIGITAL_NATIVE.
"""
import json

import fitz

SCANNED_MIN_COVERAGE = 0.55
SCANNED_MAX_CHARS = 250


def probe(pdf_path):
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        text_chars = len(page.get_text("text").strip())
        coverage = 0.0
        n_imgs = 0
        for img in page.get_images(full=True):
            try:
                rects = page.get_image_rects(img[0])
            except Exception:
                rects = []
            for r in rects:
                n_imgs += 1
                area = r.width * r.height
                if area > 0:
                    coverage += area / (page.rect.width * page.rect.height)
        scanned_like = coverage > SCANNED_MIN_COVERAGE and text_chars < SCANNED_MAX_CHARS
        pages.append({"page": page.number + 1, "text_chars": text_chars,
                      "images": n_imgs, "image_coverage": round(coverage, 3),
                      "scanned_like": scanned_like})
    doc.close()
    n_scanned = sum(1 for p in pages if p["scanned_like"])
    if n_scanned > len(pages) / 2:
        verdict = "SCANNED"
    elif n_scanned:
        verdict = "MIXED"
    else:
        verdict = "DIGITAL_NATIVE"
    return {"pdf": pdf_path, "page_count": len(pages), "pages": pages,
            "scanned_like_pages": [p["page"] for p in pages if p["scanned_like"]],
            "verdict": verdict,
            "route": "vision" if verdict == "SCANNED" else "deterministic"}


def probe_both(qp_pdf, ms_pdf):
    r = {"QP": probe(qp_pdf), "MS": probe(ms_pdf)}
    return r


def probe_ms_only(ms_pdf):
    """MS-only probe (COVID-session papers ship ms.pdf without a QP)."""
    return {"MS": probe(ms_pdf)}


if __name__ == "__main__":
    import sys
    print(json.dumps(probe_both(sys.argv[1], sys.argv[2]), indent=1))
