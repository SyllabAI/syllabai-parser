"""Stage 1 structure engine: PyMuPDF (fitz) blocks + tables + figures.

Port of the T-C17-proven extractor (scripts/pymupdf_parse_2012jan.py), with
ONE engineered addition — the total-row span patch (FAILSAFE_PLAN §4 / F2):
merged-cell "Total N marks" rows are typeset BELOW the last ruled table row,
so every table detector loses them. Here, text lines excluded because they
fall inside a table region are re-admitted when they match the total-row
pattern, and re-inserted at their true y-position.

No OCR, no model calls: same PDF + code -> byte-identical output.
"""
import json
import os
import re

import fitz

TOTAL_ROW_RE = re.compile(r"^\s*Total\s+(\d{1,3})\s+marks?\s*$", re.I)


def page_to_md(page, doc, assets_dir, prefix, asset_counter):
    """Return (markdown_lines, block_records, new_asset_counter)."""
    lines = []
    blocks = []
    items = []  # (y0, kind, payload, bbox)

    # tables (dedupe overlapping detections: find_tables can emit the same
    # grid region twice on ruled papers -> mark-cell duplication)
    table_boxes = []
    try:
        tabs = page.find_tables()
        for t in tabs.tables:
            bb = t.bbox
            dup = False
            for sb in table_boxes:
                ix = max(0, min(bb[2], sb[2]) - max(bb[0], sb[0]))
                iy = max(0, min(bb[3], sb[3]) - max(bb[1], sb[1]))
                if ix * iy > 0.5 * min((bb[2] - bb[0]) * (bb[3] - bb[1]),
                                       (sb[2] - sb[0]) * (sb[3] - sb[1])):
                    dup = True
                    break
            if not dup:
                table_boxes.append(bb)
                items.append((bb[1], "table", t.extract(), bb))
    except Exception as e:  # table detection failure must not kill the run
        items.append((0.0, "table-error", ["[table detection failed: %s]" % e], None))

    # text lines NOT covered by a table region; total rows re-admitted (patch)
    d = page.get_text("dict")
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            bb = l["bbox"]
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            covered = any(tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3] for tb in table_boxes)
            s = "".join(sp.get("text", "") for sp in l.get("spans", []))
            if not s.strip():
                continue
            if covered:
                m = TOTAL_ROW_RE.match(s.strip())
                if m:  # ---- total-row span patch (F2) ----
                    items.append((bb[1], "total-row", [s.rstrip()], bb))
                # else: genuinely inside a ruled table -> handled by table emit
                continue
            items.append((bb[1], "text-line", [s.rstrip()], bb))

    # images
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        if not rects:
            continue
        r = rects[0]
        if r.width < 8 or r.height < 8:
            continue
        asset_counter += 1
        name = "%s_p%02d_%02d.png" % (prefix, page.number + 1, asset_counter)
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pix.save(os.path.join(assets_dir, name))
        except Exception:
            pass
        items.append((r.y0, "image",
                      ["![figure](assets/%s)" % name], (r.x0, r.y0, r.x1, r.y1)))

    items.sort(key=lambda t: (t[0], t[3][0] if t[3] else 0))
    for y0, kind, payload, bbox in items:
        if kind == "text-line":
            for ln in payload:
                lines.append(ln)
                blocks.append({"page": page.number + 1, "kind": "text",
                               "y0": round(y0, 1), "text": ln})
        elif kind == "total-row":
            lines.append("")
            lines.append("**%s**" % payload[0].strip())
            lines.append("")
            blocks.append({"page": page.number + 1, "kind": "total-row",
                           "y0": round(y0, 1), "text": payload[0].strip()})
        elif kind == "table":
            lines.append("")
            ncols = max(len(r) for r in payload)
            for ri, row in enumerate(payload):
                cells = [(c or "").replace("\n", " ").strip() for c in row]
                while len(cells) < ncols:
                    cells.append("")
                lines.append("| " + " | ".join(cells) + " |")
                if ri == 0:
                    lines.append("|" + "---|" * ncols)
            lines.append("")
            blocks.append({"page": page.number + 1, "kind": "table",
                           "y0": round(y0, 1), "rows": len(payload)})
        elif kind == "image":
            lines.append("")
            lines.append(payload[0])
            lines.append("")
            blocks.append({"page": page.number + 1, "kind": "image",
                           "y0": round(y0, 1), "text": payload[0]})
        else:
            lines.extend(payload)
    return lines, blocks, asset_counter


def extract(pdf_path, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    assets_dir = os.path.join(out_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    md_lines, all_blocks, counter = [], [], 0
    for page in doc:
        md_lines.append("<!-- PAGE %d -->" % (page.number + 1))
        plines, pblocks, counter = page_to_md(page, doc, assets_dir, prefix, counter)
        md_lines.extend(plines)
        md_lines.append("")
        all_blocks.extend(pblocks)
    md_path = os.path.join(out_dir, prefix + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
    blocks_path = os.path.join(out_dir, prefix.lower() + "-blocks.json")
    with open(blocks_path, "w", encoding="utf-8") as f:
        json.dump(all_blocks, f, indent=1)
    doc.close()
    assets = sorted(os.listdir(assets_dir))
    return {"md": md_path, "blocks": blocks_path, "assets_dir": assets_dir,
            "assets": ["assets/" + a for a in assets], "pages": len(all_blocks and set(b["page"] for b in all_blocks) or set()),
            "asset_count": len(assets),
            "total_rows": sum(1 for b in all_blocks if b["kind"] == "total-row")}
