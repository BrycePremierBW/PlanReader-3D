from pathlib import Path

ocr_path = Path('pb_drawing_ocr_evidence_layer.py')
text = ocr_path.read_text(encoding='utf-8')
old = '''            except Exception:\n                pass\n\n        return []\n\n    def recognize_page_rect(\n'''
new = '''            except Exception:\n                pass\n\n        # 3. Portable RapidOCR fallback for non-Windows/server environments.\n        # The dependency is optional and initialized lazily; absence or backend\n        # failure emits no evidence rather than guessing.\n        try:\n            from pb_portable_raster_ocr import recognize_pil_with_rapidocr\n\n            raw_lines = recognize_pil_with_rapidocr(image)\n            if raw_lines:\n                out = []\n                for r in raw_lines:\n                    r_conf = float(r.get("confidence", 0.0)) * quality\n                    out.append({\n                        "text": r.get("text", ""),\n                        "bounding_box": r.get(\n                            "bounding_box",\n                            [0.0, 0.0, float(image.width), float(image.height)],\n                        ),\n                        "confidence": round(r_conf, 4),\n                    })\n                return out\n        except Exception:\n            pass\n\n        return []\n\n    def recognize_page_rect(\n'''
if old not in text:
    raise SystemExit('recognize_pil_image anchor not found')
text = text.replace(old, new, 1)

anchor = '''        except Exception:\n            return []\n\n\nclass DrawingEvidenceParser:\n'''
insert = '''        except Exception:\n            return []\n\n    def recognize_page_tiled(\n        self,\n        page: fitz.Page,\n        *,\n        dpi: int = 220,\n        columns: int = 3,\n        rows: int = 3,\n        overlap_fraction: float = 0.06,\n    ) -> List[Dict[str, Any]]:\n        """OCR a large raster drawing in overlapping tiles.\n\n        Large-format plans routinely make opening tags too small for a single\n        whole-page OCR pass. Tile overlap protects edge text; duplicate OCR\n        detections are removed spatially afterwards. All geometry is mapped\n        back into PDF point coordinates by ``recognize_page_rect``.\n        """\n        if columns <= 0 or rows <= 0 or dpi <= 0:\n            return []\n        try:\n            from pb_portable_raster_ocr import deduplicate_tiled_ocr_lines\n\n            rect = page.rect\n            tile_w = rect.width / columns\n            tile_h = rect.height / rows\n            overlap = max(0.0, min(0.25, float(overlap_fraction)))\n            lines: List[Dict[str, Any]] = []\n            for row_idx in range(rows):\n                for col_idx in range(columns):\n                    clip = fitz.Rect(\n                        max(rect.x0, rect.x0 + col_idx * tile_w - tile_w * overlap),\n                        max(rect.y0, rect.y0 + row_idx * tile_h - tile_h * overlap),\n                        min(rect.x1, rect.x0 + (col_idx + 1) * tile_w + tile_w * overlap),\n                        min(rect.y1, rect.y0 + (row_idx + 1) * tile_h + tile_h * overlap),\n                    )\n                    lines.extend(self.recognize_page_rect(page, clip_rect=clip, dpi=dpi))\n            return deduplicate_tiled_ocr_lines(lines)\n        except Exception:\n            return []\n\n\nclass DrawingEvidenceParser:\n'''
if anchor not in text:
    raise SystemExit('tiled method anchor not found')
text = text.replace(anchor, insert, 1)
ocr_path.write_text(text, encoding='utf-8')

ext_path = Path('pb_planreader_pdf_extractor.py')
text = ext_path.read_text(encoding='utf-8')
old_import = '''                EvidenceReconciler,\n                EvidenceStatus,\n            )\n\n            ocr_engine = DrawingOCREngine()\n            dwg_pages = [p for p in target_pages if 0 <= p < len(doc) and self.is_drawing_page(doc[p].get_text("text"))]\n\n            for p_num in dwg_pages:\n'''
new_import = '''                EvidenceReconciler,\n                EvidenceStatus,\n            )\n            from pb_portable_raster_ocr import (\n                extract_opening_instance_evidence,\n                resolve_cross_page_opening_instances,\n            )\n\n            ocr_engine = DrawingOCREngine()\n            dwg_pages = [p for p in target_pages if 0 <= p < len(doc) and self.is_drawing_page(doc[p].get_text("text"))]\n            raster_instance_evidence = []\n\n            for p_num in dwg_pages:\n'''
if old_import not in text:
    raise SystemExit('extractor import anchor not found')
