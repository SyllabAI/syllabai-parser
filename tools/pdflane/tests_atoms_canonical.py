"""Canonical bridge selftests (atoms/1.1 → canonical schema 1.0).

Run:  python3 -m pdflane.tests_atoms_canonical
Exit 0 = all green. Covers: identity derivation lockstep with the audited
glmocr mirror, validator-mirror rejections, chunk-simulation equivalence with
core ChunkingService semantics, page-alignment behavior, leakage guard, and a
full synthetic-document conversion round-trip. The 10-product chemistry corpus
run is exercised separately (corpus smoke test skips when the corpus is absent).
"""
import json
import os
import shutil
import tempfile
import unittest

from glmocr.canonical import content_document_id
from pdflane import atoms_to_canonical as bridge


def text_block(text, page=1, role="paragraph"):
    return {"element_id": "e000000", "element_type": "text_block",
            "page_number": page, "bounding_box": None, "text": text,
            "reading_order": 0, "confidence": 1.0, "role": role,
            "heading_level": None, "source_engine": bridge.ENGINE_NAME,
            "source_engine_version": bridge.ENGINE_VERSION}


def base_doc(**overrides):
    doc = {
        "documentId": content_document_id("ab" * 32, bridge.ENGINE_NAME,
                                          bridge.ENGINE_VERSION),
        "schemaVersion": "1.0", "version": 1,
        "source": {"uri": "x/qp.pdf", "checksum": "ab" * 32,
                   "checksumAlgorithm": "SHA-256", "mimeType": "application/pdf",
                   "fileName": "qp.pdf"},
        "pageCount": 3,
        "pages": [{"pageNumber": n, "width": None, "height": None}
                  for n in (1, 2, 3)],
        "sections": [{"sectionId": "q01", "title": "Question 1", "level": 1,
                      "pageNumber": 1, "elementIds": ["e000000"]}],
        "textBlocks": [text_block("hello world")],
        "tables": [], "figures": [], "equations": [],
        "provenance": {"engine": bridge.ENGINE_NAME,
                       "engineVersion": bridge.ENGINE_VERSION,
                       "extractedAt": None, "extractionParams": {},
                       "application": "syllabai-parser",
                       "schemaVersion": "1.0"},
    }
    doc.update(overrides)
    return doc


class IdentityLockstep(unittest.TestCase):
    def test_matches_audited_glmocr_mirror(self):
        for checksum, engine, version in (
                ("ab" * 32, "pdflane-atoms", "1.1.0"),
                ("0" * 64, "glm-ocr-markdown", "1.2.0"),
                ("ff" * 32, "pdflane-atoms", "1.1.0")):
            self.assertEqual(
                bridge.content_document_id(checksum, engine, version),
                content_document_id(checksum, engine, version))

    def test_uuid5_layout_bits(self):
        import uuid
        u = uuid.UUID(bridge.content_document_id("ab" * 32, "pdflane-atoms",
                                                 "1.1.0"))
        self.assertEqual(u.version, 5)
        self.assertEqual(u.variant, uuid.RFC_4122)

    def test_different_engines_never_collide(self):
        a = bridge.content_document_id("ab" * 32, "pdflane-atoms", "1.1.0")
        b = bridge.content_document_id("ab" * 32, "glm-ocr-markdown", "1.2.0")
        self.assertNotEqual(a, b)


class ValidatorMirror(unittest.TestCase):
    def test_clean_doc_passes(self):
        self.assertEqual(bridge.validate_canonical(base_doc()), [])

    def test_duplicate_element_id_rejected(self):
        doc = base_doc()
        doc["textBlocks"].append(text_block("second"))
        v = bridge.validate_canonical(doc)
        self.assertTrue(any("duplicate element_id" in x for x in v))

    def test_page_out_of_range_rejected(self):
        doc = base_doc()
        doc["textBlocks"][0]["page_number"] = 9
        v = bridge.validate_canonical(doc)
        self.assertTrue(any("outside 1.." in x for x in v))

    def test_document_id_drift_rejected(self):
        doc = base_doc(documentId="00000000-0000-5000-8000-000000000000")
        v = bridge.validate_canonical(doc)
        self.assertTrue(any("derivation drift" in x for x in v))

    def test_dangling_section_ref_rejected(self):
        doc = base_doc()
        doc["sections"][0]["elementIds"].append("e999999")
        v = bridge.validate_canonical(doc)
        self.assertTrue(any("unknown element" in x for x in v))

    def test_null_text_allowed(self):
        doc = base_doc()
        doc["textBlocks"][0]["text"] = None
        self.assertEqual(bridge.validate_canonical(doc), [])


