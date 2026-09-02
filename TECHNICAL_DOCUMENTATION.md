# Legal Metrology Compliance Checker — Technical Documentation

**System type:** AI-assisted regulatory enforcement tool
**Target users:** Legal Metrology enforcement officers and administrators
**Governing regulation:** Legal Metrology Act, 2009 & Legal Metrology (Packaged Commodities) Rules, 2011

---

## 1. Problem Statement Mapping

| Functional requirement | Implementation |
|---|---|
| Image upload and scanning | Streamlit file uploader, camera capture, restricted to authenticated officers |
| Extraction of mandatory declarations | Gemini multimodal vision model, structured JSON prompt |
| Font size / readability analysis | Two-tier: (1) AI relative-judgment check (Rule 7) for a fast pass/flag, and (2) an optional **calibrated physical measurement** — local Tesseract OCR + an in-frame reference object converts the printed numeral height to real millimetres and checks it against the Rule 7 Table-I minimum, independent of the AI judgment |
| Detection of missing/misleading declarations | Rule engine compares extracted fields against `rules.json`; a dedicated AI check also flags conflicting values or signs of altered/stickered declarations (Rule 6(3)/18) |
| Compliance / non-compliance report generation | PDF (fpdf2, bilingual), DOCX (python-docx, bilingual), CSV |
| Attachment of photographs and evidence | Original label image stored as BLOB, embedded in every report |
| Repository of scanned products and inspection history | SQLite `scans` table, multi-filter search (filename/location, officer, date range, score range, violation type) |
| Role-based access and secure authentication | `admin` / `officer` roles, salted SHA-256 password hashing, forced password change on first login |
| Dashboard for monitoring compliance and enforcement | Summary metrics + trend charts (scans over time, score distribution, top violations) |
| Export to PDF and editable formats | PDF, DOCX, CSV download buttons on every scan (including bulk re-download from history) |
| E-commerce listing compliance (Rule 6(10)) | Product listing URL fetch, screenshot upload, or manual paste of listing text, checked against the same six mandatory declarations |

---

## 2. System Architecture

```
                         Enforcement Officer / Admin
                                    |
                                 (Login)
                                    v
                          Auth Layer (db.py)
                                    |
                          Streamlit App (app.py)
                                    |
              ------------------------------------------------
              |                                               |
   Label image (upload/camera)                Listing URL / pasted text
              |                                               |
      Gemini Vision Model                        Listing Text Extraction
   (label extraction + AI checks)                 (Rule 6(10) extraction)
              |                                               |
              ------------------------------------------------
                                    |
                                    v
                    Rule Engine (compute_compliance)
                        <-- rules.json (rules_manager.py)
                                    |
                        (score, found list, missing list)
                                    v
                          Streamlit App (app.py)
                                    |
        --------------------+------+-------+----------------------+
        |                   |              |                      |
   Tesseract OCR      Reverse Geocoding   SQLite Database    Report Modules
 (calibrated Rule 7    (browser geo ->    (compliance_       (pdf_report.py,
  mm measurement,        OSM Nominatim)    history.db;        report_export.py
  font_height.py)                          scan history,      -> PDF / DOCX / CSV)
        |                   |              analytics)                |
        v                   v                   |                    v
   measured_mm,        location_name    Dashboard (pandas +   Downloadable
   verdict -> app                        st.bar_chart charts)  compliance report
```

**Text summary of the flow:**
1. An officer logs in (session-based auth against the `users` table).
2. They provide a product label image (file upload or camera) **or** an e-commerce listing (URL fetch, screenshot upload, or pasted page text).
3. Label images are sent to Google's Gemini vision model with a structured extraction prompt covering the six mandatory declarations plus three AI-judgment checks (font legibility, placement, tampering/misleading signs); listing text is sent to Gemini with a parallel prompt covering the same six declarations under Rule 6(10) (assessment-only checks are skipped for listings, since there is no physical layout to judge).
4. The rule engine (`compute_compliance`) compares the model's JSON output against `rules.json` to produce `found`, `missing`, and a percentage `score`.
5. Optionally, for a physical label image, the officer can run a **calibrated Rule 7 measurement**: local Tesseract OCR proposes candidate text boxes, the officer selects the numeral to verify and supplies an in-frame calibration reference (a ruler, coin, or known dimension), and `font_height.py` converts the selected box's pixel height into millimetres and compares it against the Rule 7 Table-I minimum for the declared net quantity — independent of the Gemini extraction path.
6. Optional browser geolocation is reverse-geocoded (OpenStreetMap Nominatim) to attach a human-readable location.
7. The scan (image, results, location, officer identity, timestamp, and any calibrated font-height result) is persisted to SQLite.
8. Reports are generated on demand in PDF, DOCX, and CSV, in English and Hindi.
9. The dashboard aggregates historical scans into summary metrics and trend charts, with multi-filter search and re-download of past reports.

---

