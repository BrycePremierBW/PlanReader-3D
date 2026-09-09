from pathlib import Path

path = Path('pb_planreader_pdf_extractor.py')
text = path.read_text(encoding='utf-8')
old = '''            from pb_portable_raster_ocr import (\n                extract_opening_instance_evidence,\n                resolve_cross_page_opening_instances,\n            )\n\n            ocr_engine = DrawingOCREngine()\n            dwg_pages = [p for p in target_pages if 0 <= p < len(doc) and self.is_drawing_page(doc[p].get_text("text"))]\n            raster_instance_evidence = []\n'''
new = '''            from pb_portable_raster_ocr import (\n                extract_opening_instance_evidence,\n                resolve_cross_page_opening_instances,\n            )\n            from pb_raster_page_classifier import is_sparse_raster_ocr_candidate\n\n            ocr_engine = DrawingOCREngine()\n            dwg_pages = []\n            for p_num in target_pages:\n                if p_num < 0 or p_num >= len(doc):\n                    continue\n                candidate_page = doc[p_num]\n                candidate_text = candidate_page.get_text("text") or ""\n                if self.is_drawing_page(candidate_text) or is_sparse_raster_ocr_candidate(\n                    candidate_page, candidate_text\n                ):\n                    dwg_pages.append(p_num)\n            raster_instance_evidence = []\n'''
if old not in text:
    raise SystemExit('OCR page-selection anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('F25 raster page classifier wiring applied')
