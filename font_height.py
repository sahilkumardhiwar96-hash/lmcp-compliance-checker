# -*- coding: utf-8 -*-
"""
Rule 7 numeral/letter height verification.

Legal Metrology (Packaged Commodities) Rules, 2011, Rule 7 read with Table-I
prescribes a MINIMUM physical height (in mm) for numerals/letters used in the
mandatory declarations, scaled to the net quantity of the package. An AI's
opinion of "does this look legible" is not physical evidence of that height.
This module measures it instead:

  1. Run local Tesseract OCR on the uploaded image to get real pixel
     bounding boxes for each recognized word/number (independent of Gemini).
  2. Let the inspector pick which OCR box is the declaration they want to
     verify (e.g. the printed net-quantity or MRP numerals).
  3. Let the inspector supply a calibration reference: the pixel length of
     something in the SAME photo whose real-world length (mm) is known
     (a ruler laid next to the pack, a coin, the package's own printed
     dimension, etc). This converts pixels -> mm for THIS photo only.
  4. Convert the selected box's pixel height to mm and compare against the
     Table-I threshold for the product's declared net quantity.

Without a calibration reference, physical height cannot be measured from a
photo at all (a phone photo carries no reliable absolute scale) — in that
case this module returns None and the caller should fall back to noting the
check as unverified, not silently pass/fail it.
"""

import re
from dataclasses import dataclass, asdict
from typing import List, Optional

try:
    import pytesseract
    from pytesseract import Output
    _TESSERACT_OK = True
except Exception:
    pytesseract = None
    Output = None
    _TESSERACT_OK = False


@dataclass
class OCRWordBox:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int

    def to_dict(self):
        return asdict(self)


def tesseract_available():
    if not _TESSERACT_OK:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def get_word_boxes(pil_image, min_confidence=40) -> List[OCRWordBox]:
    """Run local Tesseract OCR and return per-word bounding boxes with
    real confidences. Independent of the Gemini extraction path."""
    if not _TESSERACT_OK:
        return []
    data = pytesseract.image_to_data(pil_image, output_type=Output.DICT)
    boxes = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf < min_confidence:
            continue
        boxes.append(OCRWordBox(
            text=text,
            confidence=conf,
            left=int(data["left"][i]),
            top=int(data["top"][i]),
            width=int(data["width"][i]),
            height=int(data["height"][i]),
        ))
    return boxes


def measure_height_mm(pixel_height, reference_pixels, reference_mm):
    """Convert a pixel height to mm using a calibration reference measured
    in the SAME photo. Returns None if calibration is invalid/missing."""
    if not pixel_height or not reference_pixels or not reference_mm:
        return None
    if reference_pixels <= 0 or reference_mm <= 0:
        return None
    pixels_per_mm = float(reference_pixels) / float(reference_mm)
    if pixels_per_mm <= 0:
        return None
    return round(float(pixel_height) / pixels_per_mm, 2)


# ---------------------------------------------------------------------------
# Rule 7, Table-I — minimum numeral height by net quantity (weight/volume).
# NOTE: these bands mirror the commonly cited post-2017-amendment Table-I
# ranges. Exact statutory wording should be verified against the current
# gazetted text before use in real enforcement — see legal caution below.
# ---------------------------------------------------------------------------
_TABLE_I_BANDS_G = [
    (50, 1.0),
    (200, 2.0),
    (500, 4.0),
    (float("inf"), 6.0),
]


def required_height_mm(net_quantity_text: str) -> Optional[dict]:
    """Parse a net-quantity string like '500 g', '1 kg', '200 ml', '1.5 L'
    and return the Rule 7 Table-I minimum numeral height in mm, normalized
    to grams/millilitres. Returns None if the value/unit can't be parsed
    (e.g. count-based items like '10 pieces', which fall under Table-II,
    a different table this module does not encode)."""
    if not net_quantity_text:
        return None
    match = re.search(r"([\d.]+)\s*(kg|g|gm|gms|l|litre|liter|ml)\b", net_quantity_text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "kg":
        grams = value * 1000
    elif unit in ("l", "litre", "liter"):
        grams = value * 1000  # 1 L ~ 1000 ml, same numeric band
    else:
        grams = value
    for threshold, mm in _TABLE_I_BANDS_G:
        if grams <= threshold:
            return {"required_mm": mm, "normalized_g_or_ml": grams, "unit_basis": unit}
    return None


LEGAL_CAUTION = (
    "Rule 7 Table-I thresholds used here should be checked against the exact "
    "current gazetted text before any real enforcement decision. Table-II "
    "(length/area/number-based declarations) is not covered by this "
    "automated check and requires manual verification."
)