class ChunkSimulation(unittest.TestCase):
    def test_packing_respects_target_and_order(self):
        doc = base_doc()
        doc["textBlocks"] = []
        texts = [("a" * 800, 1), ("b" * 800, 1), ("c" * 800, 2)]
        for i, (t, p) in enumerate(texts):
            el = text_block(t, p)
            el["element_id"] = f"e{i:06d}"
            el["reading_order"] = i
            doc["textBlocks"].append(el)
        chunks = bridge.simulate_chunks(doc, target=300, max_tokens=800)
        # each block is ~200 tokens; 300-token target packs at most one more
        # only while under target: 200+200=400 > 300 → one block per chunk
        self.assertEqual(len(chunks), 3)
        self.assertEqual([c["pageStart"] for c in chunks], [1, 1, 2])
        self.assertEqual(chunks[0]["tokenEstimate"], 200)

    def test_oversized_block_own_chunk(self):
        doc = base_doc()
        el = text_block("x" * 4000, 2)  # 1000 tokens > 800 max
        doc["textBlocks"] = [el]
        chunks = bridge.simulate_chunks(doc)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["tokenEstimate"], 1000)
        self.assertEqual(chunks[0]["pageStart"], 2)

    def test_figures_and_null_text_skipped(self):
        doc = base_doc()
        fig = {"element_id": "e000001", "element_type": "figure",
               "page_number": 1, "bounding_box": None, "text": "assets/x.png",
               "reading_order": 1, "confidence": 1.0, "format": "png",
               "source_name": "assets/x.png", "alt": "",
               "source_engine": bridge.ENGINE_NAME,
               "source_engine_version": bridge.ENGINE_VERSION}
        doc["figures"] = [fig]
        doc["textBlocks"][0]["text"] = None
        self.assertEqual(bridge.simulate_chunks(doc), [])

    def test_deterministic(self):
        doc = base_doc()
        doc["textBlocks"] = [text_block("same input", 1)]
        self.assertEqual(bridge.simulate_chunks(doc),
                         bridge.simulate_chunks(doc))


class PageAlignment(unittest.TestCase):
    def _aligner(self, md_text):
        lines = md_text.split("\n")
        per_line = []
        page = 1
        for line in lines:
            m = bridge.PAGE_MARK.match(line.strip())
            if m:
                page = int(m.group(1))
            per_line.append(page)
        return bridge._PageAligner(lines, per_line)

    def test_forward_cursor_never_looks_back(self):
        a = self._aligner("<!-- PAGE 1 -->\nDO NOT WRITE IN THIS AREA\n"
                          "<!-- PAGE 2 -->\nDO NOT WRITE IN THIS AREA\n"
                          "<!-- PAGE 3 -->\nunique tail text\n")
        self.assertEqual(a.block_page("DO NOT WRITE IN THIS AREA", 9), 1)
        self.assertEqual(a.block_page("DO NOT WRITE IN THIS AREA", 9), 2)
        self.assertEqual(a.block_page("unique tail text", 9), 3)

    def test_miss_falls_back_and_counts(self):
        a = self._aligner("<!-- PAGE 1 -->\nalpha\n")
        self.assertEqual(a.block_page("NOT PRESENT ANYWHERE", 7), 7)
        self.assertEqual(a.inherited, 1)
        self.assertEqual(a.aligned, 0)

    def test_bidirectional_containment(self):
        a = self._aligner("<!-- PAGE 1 -->\n1\tThis question is about nitrogen\n")
        page, found = a.question_page("This question is about nitrogen", 1)
        self.assertEqual((page, found), (1, True))


