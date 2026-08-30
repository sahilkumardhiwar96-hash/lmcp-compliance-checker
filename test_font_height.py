import font_height as fh


def test_measure_height_mm_basic():
    # 100px tall text, calibration ref: 50px = 5mm -> 10px/mm -> 10mm
    assert fh.measure_height_mm(100, 50, 5) == 10.0


def test_measure_height_mm_missing_calibration():
    assert fh.measure_height_mm(100, None, None) is None
    assert fh.measure_height_mm(100, 0, 5) is None
    assert fh.measure_height_mm(100, 50, 0) is None
    assert fh.measure_height_mm(0, 50, 5) is None


def test_required_height_mm_grams_bands():
    assert fh.required_height_mm("30 g")["required_mm"] == 1.0
    assert fh.required_height_mm("150g")["required_mm"] == 2.0
    assert fh.required_height_mm("500 g")["required_mm"] == 4.0
    assert fh.required_height_mm("1 kg")["required_mm"] == 6.0


def test_required_height_mm_ml_and_litre():
    assert fh.required_height_mm("100 ml")["required_mm"] == 2.0
    assert fh.required_height_mm("1 L")["required_mm"] == 6.0
    assert fh.required_height_mm("1.5 litre")["required_mm"] == 6.0


def test_required_height_mm_unparseable_falls_back_none():
    assert fh.required_height_mm("10 pieces") is None
    assert fh.required_height_mm("") is None
    assert fh.required_height_mm(None) is None


def test_get_word_boxes_empty_without_tesseract(monkeypatch):
    monkeypatch.setattr(fh, "_TESSERACT_OK", False)
    assert fh.get_word_boxes(None) == []
