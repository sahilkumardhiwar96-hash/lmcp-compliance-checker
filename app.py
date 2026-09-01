import streamlit as st
import json
import io
from datetime import datetime
from collections import Counter
import pandas as pd
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from streamlit_js_eval import get_geolocation
from PIL import Image

import db
import rules_manager
import font_height as fh
from pdf_report import generate_pdf_report
from report_export import generate_csv_report, generate_docx_report

st.set_page_config(page_title="Legal Metrology Compliance Checker", page_icon="⚖️", layout="wide")
db.init_db()

# =====================================================================
# THEME — Government portal style: light background, navy header,
# tricolor accent strip, high-contrast text (GIGW-style accessibility)
# =====================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Noto Sans', sans-serif; color: #1a1a1a; }

.stApp { background: #f4f6f8; }

@keyframes fadeSlideIn {
    0% { opacity: 0; transform: translateY(-14px); }
    100% { opacity: 1; transform: translateY(0); }
}
@keyframes fadeIn { 0% { opacity: 0; } 100% { opacity: 1; } }

.tricolor {
    height: 6px; width: 100%; border-radius: 3px; margin-bottom: 0;
    background: linear-gradient(90deg, #FF9933 0%, #FF9933 33%, #FFFFFF 33%, #FFFFFF 66%, #138808 66%, #138808 100%);
    animation: fadeSlideIn 0.5s ease-out;
}

.hero {
    animation: fadeSlideIn 0.6s ease-out;
    background: linear-gradient(120deg, #0b3d66 0%, #14528a 100%);
    border-radius: 0 0 14px 14px;
    padding: 26px 34px;
    margin-bottom: 26px;
    box-shadow: 0 4px 18px rgba(11,61,102,0.25);
}
.hero h1 { color: #ffffff; font-size: 1.9rem; font-weight: 700; margin: 0; }
.hero p { color: #dceaf7; font-size: 0.98rem; margin-top: 6px; }
.hero .icon {
    font-size: 2.2rem; margin-right: 12px; vertical-align: middle;
    background: #FF9933; padding: 8px 12px; border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}

.card {
    animation: fadeIn 0.5s ease-in;
    background: #ffffff;
    border: 1px solid #e0e4e8;
    border-radius: 12px;
    padding: 20px 22px;
    margin-bottom: 16px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.04);
}
.card h3 { color: #0b3d66; margin-top: 0; }

.badge-found {
    display: flex; align-items: flex-start; gap: 10px;
    background: #e9f7ec; border-left: 4px solid #1e8e3e;
    border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;
    color: #1a1a1a; animation: fadeIn 0.4s ease-in;
}
.badge-missing {
    display: flex; align-items: flex-start; gap: 10px;
    background: #fdecea; border-left: 4px solid #d93025;
    border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;
    color: #1a1a1a; animation: fadeIn 0.4s ease-in;
}
.badge-icon { font-size: 1.2rem; }
.badge-text b { color: #0b3d66; }
.badge-sub { font-size: 0.78rem; color: #555; display: block; margin-top: 2px; }

.score-box {
    text-align: center; padding: 20px; border-radius: 14px;
    background: #ffffff; border: 1px solid #e0e4e8;
    box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    animation: fadeIn 0.5s ease-in;
}
.score-box .num { font-size: 2.6rem; font-weight: 700; }
.score-box .label { color: #555; font-size: 0.9rem; }

section[data-testid="stSidebar"] { background: #0b3d66; }
section[data-testid="stSidebar"] * { color: #ffffff !important; }
section[data-testid="stSidebar"] input { color: #1a1a1a !important; }

div.stButton > button, div.stDownloadButton > button {
    background: #0b3d66; color: white; border-radius: 8px; border: none;
    font-weight: 600; transition: 0.2s;
}
div.stButton > button:hover, div.stDownloadButton > button:hover {
    background: #14528a;
}
</style>
""", unsafe_allow_html=True)

# =====================================================================
# RULE ENGINE
# =====================================================================
RULE_ENGINE, RULE_NOTES = rules_manager.load_rules()
ASSESSMENT_FIELDS = ["font_legibility", "placement", "misleading"]  # AI relative-judgment fields (acceptable/notes shape), not simple extraction
REQUIRED_FIELDS = [r["field"] for r in RULE_ENGINE if r["field"] not in ASSESSMENT_FIELDS]
ASSESSMENT_RULES = {r["field"]: r for r in RULE_ENGINE if r["field"] in ASSESSMENT_FIELDS}
FIELD_LABELS = {r["field"]: r["label"] for r in RULE_ENGINE}
FIELD_LEGAL_REF = {r["field"]: r["legal_reference"] for r in RULE_ENGINE}

# =====================================================================
# GEMINI
# =====================================================================
# =====================================================================
# GEMINI
# =====================================================================
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    st.error("❌ Gemini API key is not configured. Please add GOOGLE_API_KEY in Streamlit Secrets.")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)

model = genai.GenerativeModel("gemini-3.6-flash")

EXTRACTION_PROMPT = """You are a Legal Metrology compliance inspector. Look at this packaged commodity label image and check for the following mandatory declarations required under the Legal Metrology (Packaged Commodities) Rules, 2011:

1. manufacturer_details - name and address of manufacturer/packer/importer
2. common_name - common or generic name of the commodity
3. net_quantity - net quantity in any standard/valid unit (weight, volume, count, or dimensions e.g. "1N strip (1.9cm x 7.2cm)")
4. mrp - Maximum Retail Price, inclusive of all taxes
5. mfg_date - month and year of manufacture, packing, or import
6. consumer_care - consumer care details (address, phone number, toll-free number, or email)

For each field, determine if it is present on the label. Read all text carefully, including text that is rotated, small, or on the edge of the packaging.

Additionally, assess three relative-judgment quality checks (Rule 7 prescribes minimum font/numeral height; Rule 9 requires declarations to appear together on the principal display panel; Rule 6(3) and Rule 18 prohibit altering, obliterating, or improperly stickering declarations, especially the retail price):

- font_legibility: Judge whether the mandatory declarations (especially net quantity and MRP) are printed in a reasonably sized, legible font relative to the package size. Flag if any declaration appears unusually tiny, low-contrast, blurry, or crammed compared to the rest of the label.
- placement: Judge whether the mandatory declarations are grouped together in a sensible, organized area (not scattered confusingly across different panels), and are prominently visible rather than hidden in a corner, wrapped around an edge illegibly, or overlapped/obscured by graphics or other text.
- misleading: Look for signs of improper alteration or conflicting information: (a) two or more different values printed for the same declaration (e.g. two different MRPs visible), (b) a sticker that appears to cover or obscure an original printed declaration rather than sit alongside it, (c) a declaration whose font, ink, or print quality visibly differs from the rest of the label in a way that suggests it was added or altered afterward. A single clean sticker placed next to (not over) the original MRP for a lawful price reduction is NOT a violation. Flag only genuine signs of tampering or conflicting values.

Respond with ONLY a JSON object, no other text, no markdown code fences, in this exact format:
{
  "manufacturer_details": {"found": true/false, "value": "extracted text or null"},
  "common_name": {"found": true/false, "value": "extracted text or null"},
  "net_quantity": {"found": true/false, "value": "extracted text or null"},
  "mrp": {"found": true/false, "value": "extracted text or null"},
  "mfg_date": {"found": true/false, "value": "extracted text or null"},
  "consumer_care": {"found": true/false, "value": "extracted text or null"},
  "font_legibility": {"acceptable": true/false, "notes": "brief explanation"},
  "placement": {"acceptable": true/false, "notes": "brief explanation"},
  "misleading": {"acceptable": true/false, "notes": "brief explanation; 'acceptable': true means NO signs of tampering/conflict found"}
}"""


def analyze_label(image_bytes, media_type):
    response = model.generate_content([
        {"mime_type": media_type, "data": image_bytes},
        EXTRACTION_PROMPT,
    ])
    raw_reply = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw_reply)


# =====================================================================
# E-COMMERCE / PRODUCT LISTING SCANNING (Rule 6(10))
# Rule 6(10) of the Legal Metrology (Packaged Commodities) Rules, 2011
# requires every statutory declaration to also be displayed on the
# product's e-commerce listing page. This lets an officer check a listing
# URL directly, reusing the same rule engine — but only over the six
# extractable REQUIRED_FIELDS, since font legibility, placement, and
# tampering are physical-label checks that don't apply to page text.
# =====================================================================
LISTING_EXTRACTION_PROMPT_TEMPLATE = """You are a Legal Metrology compliance inspector reviewing the text content of an e-commerce product listing page. Rule 6(10) of the Legal Metrology (Packaged Commodities) Rules, 2011 requires every statutory declaration to be displayed on the listing page itself.

Check whether the following mandatory declarations are EXPLICITLY present anywhere in the page text below. Do not guess or infer a value that is not clearly stated.

1. manufacturer_details - name and address of manufacturer/packer/importer
2. common_name - common or generic name of the commodity
3. net_quantity - net quantity in a standard unit (weight, volume, count, or dimensions)
4. mrp - Maximum Retail Price, inclusive of all taxes
5. mfg_date - month and year of manufacture, packing, or import
6. consumer_care - consumer care details (address, phone number, toll-free number, or email)

PAGE TEXT:
---
{page_text}
---

Respond with ONLY a JSON object, no other text, no markdown code fences, in this exact format:
{{
  "manufacturer_details": {{"found": true/false, "value": "extracted text or null"}},
  "common_name": {{"found": true/false, "value": "extracted text or null"}},
  "net_quantity": {{"found": true/false, "value": "extracted text or null"}},
  "mrp": {{"found": true/false, "value": "extracted text or null"}},
  "mfg_date": {{"found": true/false, "value": "extracted text or null"}},
  "consumer_care": {{"found": true/false, "value": "extracted text or null"}}
}}"""


def fetch_listing_text(url, max_chars=8000):
    """Fetch an e-commerce product listing page and return its visible text
    (title + body copy, scripts/styles stripped), capped to max_chars so the
    extraction prompt stays a reasonable size.

    NOTE: Major marketplaces (Amazon, Flipkart, etc.) actively block
    automated/script-based fetches — even with realistic headers — and will
    often return a 500/503 or a CAPTCHA page instead of the real listing.
    This is a platform-side anti-bot measure, not something a request-level
    fix can reliably get around. When this happens, the officer should use
    the "Paste page text manually" fallback in the UI instead.
    """
    resp = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        },
        timeout=12,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    lines = [ln.strip() for ln in soup.get_text(separator="\n").splitlines() if ln.strip()]
    body_text = "\n".join(lines)
    combined = f"PAGE TITLE: {title}\n\n{body_text}"
    return combined[:max_chars]


def analyze_listing(page_text):
    prompt = LISTING_EXTRACTION_PROMPT_TEMPLATE.format(page_text=page_text)
    response = model.generate_content(prompt)
    raw_reply = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw_reply)


def compute_compliance(result_json, assessment=True):
    """assessment=False skips the three physical-label-only checks
    (font_legibility, placement, misleading) — used for e-commerce listing
    scans, which have no physical layout to judge."""
    found, missing = [], []
    for field in REQUIRED_FIELDS:
        entry = result_json.get(field, {"found": False, "value": None})
        label = FIELD_LABELS[field]
        legal_ref = FIELD_LEGAL_REF[field]
        if entry.get("found"):
            found.append({"label": label, "value": entry.get("value"), "legal_ref": legal_ref})
        else:
            missing.append({"label": label, "legal_ref": legal_ref})

    if assessment:
        for field, rule in ASSESSMENT_RULES.items():
            entry = result_json.get(field, {"acceptable": False, "notes": "Not assessed"})
            if entry.get("acceptable"):
                found.append({"label": rule["label"], "value": entry.get("notes", "Acceptable"), "legal_ref": rule["legal_reference"]})
            else:
                missing.append({"label": rule["label"], "legal_ref": rule["legal_reference"], "note": entry.get("notes", "")})

    total_checks = len(REQUIRED_FIELDS) + (len(ASSESSMENT_RULES) if assessment else 0)
    score = round((len(found) / total_checks) * 100) if total_checks else 0
    return found, missing, score


def build_scans_over_time(records):
    """Daily scan count as a DataFrame indexed by date, for a line/bar chart."""
    if not records:
        return pd.DataFrame({"Scans": []})
    dates = [r["scan_time"][:10] for r in records]  # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DD"
    counts = Counter(dates)
    df = pd.DataFrame({"Date": list(counts.keys()), "Scans": list(counts.values())})
    df = df.sort_values("Date").set_index("Date")
    return df


def build_violation_frequency(records, top_n=10):
    """Count how often each declaration label shows up as a violation, for a bar chart."""
    if not records:
        return pd.DataFrame({"Violations": []})
    counter = Counter()
    for r in records:
        try:
            missing_list = json.loads(r["missing_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        for m in missing_list:
            counter[m["label"]] += 1
    if not counter:
        return pd.DataFrame({"Violations": []})
    top = counter.most_common(top_n)
    df = pd.DataFrame({"Declaration": [t[0] for t in top], "Violations": [t[1] for t in top]})
    df = df.set_index("Declaration")
    return df


def build_score_distribution(records):
    """Bucket scores into ranges for a bar chart."""
    buckets = {"0–49%": 0, "50–79%": 0, "80–99%": 0, "100%": 0}
    for r in records:
        s = r["score"]
        if s == 100:
            buckets["100%"] += 1
        elif s >= 80:
            buckets["80–99%"] += 1
        elif s >= 50:
            buckets["50–79%"] += 1
        else:
            buckets["0–49%"] += 1
    df = pd.DataFrame({"Scans": list(buckets.values())}, index=list(buckets.keys()))
    return df


def reverse_geocode(lat, lon):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "LegalMetrologyComplianceChecker/1.0"},
            timeout=5,
        )
        if resp.ok:
            return resp.json().get("display_name", None)
    except Exception:
        pass
    return None


# =====================================================================
# LOCATION (auto-detect, silent best-effort)
# =====================================================================
if "location" not in st.session_state:
    st.session_state.location = None

loc = get_geolocation()
if loc and loc.get("coords"):
    st.session_state.location = {"lat": loc["coords"]["latitude"], "lon": loc["coords"]["longitude"]}

# =====================================================================
# HEADER
# =====================================================================
st.markdown('<div class="tricolor"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="hero">
    <h1><span class="icon">⚖️</span>Legal Metrology Compliance Checker</h1>
    <p>Enforcement tool for authorized officers — scan packaged product labels and check compliance with the Legal Metrology (Packaged Commodities) Rules, 2011</p>
</div>
""", unsafe_allow_html=True)

# =====================================================================
# SIDEBAR: STAFF LOGIN (admin / officer roles)
# =====================================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.must_change_password = False

with st.sidebar:
    st.markdown("### 🔐 Staff login")
    if not st.session_state.logged_in:
        with st.form("login_form"):
            uname = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Log in"):
                auth = db.verify_user(uname, pw)
                if auth:
                    st.session_state.logged_in = True
                    st.session_state.username = uname
                    st.session_state.role = auth["role"]
                    st.session_state.must_change_password = auth["must_change_password"]
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")
    else:
        st.success(f"{st.session_state.username} ({st.session_state.role})")
        if st.button("Log out"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.role = None
            st.session_state.must_change_password = False
            st.rerun()

# =====================================================================
# FORCED PASSWORD CHANGE — blocks all other functionality until the
# officer/admin sets their own password (applies to seeded default
# accounts and any newly created account on first login).
# =====================================================================
if st.session_state.logged_in and st.session_state.get("must_change_password"):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 🔒 You must set a new password before continuing")
    st.write(
        "Your account is using a default or administrator-assigned password. "
        "For security, please set a new password now."
    )
    with st.form("forced_pw_change"):
        new_pw = st.text_input("New password", type="password")
        confirm_pw = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Set new password"):
            if new_pw and new_pw == confirm_pw:
                db.set_user_password(st.session_state.username, new_pw)
                st.session_state.must_change_password = False
                st.success("Password updated. Continuing...")
                st.rerun()
            else:
                st.error("Passwords don't match or are empty.")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# =====================================================================
# SCAN A PRODUCT — restricted to authenticated enforcement officers/admins
# (this is an official inspection tool, not a public consumer app)
# =====================================================================
if not st.session_state.logged_in:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 🔒 Officer login required")
    st.write(
        "This is an official Legal Metrology enforcement tool. Please log in from the "
        "sidebar with your officer or admin account to scan a product label, "
        "view inspection history, or generate compliance reports."
    )
    st.markdown('</div>', unsafe_allow_html=True)
    uploaded_file = None
    listing_url = None
else:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 📷 Scan a product label or e-commerce listing")
    capture_mode = st.radio(
        "Image source",
        ["Upload a file", "Use camera", "E-commerce listing (URL)"],
        horizontal=True,
        label_visibility="collapsed",
    )
    uploaded_file = None
    listing_url = None
    if capture_mode == "Upload a file":
        uploaded_file = st.file_uploader("Upload a product label image", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
    elif capture_mode == "Use camera":
        uploaded_file = st.camera_input("Capture a product label", label_visibility="collapsed")
    else:
        st.caption(
            "Rule 6(10) requires all statutory declarations to appear on the product's e-commerce "
            "listing page itself. Paste the product page URL below to check it."
        )
        url_input = st.text_input("Product listing URL", placeholder="https://www.example.com/product/...")
        fetch_clicked = st.button("🌐 Fetch & analyze listing")
        if fetch_clicked and url_input:
            listing_url = url_input
            st.session_state["ecommerce_url"] = url_input
            st.session_state.pop("ecommerce_page_text", None)  # force a fresh fetch attempt
        elif st.session_state.get("ecommerce_url"):
            # Persist across reruns triggered by the "paste text manually" fallback
            # button below, which would otherwise lose listing_url on rerun.
            listing_url = st.session_state["ecommerce_url"]
    st.markdown('</div>', unsafe_allow_html=True)

if uploaded_file is not None:
    image_bytes = uploaded_file.read()
    media_type = "image/png" if uploaded_file.name.lower().endswith("png") else "image/jpeg"

    col1, col2 = st.columns([1, 1.3])
    with col1:
        st.image(image_bytes, caption="Uploaded image", use_container_width=True)

    with st.spinner("🔍 Analyzing label with AI..."):
        try:
            result_json = analyze_label(image_bytes, media_type)
            found, missing, score = compute_compliance(result_json)
        except Exception as e:
            st.error(f"Error during analysis: {e}")
            found, missing, score = [], [], 0
            result_json = {}

    location_name = None
    if st.session_state.location:
        location_name = reverse_geocode(st.session_state.location["lat"], st.session_state.location["lon"])

    with col2:
        ring_color = "#1e8e3e" if score == 100 else ("#f9a825" if score >= 50 else "#d93025")
        st.markdown(f"""
        <div class="score-box">
            <div class="num" style="color:{ring_color}">{score}%</div>
            <div class="label">Compliance score</div>
        </div>
        """, unsafe_allow_html=True)

        st.write("")
        st.markdown("**✅ Found declarations**")
        for f in found:
            st.markdown(f"""
            <div class="badge-found">
                <span class="badge-icon">✅</span>
                <span class="badge-text"><b>{f['label']}</b> — {f['value']}
                <span class="badge-sub">{f['legal_ref']}</span></span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("**❌ Missing declarations (violations)**")
        if not missing:
            st.markdown('<div class="badge-found"><span class="badge-icon">🎉</span> No violations detected.</div>', unsafe_allow_html=True)
        for m in missing:
            note_html = f'<span class="badge-sub">AI note: {m["note"]}</span>' if m.get("note") else ""
            st.markdown(f"""
            <div class="badge-missing">
                <span class="badge-icon">❌</span>
                <span class="badge-text"><b>{m['label']}</b>
                <span class="badge-sub">Violates {m['legal_ref']}</span>{note_html}</span>
            </div>
            """, unsafe_allow_html=True)

    if result_json:
        with st.expander("Raw AI response (for debugging)"):
            st.json(result_json)

    # =================================================================
    # RULE 7 — PRECISE NUMERAL-HEIGHT VERIFICATION (calibrated, optional)
    # AI's font_legibility judgment above is a relative opinion, not a
    # physical measurement. This section lets the officer measure the
    # actual printed numeral height in millimetres using local OCR
    # (independent of Gemini) plus an in-frame calibration reference,
    # and compare it against the Rule 7 Table-I threshold.
    # =================================================================
    font_height_result = None
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 🔬 Verify Rule 7 numeral height (precise, optional)")
    st.caption(
        "The AI legibility check above is a relative judgment. Use this section for a physical "
        "mm measurement an inspector can rely on in an enforcement action."
    )

    if not fh.tesseract_available():
        st.warning(
            "Local OCR (Tesseract) is not available in this environment, so precise measurement "
            "can't run here. The AI relative-judgment check above remains the only font/legibility "
            "signal for this scan."
        )
    else:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        word_boxes = fh.get_word_boxes(pil_image)

        if not word_boxes:
            st.info("No text boxes were detected by OCR on this image — try a clearer, well-lit photo.")
        else:
            box_options = {
                f"\"{b.text}\"  (h={b.height}px, conf={b.confidence:.0f}%)  @({b.left},{b.top})": b
                for b in word_boxes
            }
            box_label = st.selectbox(
                "1. Select the OCR box for the numeral you want to verify (e.g. the net-quantity or MRP figure)",
                list(box_options.keys()),
            )
            selected_box = box_options[box_label]

            st.write(
                "2. Calibrate: measure something else **in the same photo** whose real-world size you know "
                "(a ruler, a coin, or the pack's own printed dimension), in pixels and in millimetres."
            )
            cal_col1, cal_col2 = st.columns(2)
            with cal_col1:
                ref_px = st.number_input("Reference length in the photo (pixels)", min_value=0.0, value=0.0, step=1.0)
            with cal_col2:
                ref_mm = st.number_input("Real-world length of that reference (mm)", min_value=0.0, value=0.0, step=0.5)

            net_qty_value = next((f["value"] for f in found if f["label"] == FIELD_LABELS.get("net_quantity")), None)
            required_info = fh.required_height_mm(net_qty_value) if net_qty_value else None

            if st.button("📏 Measure numeral height"):
                measured_mm = fh.measure_height_mm(selected_box.height, ref_px, ref_mm)
                if measured_mm is None:
                    st.error("Couldn't measure — check that both calibration values are greater than zero.")
                elif required_info is None:
                    st.warning(
                        f"Measured height: **{measured_mm} mm**. Could not determine the Rule 7 Table-I "
                        f"requirement automatically (net quantity '{net_qty_value}' doesn't parse as a "
                        "weight/volume — Table-II count-based items need manual lookup)."
                    )
                    font_height_result = {"measured_mm": measured_mm, "required_mm": None, "verdict": "UNVERIFIED", "field": "selected_box"}
                else:
                    required_mm = required_info["required_mm"]
                    verdict = "PASS" if measured_mm >= required_mm else "FAIL"
                    color = "#1e8e3e" if verdict == "PASS" else "#d93025"
                    st.markdown(
                        f"**Measured height: {measured_mm} mm** — Rule 7 requires ≥ **{required_mm} mm** "
                        f"for this net quantity — <span style='color:{color};font-weight:700'>{verdict}</span>",
                        unsafe_allow_html=True,
                    )
                    font_height_result = {"measured_mm": measured_mm, "required_mm": required_mm, "verdict": verdict, "field": "net_quantity"}
                st.session_state["_last_font_height_result"] = font_height_result
                st.caption(fh.LEGAL_CAUTION)

    if st.session_state.get("_last_font_height_result"):
        font_height_result = st.session_state["_last_font_height_result"]
    st.markdown('</div>', unsafe_allow_html=True)

    if found or missing:
        st.markdown("#### 📄 Download compliance report")
        st.caption("PDF for filing/printing · Word for editing · CSV for raw data/spreadsheets")

        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            pdf_en = generate_pdf_report(image_bytes, found, missing, score, uploaded_file.name, FIELD_LABELS, lang="en", location_name=location_name, font_height_result=font_height_result)
            st.download_button(
                "📄 PDF Report (English)",
                data=pdf_en,
                file_name=f"compliance_report_en_{uploaded_file.name.split('.')[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
            )
        with row1_col2:
            pdf_hi = generate_pdf_report(image_bytes, found, missing, score, uploaded_file.name, FIELD_LABELS, lang="hi", location_name=location_name, font_height_result=font_height_result)
            st.download_button(
                "📄 रिपोर्ट (हिन्दी PDF)",
                data=pdf_hi,
                file_name=f"compliance_report_hi_{uploaded_file.name.split('.')[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
            )

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        with row2_col1:
            docx_en = generate_docx_report(image_bytes, found, missing, score, uploaded_file.name, FIELD_LABELS, lang="en", location_name=location_name, font_height_result=font_height_result)
            st.download_button(
                "📝 Word (English)",
                data=docx_en,
                file_name=f"compliance_report_en_{uploaded_file.name.split('.')[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with row2_col2:
            docx_hi = generate_docx_report(image_bytes, found, missing, score, uploaded_file.name, FIELD_LABELS, lang="hi", location_name=location_name, font_height_result=font_height_result)
            st.download_button(
                "📝 वर्ड रिपोर्ट (हिन्दी)",
                data=docx_hi,
                file_name=f"compliance_report_hi_{uploaded_file.name.split('.')[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with row2_col3:
            csv_data = generate_csv_report(found, missing, score, uploaded_file.name, location_name)
            st.download_button(
                "📊 CSV (raw data)",
                data=csv_data,
                file_name=f"compliance_data_{uploaded_file.name.split('.')[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

        lat = st.session_state.location["lat"] if st.session_state.location else None
        lon = st.session_state.location["lon"] if st.session_state.location else None
        db.save_scan(uploaded_file.name, score, found, missing, image_bytes, media_type, lat, lon, location_name, scanned_by=st.session_state.username, font_height_result=font_height_result)
        st.session_state.pop("_last_font_height_result", None)

elif listing_url:
    # ---------------------------------------------------------------
    # E-COMMERCE / PRODUCT LISTING SCAN (text-based, Rule 6(10))
    # No physical label image, so font/placement/tampering checks are
    # skipped (compute_compliance(..., assessment=False)); score is out
    # of the 6 required declarations only.
    # ---------------------------------------------------------------
    with st.spinner("🌐 Fetching listing page..."):
        try:
            page_text = fetch_listing_text(listing_url)
        except Exception as e:
            st.error(
                f"Couldn't fetch the listing page automatically ({e}). Many marketplaces "
                "(Amazon, Flipkart, etc.) block automated fetches with an anti-bot error page — "
                "this isn't something a retry will fix."
            )
            page_text = None

    if page_text is None:
        st.markdown("**Fallback: paste the listing page text manually**")
        st.caption(
            "Open the listing in your browser, select all the visible product text (Ctrl+A / Cmd+A "
            "on the product details area, or the whole page), copy it, and paste it below."
        )
        pasted_text = st.text_area("Pasted listing text", height=200, key="pasted_listing_text")
        if st.button("🔍 Analyze pasted text") and pasted_text.strip():
            page_text = f"PAGE TITLE: (pasted manually)\n\n{pasted_text.strip()}"

    if page_text:
        with st.spinner("🔍 Analyzing listing text with AI..."):
            try:
                result_json = analyze_listing(page_text)
                found, missing, score = compute_compliance(result_json, assessment=False)
            except Exception as e:
                st.error(f"Error during analysis: {e}")
                found, missing, score = [], [], 0
                result_json = {}

        with st.expander("Extracted page text (what the AI actually read)"):
            st.text(page_text[:3000] + ("..." if len(page_text) > 3000 else ""))

        if st.button("🔄 Scan a different listing"):
            st.session_state.pop("ecommerce_url", None)
            st.session_state.pop("pasted_listing_text", None)
            st.rerun()

        ring_color = "#1e8e3e" if score == 100 else ("#f9a825" if score >= 50 else "#d93025")
        st.markdown(f"""
        <div class="score-box">
            <div class="num" style="color:{ring_color}">{score}%</div>
            <div class="label">Compliance score (6 required declarations — Rule 6(10))</div>
        </div>
        """, unsafe_allow_html=True)
        st.caption(
            "Font legibility, placement, and tampering checks are not applicable to a text-based "
            "listing and are excluded from this score."
        )

        st.markdown("**✅ Found declarations**")
        for f in found:
            st.markdown(f"""
            <div class="badge-found">
                <span class="badge-icon">✅</span>
                <span class="badge-text"><b>{f['label']}</b> — {f['value']}
                <span class="badge-sub">{f['legal_ref']}</span></span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("**❌ Missing declarations (violations)**")
        if not missing:
            st.markdown('<div class="badge-found"><span class="badge-icon">🎉</span> No violations detected.</div>', unsafe_allow_html=True)
        for m in missing:
            st.markdown(f"""
            <div class="badge-missing">
                <span class="badge-icon">❌</span>
                <span class="badge-text"><b>{m['label']}</b>
                <span class="badge-sub">Violates {m['legal_ref']}</span></span>
            </div>
            """, unsafe_allow_html=True)

        if found or missing:
            st.markdown("#### 📄 Download compliance report")
            row1_col1, row1_col2 = st.columns(2)
            with row1_col1:
                pdf_en = generate_pdf_report(None, found, missing, score, listing_url, FIELD_LABELS, lang="en", location_name=None)
                st.download_button(
                    "📄 PDF Report (English)",
                    data=pdf_en,
                    file_name=f"compliance_report_listing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                )
            with row1_col2:
                docx_en = generate_docx_report(None, found, missing, score, listing_url, FIELD_LABELS, lang="en", location_name=None)
                st.download_button(
                    "📝 Word (English)",
                    data=docx_en,
                    file_name=f"compliance_report_listing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            csv_data = generate_csv_report(found, missing, score, listing_url, None)
            st.download_button(
                "📊 CSV (raw data)",
                data=csv_data,
                file_name=f"compliance_data_listing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

            db.save_scan(listing_url, score, found, missing, None, None, None, None, listing_url, scanned_by=st.session_state.username)

# =====================================================================
# STAFF PANEL (role-based: officer = view-only dashboard, admin = full access)
# =====================================================================
if st.session_state.logged_in:
    st.markdown("---")
    st.markdown("## 🛠️ Staff panel")

    if st.session_state.role == "admin":
        tab_labels = ["📊 Dashboard & history", "⚙️ Manage rules", "👥 Manage users", "🔑 Change password"]
    else:
        tab_labels = ["📊 Dashboard & history", "🔑 Change password"]

    tabs = st.tabs(tab_labels)
    admin_tab1 = tabs[0]
    if st.session_state.role == "admin":
        admin_tab2, admin_tab3, admin_tab4 = tabs[1], tabs[2], tabs[3]
    else:
        admin_tab4 = tabs[1]

    with admin_tab1:
        stats = db.get_summary_stats()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total scans", stats["total_scans"])
        c2.metric("Average score", f"{stats['avg_score']}%")
        c3.metric("Fully compliant", stats["fully_compliant"])

        analytics_records = db.get_scans_for_analytics()
        if analytics_records:
            st.divider()
            st.markdown("#### 📈 Inspection trends")
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.write("**Scans over time**")
                st.bar_chart(build_scans_over_time(analytics_records))
            with chart_col2:
                st.write("**Compliance score distribution**")
                st.bar_chart(build_score_distribution(analytics_records))

            st.write("**Most frequent violations (top 10 declarations)**")
            violation_df = build_violation_frequency(analytics_records)
            if not violation_df.empty:
                st.bar_chart(violation_df)
            else:
                st.caption("No violations recorded yet.")

        st.divider()
        st.markdown("#### 🔎 Search & filter inspection history")
        with st.form("search_filters_form"):
            f_col1, f_col2, f_col3 = st.columns(3)
            with f_col1:
                filter_text = st.text_input("Filename or location contains")
            with f_col2:
                scanner_options = ["All officers/admins"] + db.get_distinct_scanners()
                filter_scanner = st.selectbox("Scanned by", scanner_options)
            with f_col3:
                violation_options = ["Any"] + list(FIELD_LABELS.values())
                filter_violation = st.selectbox("Has this violation", violation_options)

            f_col4, f_col5, f_col6 = st.columns(3)
            with f_col4:
                filter_date_from = st.date_input("From date", value=None)
            with f_col5:
                filter_date_to = st.date_input("To date", value=None)
            with f_col6:
                filter_score_range = st.slider("Compliance score range (%)", 0, 100, (0, 100))

            filters_submitted = st.form_submit_button("Apply filters")

        any_filter_active = any([
            filter_text, filter_scanner != "All officers/admins", filter_violation != "Any",
            filter_date_from, filter_date_to, filter_score_range != (0, 100),
        ])

        if filters_submitted or any_filter_active:
            records = db.search_scans_advanced(
                filename=filter_text or None,
                scanned_by=None if filter_scanner == "All officers/admins" else filter_scanner,
                date_from=filter_date_from.strftime("%Y-%m-%d") if filter_date_from else None,
                date_to=filter_date_to.strftime("%Y-%m-%d") if filter_date_to else None,
                min_score=filter_score_range[0],
                max_score=filter_score_range[1],
                violation_label=None if filter_violation == "Any" else filter_violation,
            )
        else:
            records = db.get_all_scans()
        st.write(f"**{len(records)} scan(s)**")

        for rec in records:
            missing_list = json.loads(rec["missing_json"])
            violation_labels = [m["label"] for m in missing_list]
            with st.expander(f"{rec['filename']} — {rec['scan_time']} — Score: {rec['score']}%"):
                c_img, c_details = st.columns([1, 2])
                with c_img:
                    if rec["image_blob"]:
                        st.image(rec["image_blob"], use_container_width=True)
                with c_details:
                    st.write(f"**Timestamp:** {rec['scan_time']}")
                    if rec.get("scanned_by"):
                        st.write(f"**Scanned by:** {rec['scanned_by']}")
                    if rec.get("location_name"):
                        st.write(f"**Location:** {rec['location_name']}")
                    elif rec.get("latitude"):
                        st.write(f"**Coordinates:** {rec['latitude']}, {rec['longitude']}")
                    else:
                        st.write("**Location:** not available")
                    if violation_labels:
                        st.write("**Violations:**")
                        for v in violation_labels:
                            st.write(f"❌ {v}")
                    else:
                        st.write("No violations detected.")
                    if rec.get("font_height_verdict"):
                        v = rec["font_height_verdict"]
                        icon = "✅" if v == "PASS" else ("❌" if v == "FAIL" else "⚠️")
                        req_txt = f" (required ≥ {rec['font_height_required_mm']} mm)" if rec.get("font_height_required_mm") else ""
                        st.write(f"**Rule 7 numeral height:** {icon} {v} — measured {rec['font_height_measured_mm']} mm{req_txt}")

                st.markdown("**Re-download this report:**")
                found_list = json.loads(rec["found_json"])
                dl_col1, dl_col2, dl_col3, dl_col4, dl_col5 = st.columns(5)
                with dl_col1:
                    pdf_en_old = generate_pdf_report(rec["image_blob"], found_list, missing_list, rec["score"], rec["filename"], FIELD_LABELS, lang="en", location_name=rec.get("location_name"))
                    st.download_button("PDF (EN)", data=pdf_en_old, file_name=f"report_en_{rec['id']}.pdf", mime="application/pdf", key=f"pdf_en_{rec['id']}")
                with dl_col2:
                    pdf_hi_old = generate_pdf_report(rec["image_blob"], found_list, missing_list, rec["score"], rec["filename"], FIELD_LABELS, lang="hi", location_name=rec.get("location_name"))
                    st.download_button("PDF (HI)", data=pdf_hi_old, file_name=f"report_hi_{rec['id']}.pdf", mime="application/pdf", key=f"pdf_hi_{rec['id']}")
                with dl_col3:
                    docx_en_old = generate_docx_report(rec["image_blob"], found_list, missing_list, rec["score"], rec["filename"], FIELD_LABELS, lang="en", location_name=rec.get("location_name"))
                    st.download_button("Word (EN)", data=docx_en_old, file_name=f"report_en_{rec['id']}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"docx_en_{rec['id']}")
                with dl_col4:
                    docx_hi_old = generate_docx_report(rec["image_blob"], found_list, missing_list, rec["score"], rec["filename"], FIELD_LABELS, lang="hi", location_name=rec.get("location_name"))
                    st.download_button("Word (HI)", data=docx_hi_old, file_name=f"report_hi_{rec['id']}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"docx_hi_{rec['id']}")
                with dl_col5:
                    csv_old = generate_csv_report(found_list, missing_list, rec["score"], rec["filename"], rec.get("location_name"))
                    st.download_button("CSV", data=csv_old, file_name=f"report_{rec['id']}.csv", mime="text/csv", key=f"csv_{rec['id']}")

    if st.session_state.role == "admin":
        with admin_tab2:
            st.write("Edit legal references, labels, or requirement status for each rule. Changes apply immediately.")
            rules, notes = rules_manager.load_rules()
            updated_rules = []
            for i, rule in enumerate(rules):
                with st.expander(f"{rule['label']} ({rule['field']})"):
                    label = st.text_input("Label", value=rule["label"], key=f"label_{i}")
                    legal_ref = st.text_input("Legal reference", value=rule["legal_reference"], key=f"ref_{i}")
                    required = st.checkbox("Required", value=rule.get("required", True), key=f"req_{i}")
                    keep = st.checkbox("Keep this rule", value=True, key=f"keep_{i}")
                    new_rule = dict(rule)
                    new_rule["label"] = label
                    new_rule["legal_reference"] = legal_ref
                    new_rule["required"] = required
                    if keep:
                        updated_rules.append(new_rule)

            if st.button("💾 Save rule changes"):
                rules_manager.save_rules(updated_rules, notes)
                st.success("Rules updated. Reloading...")
                st.rerun()

            st.divider()
            st.write("**Add a new rule**")
            with st.form("add_rule_form"):
                new_field = st.text_input("Field key (no spaces, e.g. country_of_origin)")
                new_label = st.text_input("Label")
                new_ref = st.text_input("Legal reference")
                if st.form_submit_button("Add rule"):
                    if new_field and new_label and new_ref:
                        rules, notes = rules_manager.load_rules()
                        rules.append({"field": new_field, "label": new_label, "legal_reference": new_ref, "required": True})
                        rules_manager.save_rules(rules, notes)
                        st.success("Rule added. Note: the AI extraction prompt must also be updated in code to recognize new declaration types, and a Hindi label added to translations.py.")
                        st.rerun()
                    else:
                        st.error("All fields are required.")

        with admin_tab3:
            st.write("**Existing accounts**")
            for u in db.get_all_users():
                ucol1, ucol2 = st.columns([4, 1])
                pw_status = " ⚠️ *(must change password)*" if u.get("must_change_password") else ""
                ucol1.write(f"👤 **{u['username']}** — {u['role']}{pw_status}")
                if u["username"] != st.session_state.username:
                    if ucol2.button("Delete", key=f"del_{u['id']}"):
                        if db.delete_user(u["username"]):
                            st.success(f"Deleted {u['username']}.")
                            st.rerun()
                        else:
                            st.error("Cannot delete the last remaining admin.")

            st.divider()
            st.write("**Add a new account**")
            st.caption("The new account will be required to set its own password on first login.")
            with st.form("add_user_form"):
                new_username = st.text_input("Username")
                new_password = st.text_input("Password", type="password")
                new_role = st.selectbox("Role", ["officer", "admin"])
                if st.form_submit_button("Create account"):
                    if not new_username or not new_password:
                        st.error("Username and password are required.")
                    elif db.create_user(new_username, new_password, new_role):
                        st.success(f"Account '{new_username}' created with role '{new_role}'.")
                        st.rerun()
                    else:
                        st.error("That username already exists.")

    with admin_tab4:
        st.write(f"Change password for **{st.session_state.username}**")
        with st.form("change_pw_form"):
            new_pw = st.text_input("New password", type="password")
            confirm_pw = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update password"):
                if new_pw and new_pw == confirm_pw:
                    db.set_user_password(st.session_state.username, new_pw)
                    st.success("Password updated.")
                else:
                    st.error("Passwords don't match or are empty.")