## 3. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| UI / application framework | Streamlit | Web UI, session state, file upload, forms |
| AI / vision extraction | Google Gemini API (`google-generativeai`, model `gemini-3.6-flash`) | Multimodal label reading and structured extraction (labels and e-commerce listing text) |
| Precise font-height OCR | `pytesseract` + Tesseract (`tesseract-ocr` system package) | Local, Gemini-independent pixel bounding boxes for calibrated Rule 7 mm measurement |
| E-commerce listing fetch | `requests` + `beautifulsoup4` | Fetches and strips visible text from simple/server-rendered listing pages (Rule 6(10)); JS-heavy marketplaces fall back to screenshot upload or manual paste |
| Geolocation | `streamlit-js-eval` (browser geolocation) + OpenStreetMap Nominatim (`requests`) | Attaching an inspection location to each scan |
| Database | SQLite (`sqlite3`, stdlib) | Users, scans, compliance history (incl. calibrated font-height results) |
| PDF generation | `fpdf2` with HarfBuzz text shaping | Bilingual (English/Hindi) reports with correct Devanagari conjunct rendering |
| DOCX generation | `python-docx` | Editable Word reports for further annotation by officers |
| Data analysis / charts | `pandas` + Streamlit native charting (`st.bar_chart`) | Dashboard trend visualizations |
| Fonts | Noto Sans Devanagari (Regular, Bold) | Embedded for correct Hindi rendering in PDFs |
| Auth | `hashlib` (SHA-256) + `secrets` (salting, constant-time comparison) | Password storage and verification |

**Language:** Python 3.9+ throughout (single-language stack — no separate frontend/backend split; Streamlit serves both).

---

## 4. Module Responsibilities

| File | Responsibility |
|---|---|
| `app.py` | UI composition, session/auth flow, label-scan and e-commerce-listing-scan workflow orchestration, calibrated font-height UI step, dashboard, staff panel (rules/users/password management) |
| `db.py` | All persistence: schema creation/migration, user CRUD, scan CRUD, search, summary stats, analytics queries |
| `font_height.py` | Local Tesseract OCR word-box detection, pixel-to-mm conversion via an in-frame calibration reference, and Rule 7 Table-I threshold lookup by net quantity |
| `rules_manager.py` | Load/save the compliance rule set from `rules.json` |
| `rules.json` | Declarative rule definitions: field key, English/Hindi label, legal reference, required flag |
| `pdf_report.py` | Bilingual PDF report rendering (fpdf2), including custom table layout with page-break-safe rows |
| `report_export.py` | Bilingual DOCX report rendering (python-docx) and CSV raw-data export |
| `translations.py` | Static English/Hindi UI and report strings, field label lookups |

---

## 5. Database Schema

**`users`**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| username | TEXT UNIQUE | |
| password_hash | TEXT | SHA-256(salt + password) |
| salt | TEXT | Random 16-hex-char salt per user |
| role | TEXT | `admin` or `officer` (CHECK constraint) |
| created_at | TEXT | |

**`scans`**
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| filename | TEXT | Original uploaded filename |
| scan_time | TEXT | `YYYY-MM-DD HH:MM:SS` |
| score | INTEGER | 0–100 compliance percentage |
| found_json | TEXT | JSON array of found declarations (label, value, legal ref) |
| missing_json | TEXT | JSON array of missing declarations (label, legal ref, AI note) |
| image_blob | BLOB | Original label photo |
| image_media_type | TEXT | MIME type |
| latitude / longitude | REAL | Optional GPS coordinates |
| location_name | TEXT | Reverse-geocoded address |
| scanned_by | TEXT | Username of the officer who performed the scan |

Schema migrations (e.g. adding `scanned_by` to a pre-existing database) are handled defensively in `init_db()` via `PRAGMA table_info` checks, so existing installations upgrade without data loss.

---

## 6. Security Notes

- Passwords are salted and hashed (SHA-256 + per-user random salt); verification uses `secrets.compare_digest` to avoid timing attacks.
- The scan/report workflow is only reachable after authentication — this is an internal enforcement tool, not a public-facing consumer app.
- The last remaining `admin` account cannot be deleted, preventing accidental lockout.
- **Before production deployment:** rotate the seeded default credentials (`admin/admin123`, `officer/officer123`), remove the on-screen demo-credentials hint, and set `GOOGLE_API_KEY` via a secrets manager rather than a plain environment variable.

---

## 7. Known Limitations

