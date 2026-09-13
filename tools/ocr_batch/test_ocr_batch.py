"""Unit tests for tools/ocr_batch/ocr_batch.py — mocked HTTP, real rasterization.

Run:  python3 -m unittest tools/ocr_batch/test_ocr_batch.py -v
(or:  python3 tools/ocr_batch/test_ocr_batch.py)

Network access is NOT required: both backends run against a local mock
server. The rasterization test uses a hand-built two-page PDF and the real
pypdfium2 (when available) — skipped with a loud mark when pypdfium2 is
absent, per the project's claim discipline.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocr_batch as ob  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

MINIMAL_TWO_PAGE_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] >> endobj
4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] >> endobj
xref
0 5
trailer << /Size 5 /Root 1 0 R >>
%%EOF
"""


class MockServer:
    """Threaded mock endpoint with programmable responses per path."""

    def __init__(self):
        self.requests: list[dict] = []      # parsed bodies
        self.headers: list[dict] = []
        self.routes: dict[str, callable] = {}   # path -> handler(body_dict) -> (status, obj|bytes, ctype)
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                outer._handle(self)

            def do_GET(self):
                outer._handle(self)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base = f"http://127.0.0.1:{self._server.server_port}"

    def _handle(self, handler: BaseHTTPRequestHandler):
        length = int(handler.headers.get("Content-Length", 0) or 0)
        raw = handler.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {"_raw": raw[:200].decode("utf-8", "replace")}
        self.requests.append(body)
        self.headers.append(dict(handler.headers.items()))
        route = self.routes.get(handler.path)
        if route is None:
            payload = json.dumps({"error": "no route"}).encode("utf-8")
            handler.send_response(404)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
            return
        status, payload, ctype = route(body)
        if isinstance(payload, bytes):
            handler.send_response(status)
            handler.send_header("Content-Type", ctype or "application/octet-stream")
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
        else:
            blob = json.dumps(payload).encode("utf-8")
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(blob)))
            handler.end_headers()
            handler.wfile.write(blob)

    def url(self, path: str) -> str:
        return self.base + path

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def make_cfg(server: MockServer, **overrides) -> ob.Config:
    cfg = ob.Config(
        api_url=server.url("/layout_parsing"),
        api_key="test-key-123",
        api_key_source="test",
        ollama_url=server.base,
        retries=2,
        retry_base_seconds=0.01,
        image_timeout=10,
        request_timeout=30,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def maas_response(md: str, crop_url: str | None = None) -> dict:
    resp = {
        "id": "resp-1",
        "created": 1700000000,
        "model": "glm-ocr",
        "request_id": "req-1",
        "md_results": md,
        "layout_details": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    if crop_url:
        resp["layout_details"] = [{"crop_url": crop_url}]
    return resp


# --------------------------------------------------------------------------- #
# api backend
# --------------------------------------------------------------------------- #

class ApiBackendTests(unittest.TestCase):
    def setUp(self):
        self.server = MockServer()
        self.addCleanup(self.server.close)
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.pdf = self.tmp / "paper.pdf"
        self.pdf.write_bytes(MINIMAL_TWO_PAGE_PDF)

    def test_string_md_saved_byte_exact_with_assets(self):
        crop_url = self.server.url("/img/crop_1_1774977205806.png")
        md = (f"# Paper\n\n<div style='text-align: center;'>"
              f"<img src='{crop_url}' alt='OCR图片'/></div>\n\n1 Find x. (3)")
        self.server.routes["/layout_parsing"] = lambda b: (200, maas_response(md, crop_url), "")
        self.server.routes["/img/crop_1_1774977205806.png"] = lambda b: (200, PNG_1X1, "image/png")

        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertTrue(ok, row)
        out_dir = self.tmp / "out" / "paper"

        # byte-exact markdown
        self.assertEqual((out_dir / "paper.md").read_text(encoding="utf-8"), md)
        # asset downloaded with URL-derived name (website convention)
        asset_file = out_dir / "assets" / "crop_1_1774977205806.png"
        self.assertTrue(asset_file.exists())
        self.assertEqual(asset_file.read_bytes(), PNG_1X1)
        # manifest integrity
        manifest = json.loads((out_dir / "manifest.json").read_text())
        self.assertEqual(manifest["markdown"]["sha256"], ob.sha256_hex(md.encode("utf-8")))
        self.assertEqual(manifest["assets"][0]["sha256"], ob.sha256_hex(PNG_1X1))
        self.assertEqual(manifest["assets"][0]["width"], 1)
        self.assertEqual(manifest["assets"][0]["sniffedMime"], "image/png")
        # provenance: usage + no key material anywhere on disk
        prov = json.loads((out_dir / "provenance.json").read_text())
        self.assertEqual(prov["response"]["usage"]["totalTokens"], 30)
        dumped = "".join(p.read_text(errors="replace") for p in out_dir.rglob("*") if p.is_file())
        self.assertNotIn("test-key-123", dumped)
        # request shape: model + data URI + return_crop_images + auth header
        req = self.server.requests[0]
        self.assertEqual(req["model"], "glm-ocr")
        self.assertTrue(req["file"].startswith("data:application/pdf;base64,"))
        self.assertTrue(req["return_crop_images"])
        auth = next(v for k, v in self.server.headers[0].items()
                    if k.lower() == "authorization")
        self.assertEqual(auth, "Bearer test-key-123")

    def test_list_md_results_joined_with_pages(self):
        self.server.routes["/layout_parsing"] = lambda b: (
            200, {**maas_response(""), "md_results": ["page one", "page two"]}, "")
        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertTrue(ok, row)
        out_dir = self.tmp / "out" / "paper"
        self.assertEqual((out_dir / "paper.md").read_text(), "page one\n\npage two")
        self.assertEqual((out_dir / "pages" / "page_001.md").read_text(), "page one")
        self.assertEqual((out_dir / "pages" / "page_002.md").read_text(), "page two")

    def test_retry_on_500_then_success(self):
        calls = {"n": 0}

        def handler(body):
            calls["n"] += 1
            if calls["n"] == 1:
                return (500, {"error": "transient"}, "")
            return (200, maas_response("recovered"), "")

        self.server.routes["/layout_parsing"] = handler
        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertTrue(ok, row)
        self.assertEqual(calls["n"], 2)

    def test_empty_md_fails_loud(self):
        self.server.routes["/layout_parsing"] = lambda b: (200, maas_response("   "), "")
        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertFalse(ok)
        self.assertIn("empty", row["error"])

    def test_missing_md_results_fails_loud(self):
        self.server.routes["/layout_parsing"] = lambda b: (200, {"unexpected": True}, "")
        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertFalse(ok)
        self.assertIn("md_results", row["error"])

    def test_no_md_written_on_failure(self):
        self.server.routes["/layout_parsing"] = lambda b: (200, {"unexpected": True}, "")
        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ob.process_paper(self.pdf, cfg)
        self.assertFalse((self.tmp / "out" / "paper" / "paper.md").exists())

    def test_page_range_passes_params(self):
        seen = {}

        def handler(body):
            seen.update(body)
            return (200, maas_response("range ok"), "")

        self.server.routes["/layout_parsing"] = handler
        cfg = make_cfg(self.server, out_dir=self.tmp / "out",
                       start_page=2, end_page=3)
        ok, _ = ob.process_paper(self.pdf, cfg)
        self.assertTrue(ok)
        # requested end=3 is honestly clamped to the real page count (2)
        self.assertEqual(seen.get("start_page_id"), 2)
        self.assertEqual(seen.get("end_page_id"), 2)

    def test_unfetched_asset_recorded_not_fatal(self):
        dead = "https://expired.invalid/crop_9.png"
        md = f"<img src='{dead}' alt='OCR图片'/>"
        self.server.routes["/layout_parsing"] = lambda b: (200, maas_response(md, dead), "")
        cfg = make_cfg(self.server, out_dir=self.tmp / "out")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertTrue(ok)
        manifest = json.loads(((self.tmp / "out" / "paper" / "manifest.json").read_text()))
        self.assertEqual(manifest["assets"], [])
        self.assertEqual(len(manifest["unfetchedAssets"]), 1)


# --------------------------------------------------------------------------- #
# ollama backend
# --------------------------------------------------------------------------- #

def _has_pdfium() -> bool:
    try:
        import pypdfium2  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_has_pdfium(), "pypdfium2 not installed")
class OllamaBackendTests(unittest.TestCase):
    def setUp(self):
        self.server = MockServer()
        self.addCleanup(self.server.close)
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.pdf = self.tmp / "paper.pdf"
        self.pdf.write_bytes(MINIMAL_TWO_PAGE_PDF)

    def test_two_pages_ocr_joined(self):
        seen_images = []

        def generate(body):
            seen_images.append(len(body.get("images", [])))
            self.assertEqual(body["prompt"], ob.OCR_PROMPT)
            self.assertEqual(body["options"]["num_ctx"], ob.DEFAULT_NUM_CTX)
            self.assertEqual(body["options"]["temperature"], 0)
            return (200, {"response": f"page text {len(seen_images)}", "done": True}, "")

        self.server.routes["/api/generate"] = generate
        cfg = make_cfg(self.server, out_dir=self.tmp / "out", backend="ollama")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertTrue(ok, row)
        self.assertEqual(seen_images, [1, 1])
        out_dir = self.tmp / "out" / "paper"
        self.assertEqual((out_dir / "paper.md").read_text(),
                         "page text 1\n\npage text 2")
        manifest = json.loads((out_dir / "manifest.json").read_text())
        self.assertTrue(manifest["warnings"])   # model-only honesty note present
        self.assertEqual(manifest["markdown"]["pageCount"], 2)

    def test_empty_page_output_fails_with_ctx_hint(self):
        self.server.routes["/api/generate"] = lambda b: (200, {"response": "", "done": True}, "")
        cfg = make_cfg(self.server, out_dir=self.tmp / "out", backend="ollama")
        ok, row = ob.process_paper(self.pdf, cfg)
        self.assertFalse(ok)
        self.assertIn("num-ctx", row["error"])


# --------------------------------------------------------------------------- #
# unit-level helpers
# --------------------------------------------------------------------------- #

class HelperTests(unittest.TestCase):
    def test_png_dims(self):
        self.assertEqual(ob.image_dims(PNG_1X1), (1, 1))

    def test_sniff_mime(self):
        self.assertEqual(ob.sniff_mime(PNG_1X1), "image/png")
        self.assertEqual(ob.sniff_mime(b"\xff\xd8\xff\xe0xyz"), "image/jpeg")
        self.assertEqual(ob.sniff_mime(b"not-an-image"), "application/octet-stream")

    def test_safe_remote_name(self):
        self.assertEqual(
            ob._safe_remote_name(
                "https://host/ocr%2Fcrop%2Fx%2Fcrop_3_1774977205.png?a=b", 0, ""),
            "crop_3_1774977205.png")
        self.assertEqual(ob._safe_remote_name("https://host/", 4, ""), "crop_5.bin")

    def test_extract_crop_urls_dedup(self):
        md = ("<img src='https://h/a.png'> and ![](https://h/b.jpg) "
              "and <img src=\"https://h/a.png\">")
        urls = ob._extract_crop_urls({}, md)
        self.assertEqual(urls, ["https://h/a.png", "https://h/b.jpg"])

    def test_png_encode_roundtrip(self):
        w, h = 2, 2
        rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])
        png = ob.png_encode_rgb(w, h, rgb)
        self.assertEqual(ob.image_dims(png), (w, h))
        self.assertEqual(ob.sniff_mime(png), "image/png")

    def test_collect_inputs_dedup_sorted(self):
        import tempfile, shutil
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "b.pdf").write_bytes(b"x")
        (tmp / "a.pdf").write_bytes(b"x")
        (tmp / "notes.txt").write_bytes(b"x")
        got = ob.collect_inputs([str(tmp)])
        self.assertEqual([p.name for p in got], ["a.pdf", "b.pdf"])
        self.assertEqual(len(ob.collect_inputs([str(tmp), str(tmp / "a.pdf")])), 2)

    def test_resolve_api_key_env_precedence(self):
        import os
        old = {k: os.environ.get(k) for k in ob.ENV_KEY_NAMES}
        try:
            os.environ.pop("ZAI_API_KEY", None)
            os.environ["ZHIPU_API_KEY"] = "zhipu-key"
            key, source = ob.resolve_api_key("")
            self.assertEqual((key, source), ("zhipu-key", "ZHIPU_API_KEY"))
            os.environ["ZAI_API_KEY"] = "zai-key"
            key, source = ob.resolve_api_key("")
            self.assertEqual(source, "ZAI_API_KEY")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main(verbosity=2)
