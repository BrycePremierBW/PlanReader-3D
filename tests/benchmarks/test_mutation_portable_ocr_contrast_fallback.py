from __future__ import annotations

from PIL import Image

import pb_portable_raster_ocr
from pb_drawing_ocr_evidence_layer import DrawingOCREngine


def test_portable_backend_combines_raw_and_contrast_and_spatially_deduplicates(monkeypatch) -> None:
    calls = []

    def fake_rapidocr(image):
        calls.append(image)
        if len(calls) == 1:
            return [
                {"text": "W-1", "bounding_box": [10, 10, 30, 22], "confidence": 0.95},
            ]
        return [
            # Same physical mark: must not be counted twice across variants.
            {"text": "W-1", "bounding_box": [10.5, 10, 30.5, 22], "confidence": 0.97},
            # Contrast recovers a second physical mark.
            {"text": "W-1", "bounding_box": [80, 10, 100, 22], "confidence": 0.91},
        ]

    monkeypatch.setattr(pb_portable_raster_ocr, "recognize_pil_with_rapidocr", fake_rapidocr)
    engine = DrawingOCREngine()
    monkeypatch.setattr(engine, "evaluate_image_quality", lambda image: 1.0)

    lines = engine.recognize_pil_image(Image.new("RGB", (140, 60), "white"))

    assert len(calls) == 2
    assert len(lines) == 2
    assert [line["text"] for line in lines] == ["W-1", "W-1"]
    assert sorted(round(line["confidence"], 2) for line in lines) == [0.91, 0.97]