- **Font/legibility (Rule 7)** and **placement (Rule 9)** checks from the AI extraction step are relative-judgment assessments, not physical measurements or computer-vision zone detection. For Rule 7, the officer can follow up with the calibrated OCR measurement described below for a physical mm figure; placement (Rule 9) currently has no equivalent precise check and remains an AI judgment call, flagged as such in the generated reports.
- **Precise Rule 7 numeral-height verification is implemented and live** in the scan workflow (`font_height.py`, invoked from `app.py`'s "Verify Rule 7 numeral height" step): local Tesseract OCR proposes candidate text boxes, the officer selects the numeral to verify and supplies an in-frame calibration reference (a ruler, coin, or known package dimension), and the tool converts the selected box's pixel height to millimetres and compares it against the Rule 7 Table-I threshold — independent of the Gemini extraction path. It requires Tesseract to be available in the deployment environment (see Section 8) and only covers Table-I (weight/volume-based) thresholds; Table-II (length/area/number-based declarations, e.g. count items) still requires manual verification.
- **Tampering detection** (Rule 6(3)/18) relies on the vision model spotting visual inconsistencies (conflicting values, stickers, mismatched print) — not a forensic-grade determination.
- **E-commerce listing scanning (Rule 6(10)) is implemented and live**, via direct URL fetch of the listing page. This depends on the target page being simple/server-rendered: JavaScript-heavy marketplaces (Amazon, Flipkart, Zepto, etc.) either block automated fetches outright (raising a fetch error, in which case the UI already offers a manual paste-text fallback) or return a shell page whose product content loads client-side — a fetch that technically succeeds but yields little or no usable text, which the AI then correctly reports as "not found." This second case does not currently trigger the manual-paste fallback automatically; officers should use the paste-text option proactively for any listing where the scored result looks implausibly empty. A screenshot-upload mode (reusing the existing image-scan pipeline) is a straightforward addition for these sites and is listed under Future Enhancements.
- SQLite is suitable for single-instance or low-concurrency deployments; a multi-officer, high-volume rollout should migrate to PostgreSQL.
- The AI extraction step depends on an external API (Gemini); network connectivity issues or Gemini API-quota limits (the free tier is capped at a small number of requests/day per model) will block scanning until resolved. A production rollout should use a paid Gemini tier or an enterprise agreement with adequate quota, and would benefit from offline capture with background sync for low-connectivity field use (see Section 9).

---

## 8. Deployment Framework

### 8.1 Local / development deployment

```bash
# 1. Clone/copy the project folder (all .py files, rules.json, compliance_history.db,
#    and a fonts/ subfolder containing the two Noto Sans Devanagari .ttf files)

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Linux/macOS
venv\Scripts\Activate.ps1         # Windows PowerShell

# 3. Install Python dependencies
pip install -r requirements.txt
# (streamlit, google-generativeai, requests, beautifulsoup4, streamlit-js-eval,
#  python-docx, pillow, fpdf2, pandas, uharfbuzz, pytesseract)

# 3b. Install the Tesseract OCR system binary (required for calibrated Rule 7
#     measurement; see packages.txt — this is a system package, not pip-installable)
sudo apt-get install tesseract-ocr      # Debian/Ubuntu
# On Streamlit Community Cloud this is installed automatically from packages.txt

# 4. Set the Gemini API key
export GOOGLE_API_KEY="your-key-here"      # Linux/macOS
$env:GOOGLE_API_KEY = "your-key-here"      # Windows PowerShell

# 5. Run
streamlit run app.py
```

The app is served at `http://localhost:8501` by default.

### 8.2 Cloud deployment options

| Option | Notes |
|---|---|
| **Streamlit Community Cloud** | Simplest path — connect a GitHub repo, set `GOOGLE_API_KEY` as a secret in the app settings. Free tier suitable for pilots/demos. |
| **Container (Docker) on Azure/AWS/GCP** | Package the app with a `Dockerfile` (base image `python:3.11-slim`, install requirements, `EXPOSE 8501`, `CMD ["streamlit","run","app.py"]`). Deploy to Azure App Service, AWS ECS/Fargate, or Google Cloud Run for horizontal scaling. |
| **On-premise government server** | Run behind a reverse proxy (Nginx) with HTTPS termination, ideally with SQLite replaced by PostgreSQL and file storage (images) moved to a mounted volume or object store rather than in-DB BLOBs, for larger-scale deployments. |

### 8.3 Environment variables required

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Authenticates calls to the Gemini API for label analysis |

### 8.4 Data persistence

- `compliance_history.db` (SQLite) holds all users and scan history — back this up regularly.
- `rules.json` holds the editable compliance rule set — version-control or back up changes made via the admin "Manage rules" tab.

---

## 9. Future Enhancements

- **Auto-detect thin/empty listing fetches and fall back to manual paste automatically.** Currently the paste-text fallback only triggers when `fetch_listing_text` raises an exception (blocked/error response); a successful-but-near-empty fetch from a JavaScript-rendered page (see Section 7) should be treated the same way.
- **Add a screenshot-upload mode for e-commerce listings**, reusing the existing image-scan Gemini pipeline, so JavaScript-heavy marketplaces that block automated text fetches can still be checked without manual copy-paste.
- Extend automated font-height verification to Table-II (count/number-based) declarations, which `font_height.py` does not currently cover.
- Add a precise, non-AI check for declaration **placement** (Rule 9), e.g. computer-vision zone/grouping detection, to complement the existing AI relative-judgment check.
- **Offline-first capture with background sync**: let an officer photograph a label with no connectivity, queue it locally, and sync to Gemini automatically once a connection is available, so field use in low-connectivity areas isn't blocked.
- Move to a paid/enterprise Gemini tier (or a self-hosted open-source vision-language model) with adequate request quota for production-scale usage, ideally via India-data-residency options for government deployments.
- Move to PostgreSQL and object storage (e.g. S3-compatible) for multi-officer, high-volume deployments.
- Add a mobile-native or PWA wrapper for field use without a laptop.
- Expand the dashboard with officer-level and region-level breakdowns once location data collection is consistent.