class LeakageGuard(unittest.TestCase):
    def test_correct_label_in_qp_rejected(self):
        doc = base_doc()
        doc["textBlocks"][0]["text"] = "choose one"
        doc["textBlocks"][0]["role"] = "choices"
        # simulate a leaked part-level correct field serialized into the doc
        doc["_leaked"] = {"correct": ["B"]}
        blob = json.dumps(doc)
        self.assertIn('"correct"', blob)
        # the guard operates on the SERIALIZED document — rebuild without the
        # private key and confirm clean; with the key, a serialized scan fails
        with self.assertRaises(ValueError):
            bridge.assert_no_leakage({**doc, "textBlocks": [
                {**doc["textBlocks"][0], "text": json.dumps({"correct": ["B"]})}]})

    def test_clean_qp_passes(self):
        doc = base_doc()
        doc["textBlocks"][0]["role"] = "choices"
        doc["textBlocks"][0]["text"] = "A chromatography\nB distillation"
        bridge.assert_no_leakage(doc)  # must not raise

    def test_ms_roles_in_qp_rejected(self):
        doc = base_doc()
        doc["textBlocks"][0]["role"] = "mark_point"
        with self.assertRaises(ValueError):
            bridge.assert_no_leakage(doc)


class SyntheticConversion(unittest.TestCase):
    """Full round-trip over a synthetic paper dir with all block types."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="atoms2canon-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        paper = os.path.join(self.tmp, "4CHX-1X")
        os.makedirs(os.path.join(paper, "parsed"))
        self.paper = paper
        qp_md = ("<!-- PAGE 1 -->\nfront matter\n"
                 "<!-- PAGE 2 -->\n1 This question is about metals.\n"
                 "A zinc\nB copper\n(a)\tState the melting point of zinc.\n"
                 "<!-- PAGE 3 -->\n2 This question is about gases.\n")
        atoms = {
            "schema": "syllabai.pastpaper.atoms/1.1",
            "source": {"qp": "qp.pdf", "ms": "ms.pdf"},
            "questionCount": 2, "totalMarks": 4, "marksVerified": True,
            "questions": [
                {"number": 1, "type": "open", "marks": 3, "commandWord": None,
                 "provenance": "pdf-parsed",
                 "stem": [{"type": "para", "md": "This question is about metals."},
                          {"type": "table", "md": "| Metal | Mp / C |\n|---|---|\n| zinc | 420 |"},
                          {"type": "image", "src": "assets/QP_p02_01.png",
                           "alt": "apparatus", "pages": [2],
                           "bbox": {"page": 2, "x0": 10.0, "y0": 20.0,
                                    "x1": 60.0, "y1": 80.0, "units": "pt"}}],
                 "parts": [{"id": "1a", "label": "a", "sub": None,
                            "type": "open", "marks": 1, "commandWord": None,
                            "prompt": [{"type": "para",
                                        "md": "State the melting point of zinc."},
                                       {"type": "answer_lines", "count": 2}],
                            "answerLines": {"count": 2}}],
                 "markScheme": {
                     "totals": {"printed": 3, "sum": 3, "verified": True},
                     "guidance": ["allow ecf"],
                     "points": [
                         {"id": "a", "part": "a", "sub": None, "marks": 1,
                          "md": "420 (C)", "allow": ["420 with unit"],
                          "reject": [], "ignore": [], "notes": [], "pages": [3]},
                         {"id": "b", "part": "b", "sub": None, "marks": 2,
                          "md": "description of alloying", "allow": [],
                          "reject": ["brittle"], "ignore": [],
                          "notes": ["M2 dep on M1"], "pages": [3]}]}},
                {"number": 2, "type": "mcq", "marks": 1, "commandWord": None,
                 "provenance": "pdf-parsed",
                 "stem": [{"type": "para", "md": "This question is about gases."}],
                 "choices": [{"label": "A", "md": "oxygen"},
                             {"label": "B", "md": "nitrogen"}],
                 "parts": [],
                 "markScheme": {"totals": {"printed": 1, "sum": 1,
                                           "verified": True},
                                "guidance": [],
                                "points": [{"id": "a", "part": None, "sub": None,
                                            "marks": 1, "md": "B nitrogen",
                                            "allow": [], "reject": [],
                                            "ignore": [], "notes": [],
                                            "pages": [3]}]}},
            ],
        }
        with open(os.path.join(paper, "parsed", "questions.json"), "w") as f:
            json.dump(atoms, f)
        with open(os.path.join(paper, "parsed", "qp.md"), "w") as f:
            f.write(qp_md)
        self.qp_pdf = os.path.join(paper, "qp.pdf")
        self.ms_pdf = os.path.join(paper, "ms.pdf")
        for p in (self.qp_pdf, self.ms_pdf):
            with open(p, "wb") as f:
                f.write(b"%PDF-1.4 synthetic")
        # manifest with the older doubled-printed quirk (normalization path)
        with open(os.path.join(paper, "manifest.yaml"), "w") as f:
            f.write("paper_id: pearson-edexcel:international-gcse:chemistry:"
                    "4chx:2025-06:4CHX/1X\n"
                    "qualification:\n  family: international-gcse\n"
                    "  name: International GCSE\n"
                    "subject: chemistry\n"
                    "series:\n  normalized: 2025-06\n"
                    "  printed: June 2025; June 2025\n"
                    "paper:\n  official_reference: 4CHX/1X\n"
                    "  unit_code: 4CHX\n  paper_number_variant: 1X\n")
        self.expected_header = ("International GCSE Chemistry 4CHX | "
                                "June 2025 | Paper 1X")

    def test_round_trip(self):
        summary = bridge.convert_paper(self.paper, os.path.join(self.tmp, "out"))
        with open(os.path.join(self.tmp, "out", "qp.canonical.json")) as f:
            qp_doc = json.load(f)
        with open(os.path.join(self.tmp, "out", "ms.canonical.json")) as f:
            ms_doc = json.load(f)

        # identity from the real PDF bytes
        self.assertEqual(qp_doc["source"]["checksum"],
                         bridge.sha256_file(self.qp_pdf))
        self.assertEqual(qp_doc["documentId"],
                         content_document_id(qp_doc["source"]["checksum"],
                                             bridge.ENGINE_NAME,
                                             bridge.ENGINE_VERSION))
        self.assertEqual(qp_doc["source"]["mimeType"], "application/pdf")

        # structure: every element family represented, sections per question
        self.assertEqual(len(qp_doc["sections"]), 2)
        self.assertEqual(len(ms_doc["sections"]), 2)
        self.assertTrue(qp_doc["tables"])      # table block became a table element
        self.assertTrue(qp_doc["figures"])     # image block became a figure
        fig = qp_doc["figures"][0]
        self.assertEqual(fig["page_number"], 2)
        self.assertEqual(fig["bounding_box"]["width"], 50.0)
        self.assertEqual(fig["bounding_box"]["unit"], "pt")
        self.assertEqual(fig["source_name"], "assets/QP_p02_01.png")

        # pages: q1 blocks on page 2 (marker-aligned), q2 opener on page 3
        q1_section = qp_doc["sections"][0]
        pages = {e["element_id"]: e["page_number"] for e in qp_doc["textBlocks"]}
        for eid in q1_section["elementIds"]:
            el_pages = pages.get(eid)
            if el_pages is not None:
                self.assertGreaterEqual(el_pages, 2)
        answer_lines = [e for e in qp_doc["textBlocks"]
                        if e["role"] == "answer_lines"]
        self.assertEqual(len(answer_lines), 1)
        self.assertIsNone(answer_lines[0]["text"])

        # v1.2.0: structured retrieval identity — doc-level retrieval block on
        # both documents + group_key on every element (the 1.1.1 text-prefix
        # header is superseded; core stamps per-chunk headers from metadata)
        self.assertEqual(qp_doc["retrieval"], {
            "subjectTitle": "International GCSE Chemistry",
            "subjectCode": "4CHX",
            "series": "JUN", "year": 2025,
            "paperCode": "4CHX/1X", "label": "Paper 1X",
            "unit": None, "specCodes": None,
        })
        self.assertEqual(ms_doc["retrieval"], qp_doc["retrieval"])
        all_els = (qp_doc["textBlocks"] + qp_doc["tables"] + qp_doc["figures"])
        self.assertTrue(all_els)
        for e in all_els:
            self.assertRegex(e["group_key"], r"^q\d+$", e["element_id"])
        ms_els = (ms_doc["textBlocks"] + ms_doc["figures"])
        for e in ms_els:
            self.assertRegex(e["group_key"], r"^q\d+$", e["element_id"])
        q1_gk = {e["group_key"] for e in qp_doc["textBlocks"]
                 if e["element_id"] in set(qp_doc["sections"][0]["elementIds"])}
        self.assertEqual(q1_gk, {"q1"})
        # no text-prefix headers on the content anymore
        for e in qp_doc["textBlocks"]:
            if e["text"]:
                self.assertFalse(e["text"].startswith("[International GCSE"),
                                 e["text"][:60])
        ep = json.load(open(os.path.join(
            self.tmp, "out", "paper_summary.json")))
        self.assertNotIn("retrievalHeaders",
                         ep["qp"]["extractionParams"])
        self.assertIn("furnitureExcluded", ep["qp"]["extractionParams"])

        # mcq choices rendered (question-level) with no correct labels
        q2_ids = set(qp_doc["sections"][1]["elementIds"])
        q2_texts = [e["text"] for e in qp_doc["textBlocks"]
                    if e["element_id"] in q2_ids]
        self.assertTrue(any("B nitrogen" in t for t in q2_texts))
        blob = json.dumps(qp_doc)
        self.assertNotIn('"correct"', blob)
        self.assertNotIn("mark_point", blob)

        # MS: connected points with allow/reject/notes, real pages
        pt_texts = [e["text"] for e in ms_doc["textBlocks"]
                    if e["role"] == "mark_point"]
        self.assertTrue(any("420 (C)" in t and "allow: 420 with unit" in t
                            for t in pt_texts))
        self.assertTrue(any("reject: brittle" in t and "note: M2 dep on M1" in t
                            for t in pt_texts))
        ms_pages = {e["text"]: e["page_number"] for e in ms_doc["textBlocks"]
                    if e["role"] == "mark_point"}
        for t, p in ms_pages.items():
            self.assertEqual(p, 3)
        self.assertEqual(ms_doc["pageCount"], 3)
        self.assertEqual(summary["qp"]["sections"], 2)
        self.assertGreater(summary["qp"]["chunks"], 0)
        self.assertGreater(summary["ms"]["chunks"], 0)

    def test_manifest_checksum_mismatch_refuses(self):
        with open(os.path.join(self.paper, "manifest.yaml"), "w") as f:
            f.write("materials:\n- type: question-paper\n  path: qp.pdf\n"
                    "  sha256: %s\n" % ("9a" * 32))
        with self.assertRaises(ValueError) as ctx:
            bridge.convert_paper(self.paper, os.path.join(self.tmp, "out2"))
        self.assertIn("refusing to mint identity", str(ctx.exception))

    def test_deterministic_output(self):
        out1 = os.path.join(self.tmp, "d1")
        out2 = os.path.join(self.tmp, "d2")
        bridge.convert_paper(self.paper, out1)
        bridge.convert_paper(self.paper, out2)
        for name in ("qp.canonical.json", "ms.canonical.json"):
            with open(os.path.join(out1, name)) as f1, \
                    open(os.path.join(out2, name)) as f2:
                self.assertEqual(f1.read(), f2.read(), name)


class ManifestIdentity(unittest.TestCase):
    def _write(self, tmp, content):
        import tempfile
        d = tempfile.mkdtemp(prefix="manifest-ident-", dir=tmp)
        with open(os.path.join(d, "manifest.yaml"), "w") as f:
            f.write(content)
        return d

    def test_real_shape_with_doubled_printed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, (
                "paper_id: pearson-edexcel:international-gcse:chemistry:"
                "4ch0:2011-06:4CH0/1C\n"
                "exam_board:\n  id: pearson-edexcel\n"
                "qualification:\n  family: international-gcse\n"
                "  name: International GCSE\n"
                "subject: chemistry\n"
                "specification:\n  folder: 4ch0\n"
                "series:\n  normalized: 2011-06\n  year: '2011'\n"
                "  printed: June 2011; June 2011\n"
                "paper:\n  official_reference: 4CH0/1C\n"
                "  unit_code: 4CH0\n  paper_number_variant: 1C\n"))
            self.assertEqual(bridge.load_manifest_identity(d),
                             "International GCSE Chemistry 4CH0 | June 2011 | Paper 1C")

    def test_falls_back_to_paper_id(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(tmp, "paper_id: pearson-edexcel:ial:physics:"
                                 "wph1:2019-01:WPH1/1\n")
            self.assertEqual(bridge.load_manifest_identity(d),
                             "Ial Physics WPH1 | 2019-01 | Paper 1")

    def test_missing_manifest_empty_header(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = tempfile.mkdtemp(prefix="empty-", dir=tmp)
            self.assertEqual(bridge.load_manifest_identity(d), "")


class CorpusSmoke(unittest.TestCase):
    # pdflane → tools → syllabai-parser → repos → <project root>
    CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                          "repos", "syllabai-pastpapers", "past-papers",
                          "pearson-edexcel", "international-gcse", "chemistry")

    def test_all_products_convert_and_validate(self):
        corpus = os.path.abspath(self.CORPUS)
        if not os.path.isdir(corpus):
            self.skipTest("chemistry corpus not present in sandbox layout")
        products = bridge.find_products(corpus)
        self.assertGreaterEqual(len(products), 10)
        for paper_dir in products:
            with self.subTest(paper=os.path.basename(paper_dir)):
                atoms = bridge.load_atoms(paper_dir)
                qp_doc = bridge.build_qp_document(paper_dir, atoms=atoms)
                ms_doc = bridge.build_ms_document(paper_dir, atoms=atoms)
                bridge.assert_no_leakage(qp_doc)
                self.assertEqual(bridge.validate_canonical(qp_doc), [],
                                 "QP validation")
                self.assertEqual(bridge.validate_canonical(ms_doc), [],
                                 "MS validation")
                self.assertEqual(len(qp_doc["sections"]),
                                 atoms["questionCount"])
                self.assertEqual(len(ms_doc["sections"]),
                                 atoms["questionCount"])
                # QP chunk count sane and every chunk within page bounds
                for ch in bridge.simulate_chunks(qp_doc):
                    self.assertGreaterEqual(ch["pageStart"], 1)
                    self.assertLessEqual(ch["pageEnd"], qp_doc["pageCount"])


class RetrievalMetaTests(unittest.TestCase):
    """v1.2.0: doc-level retrieval block derivation (core RetrievalMeta parity)."""

    def _paper(self, manifest):
        import tempfile
        d = tempfile.mkdtemp(prefix="retr-meta-")
        if manifest is not None:
            with open(os.path.join(d, "manifest.yaml"), "w") as f:
                f.write(manifest)
        return d

    BASE = ("paper_id: pearson-edexcel:international-gcse:chemistry:"
            "4ch1:2024-06:4CH1/1C\n"
            "qualification:\n  family: international-gcse\n"
            "  name: International GCSE\n"
            "subject: chemistry\n"
            "series:\n  normalized: 2024-06\n"
            "  printed: June 2024\n"
            "paper:\n  official_reference: 4CH1/1C\n"
            "  unit_code: 4CH1\n  paper_number_variant: 1C\n")

    def test_full_manifest_fields(self):
        meta = bridge.load_retrieval_meta(self._paper(self.BASE))
        self.assertEqual(meta, {
            "subjectTitle": "International GCSE Chemistry",
            "subjectCode": "4CH1", "series": "JUN", "year": 2024,
            "paperCode": "4CH1/1C", "label": "Paper 1C",
            "unit": None, "specCodes": None,
        })

    def test_series_canonicalization(self):
        cases = {
            "January 2012": ("JAN", 2012),
            "November 2020": ("NOV", 2020),
            "Summer 2022": ("JUN", 2022),     # validator rule: Summer→JUN
            "June 2011; June 2011": ("JUN", 2011),  # doubled-printed quirk
            "2019-01": ("JAN", 2019),          # numeric normalized form
        }
        for printed, (series, year) in cases.items():
            m = self._paper(self.BASE.replace(
                "  printed: June 2024", f"  printed: {printed}"))
            meta = bridge.load_retrieval_meta(m)
            self.assertEqual((meta["series"], meta["year"]), (series, year),
                             printed)

    def test_unrecognized_series_stays_null_never_a_raw_label(self):
        m = self._paper(self.BASE.replace(
            "  printed: June 2024", "  printed: Autumn 2018").replace(
            "  normalized: 2024-06", "  normalized: 2018-10"))
        meta = bridge.load_retrieval_meta(m)
        self.assertIsNone(meta["series"])     # honest null, not a raw label
        self.assertEqual(meta["year"], 2018)  # year still derivable

    def test_subject_code_alias_4ch0_to_4ch1(self):
        m = self.BASE.replace("4CH1/1C", "4CH0/1C").replace(
            "  unit_code: 4CH1", "  unit_code: 4CH0")
        meta = bridge.load_retrieval_meta(self._paper(m))
        self.assertEqual(meta["subjectCode"], "4CH1")  # pilot subject register
        self.assertEqual(meta["paperCode"], "4CH0/1C")  # paper keeps vintage

    def test_missing_manifest_is_legacy_tolerant(self):
        self.assertIsNone(bridge.load_retrieval_meta(self._paper(None)))

    def test_validator_mirror_rejects_raw_series_and_bad_year(self):
        doc = dict(base_doc(), retrieval={"series": "Summer 2019"})
        problems = bridge.validate_canonical(doc)
        self.assertTrue(any("retrieval.series" in p for p in problems))
        doc = dict(base_doc(), retrieval={"series": "JUN", "year": 1804})
        problems = bridge.validate_canonical(doc)
        self.assertTrue(any("retrieval.year" in p for p in problems))
        doc = dict(base_doc(), retrieval={"series": "JUN", "year": 2024})
        self.assertEqual(bridge.validate_canonical(doc), [])


class GroupKeyBoundaryTests(unittest.TestCase):
    """v1.2.0: per-element group_key + hard atom boundaries in the chunk preview."""

    def test_no_chunk_crosses_two_atoms(self):
        doc = base_doc()
        doc["textBlocks"] = [
            dict(text_block("q1 stem text one"), group_key="q1"),
            dict(text_block("q1 part prompt text"), group_key="q1"),
            dict(text_block("q2 stem text two"), group_key="q2"),
        ]
        chunks = bridge.simulate_chunks(doc)
        self.assertGreaterEqual(len(chunks), 2)
        gk = {e["element_id"]: e.get("group_key") for e in doc["textBlocks"]}
        for ch in chunks:
            groups = {gk[e] for e in ch["elementIds"]}
            self.assertEqual(len(groups), 1, ch["elementIds"])

    def test_legacy_blocks_without_group_key_never_boundary(self):
        doc = base_doc()
        doc["textBlocks"] = [text_block("legacy a"), text_block("legacy b")]
        chunks = bridge.simulate_chunks(doc)
        self.assertEqual(len(chunks), 1)  # legacy shape packs as before


class FurnitureRenderTests(unittest.TestCase):
    """G3: render-level furniture exclusion — product files never touched."""

    def setUp(self):
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp(prefix="furniture-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        paper = os.path.join(self.tmp, "4CHX-1X")
        os.makedirs(os.path.join(paper, "parsed"))
        self.paper = paper
        self.atoms = {
            "schema": "syllabai.pastpaper.atoms/1.1",
            "source": {"qp": "qp.pdf", "ms": "ms.pdf"},
            "questionCount": 1, "totalMarks": 2, "marksVerified": True,
            "questions": [{
                "number": 1, "type": "open", "marks": 2, "commandWord": None,
                "provenance": "pdf-parsed",
                "stem": [
                    {"type": "para", "md": "DO NOT WRITE IN THIS AREA"},
                    {"type": "para", "md": "Answer ALL questions."},
                    {"type": "para", "md":
                     "Some questions must be answered with a cross in a box . "
                     "If you change your mind, put a line through the box ."},
                    {"type": "para", "md": "Total for Question 1 = 2 marks"},
                    {"type": "para", "md":
                     "This paragraph mentions DO NOT WRITE IN THIS AREA mid-"
                     "sentence and must survive column-bleed gluing."},
                ],
                "parts": [],
                "markScheme": {"totals": {"printed": 2, "sum": 2,
                                          "verified": True},
                               "guidance": [],
                               "points": [{"id": "a", "part": None, "sub": None,
                                           "marks": 2, "md": "answer",
                                           "allow": [], "reject": [],
                                           "ignore": [], "notes": [],
                                           "pages": [1]}]},
            }],
        }
        with open(os.path.join(paper, "parsed", "questions.json"), "w") as f:
            json.dump(self.atoms, f)
        with open(os.path.join(paper, "parsed", "qp.md"), "w") as f:
            f.write("<!-- PAGE 1 -->\n1 boilerplate paper\n")
        for name in ("qp.pdf", "ms.pdf"):
            with open(os.path.join(paper, name), "wb") as f:
                f.write(b"%PDF-1.4 synthetic")
        with open(os.path.join(paper, "manifest.yaml"), "w") as f:
            f.write(self_paper_manifest())

    def test_boilerplate_excluded_counted_and_content_survives(self):
        out = os.path.join(self.tmp, "out")
        bridge.convert_paper(self.paper, out)
        qp = json.load(open(os.path.join(out, "qp.canonical.json")))
        texts = [e["text"] for e in qp["textBlocks"] if e["text"]]
        self.assertFalse(any(t == "DO NOT WRITE IN THIS AREA" for t in texts))
        self.assertFalse(any(t == "Answer ALL questions." for t in texts))
        self.assertFalse(any(t.startswith("Some questions must be answered")
                             for t in texts))
        self.assertFalse(any(t.startswith("Total for Question 1") for t in texts))
        self.assertTrue(any("mid-sentence" in t for t in texts),
                        "conservative matcher must not eat glued content")
        params = qp["provenance"]["extractionParams"]
        self.assertEqual(params["furnitureExcluded"], 3)
        self.assertEqual(params["furnitureTotalRowsExcluded"], 1)
        # excluded blocks never appear in the chunk preview either
        blob = json.dumps(json.load(open(os.path.join(out,
                                                      "chunks_preview.json"))))
        self.assertNotIn("Answer ALL questions", blob)

    def test_product_file_untouched(self):
        before = open(os.path.join(self.paper, "parsed", "questions.json"),
                      "rb").read()
        bridge.convert_paper(self.paper, os.path.join(self.tmp, "out"))
        after = open(os.path.join(self.paper, "parsed", "questions.json"),
                     "rb").read()
        self.assertEqual(before, after)

    def test_total_row_inside_real_table_is_content(self):
        doc = base_doc()
        doc["tables"] = [{
            "element_id": "e000001", "element_type": "table",
            "page_number": 1, "bounding_box": None,
            "text": "| Question | Marks |\n|---|---|\n| Total for Question 1 = 2 marks |",
            "reading_order": 0, "confidence": 1.0,
            "rows": [["Question", "Marks"]],
            "row_count": 1, "column_count": 2,
            "source_engine": bridge.ENGINE_NAME,
            "source_engine_version": bridge.ENGINE_VERSION,
        }]
        self.assertEqual(bridge.validate_canonical(doc), [])
        self.assertEqual(len(bridge.simulate_chunks(doc)), 1)


class FigureAltTextTests(unittest.TestCase):
    """G4: deterministic caption pull + [figure: alt] inline render blocks."""

    def test_existing_alt_is_kept_never_overwritten(self):
        el = bridge._Elements().add_figure("assets/q1.png", 1, "apparatus photo",
                                           group_key="q1")
        filled = bridge._resolve_figure_alt(
            el, [(0, "Figure 1 a caption")], order=1)
        self.assertEqual(filled, "apparatus photo")
        self.assertEqual(el["alt"], "apparatus photo")

    def test_no_caption_nothing_fabricated(self):
        el = bridge._Elements().add_figure("assets/q1.png", 1, "", group_key="q1")
        filled = bridge._resolve_figure_alt(
            el, [(0, "The student sets up the apparatus."),
                 (1, "Figure 1 rate of reaction graph")], order=2)
        self.assertEqual(filled, "Figure 1 rate of reaction graph")
        self.assertEqual(el["alt"], "Figure 1 rate of reaction graph")

    def test_nearest_caption_wins(self):
        el = bridge._Elements().add_figure("assets/q1.png", 1, "", group_key="q1")
        filled = bridge._resolve_figure_alt(
            el, [(0, "Figure 1 far away caption"), (1, "Graph 2 near caption")],
            order=2)
        self.assertEqual(filled, "Graph 2 near caption")

    def test_no_caption_nothing_fabricated(self):
        el = bridge._Elements().add_figure("assets/q1.png", 1, "", group_key="q1")
        filled = bridge._resolve_figure_alt(
            el, [(0, "plain text, not a caption")], order=1)
        self.assertEqual(filled, "")
        self.assertEqual(el["alt"], "")


def self_paper_manifest():
    return ("paper_id: pearson-edexcel:international-gcse:chemistry:"
            "4chx:2025-06:4CHX/1X\n"
            "qualification:\n  family: international-gcse\n"
            "  name: International GCSE\n"
            "subject: chemistry\n"
            "series:\n  normalized: 2025-06\n"
            "  printed: June 2025\n"
            "paper:\n  official_reference: 4CHX/1X\n"
            "  unit_code: 4CHX\n  paper_number_variant: 1X\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
