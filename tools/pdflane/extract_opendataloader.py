"""Stage 1 second opinion: OpenDataLoader 2.5.7 shaded CLI (repo T-009 engine).

Wraps the GitHub-release shaded CLI (Maven Central lacks its verapdf pins —
recorded deviation from the adapter's normal Maven resolution). Deterministic
given PDF bytes + flags (proven byte-identical re-run in T-C17 experiment).
"""
import glob
import os
import subprocess

CLI_JAR = "/home/z/my-project/tc17-work/jars/odl-cli/opendataloader-pdf-cli-2.5.7.jar"


def extract(pdf_path, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    img_dir = os.path.join(out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    sep = "\n\n<!-- PAGE %page-number% -->\n\n"
    cmd = ["java", "-jar", CLI_JAR,
           "--format", "json,markdown",
           "--image-output", "external",
           "--image-dir", img_dir,
           "--markdown-page-separator", sep,
           "--keep-line-breaks",
           "--reading-order", "xycut",
           "-q",
           "-o", out_dir,
           pdf_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    md = glob.glob(os.path.join(out_dir, "*.md"))
    js = glob.glob(os.path.join(out_dir, "*.json"))
    if proc.returncode != 0 or not md:
        raise RuntimeError("OpenDataLoader CLI failed rc=%s: %s" % (proc.returncode, proc.stderr[-800:]))
    md_path = max(md, key=os.path.getsize)
    json_path = max(js, key=os.path.getsize) if js else None
    return {"md": md_path, "json": json_path,
            "images": sorted(os.path.relpath(p, out_dir) for p in glob.glob(os.path.join(img_dir, "*")))}
