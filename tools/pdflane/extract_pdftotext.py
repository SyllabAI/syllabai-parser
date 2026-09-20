"""Stage 1 base layer: pdftotext -layout extraction, per-page.

The plain text layer is the token-level source of truth (proven: it carries
the merged-cell "Total N marks" rows that all table detectors lose).
Deterministic given PDF bytes + poppler version.
"""
import json
import os
import subprocess


def extract(pdf_path, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    txt_path = os.path.join(out_dir, prefix.lower() + "-layout.txt")
    subprocess.run(["pdftotext", "-layout", pdf_path, txt_path], check=True)
    with open(txt_path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    pages = raw.split("\f")
    if pages and pages[-1] == "":
        pages = pages[:-1]
    md_lines = []
    pages_json = []
    for i, ptxt in enumerate(pages, 1):
        md_lines.append("<!-- PAGE %d -->" % i)
        md_lines.append(ptxt.rstrip())
        pages_json.append({"page": i, "text": ptxt})
    md_path = os.path.join(out_dir, prefix + "-layout.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
    with open(os.path.join(out_dir, prefix.lower() + "-layout-pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages_json, f, indent=1)
    return {"md": md_path, "txt": txt_path,
            "pages_json": os.path.join(out_dir, prefix.lower() + "-layout-pages.json"),
            "pages": len(pages),
            "chars": sum(len(p) for p in pages)}