text = text.replace(old_import, new_import, 1)

old_trigger = '''                is_scanned_or_raster = len(p_text.strip()) < 150\n                has_schedule_word = any(\n'''
new_trigger = '''                is_scanned_or_raster = len(p_text.strip()) < 150\n                has_embedded_raster = bool(page.get_images(full=True))\n                has_raster_opening_candidate = has_embedded_raster and not has_complete_native_openings\n                has_schedule_word = any(\n'''
if old_trigger not in text:
    raise SystemExit('raster trigger anchor not found')
text = text.replace(old_trigger, new_trigger, 1)

old_native = '''                native_insufficient = is_scanned_or_raster or (\n                    (has_schedule_word or has_opening_keyword) and not has_complete_native_openings\n                )\n'''
new_native = '''                native_insufficient = is_scanned_or_raster or has_raster_opening_candidate or (\n                    (has_schedule_word or has_opening_keyword) and not has_complete_native_openings\n                )\n'''
if old_native not in text:
    raise SystemExit('native_insufficient anchor not found')
text = text.replace(old_native, new_native, 1)

old_call = '''                ocr_lines = ocr_engine.recognize_page_rect(page, dpi=150)\n                ocr_records: List[DrawingEvidenceRecord] = []\n'''
new_call = '''                if has_embedded_raster:\n                    ocr_lines = ocr_engine.recognize_page_tiled(page, dpi=220)\n                else:\n                    ocr_lines = ocr_engine.recognize_page_rect(page, dpi=150)\n\n                raster_instance_evidence.extend(\n                    extract_opening_instance_evidence(\n                        ocr_lines,\n                        source_page=p_num + 1,\n                    )\n                )\n\n                ocr_records: List[DrawingEvidenceRecord] = []\n'''
if old_call not in text:
    raise SystemExit('ocr call anchor not found')
text = text.replace(old_call, new_call, 1)

end_anchor = '''                        elif r.status == EvidenceStatus.CONFLICT_MANUAL_REVIEW.value:\n                            if r.tag in pred_dict:\n                                del pred_dict[r.tag]\n        except Exception:\n            pass\n\n        # ------------------------------------------------------------------\n        # Generic Opening Deduction Pipeline (Phase F.9)\n'''
end_insert = '''                        elif r.status == EvidenceStatus.CONFLICT_MANUAL_REVIEW.value:\n                            if r.tag in pred_dict:\n                                del pred_dict[r.tag]\n\n            # Explicit raster tag placements are a separate lower-authority\n            # quantity source. Never sum across pages/views: repeated pages must\n            # agree. Existing native/schedule predictions retain authority.\n            for inst in resolve_cross_page_opening_instances(raster_instance_evidence):\n                if inst.tag in pred_dict:\n                    continue\n                boxes = list(inst.bounding_boxes)\n                bbox = None\n                if boxes:\n                    bbox = [\n                        min(b[0] for b in boxes),\n                        min(b[1] for b in boxes),\n                        max(b[2] for b in boxes),\n                        max(b[3] for b in boxes),\n                    ]\n                pred_dict[inst.tag] = ExtractedPrediction(\n                    tag=inst.tag,\n                    trade_type=inst.trade_type,\n                    description=f"{inst.tag} explicit raster tagged opening placements",\n                    quantity=float(inst.quantity),\n                    unit="NO",\n                    confidence=min(float(inst.confidence), 0.86),\n                    source_page=inst.source_page,\n                    bounding_box=bbox,\n                    metadata={\n                        "derivation": "raster_explicit_opening_instance_count",\n                        "extraction_method": EvidenceMethod.RASTER_OCR.value,\n                        "status": EvidenceStatus.CONFIRMED.value,\n                    },\n                )\n        except Exception:\n            pass\n\n        # ------------------------------------------------------------------\n        # Generic Opening Deduction Pipeline (Phase F.9)\n'''
if end_anchor not in text:
    raise SystemExit('OCR end anchor not found')
text = text.replace(end_anchor, end_insert, 1)
ext_path.write_text(text, encoding='utf-8')

print('F25 production wiring applied')
