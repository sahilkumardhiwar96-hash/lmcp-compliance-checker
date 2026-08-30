# Legal Metrology Compliance Checker — Technical Documentation

**System type:** AI-assisted regulatory enforcement tool
**Target users:** Legal Metrology enforcement officers and administrators
**Governing regulation:** Legal Metrology Act, 2009 & Legal Metrology (Packaged Commodities) Rules, 2011

---

## 1. Problem Statement Mapping

| Functional requirement | Implementation |
|---|---|
| Image upload and scanning | Streamlit file uploader, restricted to authenticated officers |
| Extraction of mandatory declarations | Gemini multimodal vision model, structured JSON prompt |
| Font size / readability analysis | AI relative-judgment check (Rule 7) — flagged as a non-metrological estimate |
| Detection of missing/misleading declarations | Rule engine compares extracted fields against `rules.json` |
| Compliance / non-compliance report generation | PDF (fpdf2, bilingual), DOCX (python-docx, bilingual), CSV |
| Attachment of photographs and evidence | Original label image stored as BLOB, embedded in every report |
| Repository of scanned products and inspection history | SQLite `scans` table, searchable by filename/location |
| Role-based access and secure authentication | `admin` / `officer` roles, salted SHA-256 password hashing |
| Dashboard for monitoring compliance and enforcement | Summary metrics + trend charts (scans over time, score distribution, top violations) |
| Export to PDF and editable formats | PDF, DOCX, CSV download buttons on every scan |

---

## 2. System Architecture

```mermaid
flowchart TD
    U[Enforcement Officer / Admin] -->|Login| AUTH[Auth Layer<br/>db.py: verify_user]
    AUTH -->|Session role: admin/officer| APP[Streamlit App<br/>app.py]

    APP -->|Upload label image| VISION[Gemini Vision Model<br/>gemini-3.6-flash]
    VISION -->|Structured JSON:<br/>found/missing fields| ENGINE[Rule Engine<br/>compute_compliance]

    RULES[(rules.json<br/>via rules_manager.py)] --> ENGINE
    ENGINE -->|score, found[], missing[]| APP

    APP -->|Optional browser geolocation| GEO[Reverse Geocoding<br/>Nominatim OSM API]
    GEO --> APP

    APP -->|Save scan record| DB[(SQLite<br/>compliance_history.db)]
    APP -->|Generate report| PDFGEN[pdf_report.py<br/>fpdf2 + HarfBuzz shaping]
    APP -->|Generate report| DOCXGEN[report_export.py<br/>python-docx]
    APP -->|Generate report| CSVGEN[report_export.py<br/>csv module]

    DB -->|History, search, analytics| APP
    APP -->|Dashboard charts| CHARTS[pandas + st.bar_chart]

    PDFGEN --> OUT[Downloadable report<br/>PDF/DOCX/CSV]
    DOCXGEN --> OUT
    CSVGEN --> OUT
```

**Text summary of the flow:**
1. An officer logs in (session-based auth against the `users` table).
2. They upload a product label image.
3. The image is sent to Google's Gemini vision model with a structured extraction prompt covering the six mandatory declarations plus three AI-judgment checks (font legibility, placement, tampering/misleading signs).
4. The rule engine (`compute_compliance`) compares the model's JSON output against `rules.json` to produce `found`, `missing`, and a percentage `score`.
5. Optional browser geolocation is reverse-geocoded (OpenStreetMap Nominatim) to attach a human-readable location.
6. The scan (image, results, location, officer identity, timestamp) is persisted to SQLite.
7. Reports are generated on demand in PDF, DOCX, and CSV, in English and Hindi.
8. The dashboard aggregates historical scans into summary metrics and trend charts.

---

## 3. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| UI / application framework | Streamlit | Web UI, session state, file upload, forms |
| AI / vision extraction | Google Gemini API (`google-generativeai`, model `gemini-3.6-flash`) | Multimodal label reading and structured extraction |
| Geolocation | `streamlit-js-eval` (browser geolocation) + OpenStreetMap Nominatim (`requests`) | Attaching an inspection location to each scan |
| Database | SQLite (`sqlite3`, stdlib) | Users, scans, compliance history |
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
| `app.py` | UI composition, session/auth flow, scan workflow orchestration, dashboard, staff panel (rules/users/password management) |
| `db.py` | All persistence: schema creation/migration, user CRUD, scan CRUD, search, summary stats, analytics queries |
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

- **Font/legibility (Rule 7)** and **placement (Rule 9)** checks in the main scan workflow are AI relative-judgment assessments, not physical millimeter measurements or computer-vision zone detection. Borderline cases should be physically verified by an inspector, as noted directly in the generated reports.
- A separate, already-built module (`font_height.py`) exists for **precise Rule 7 numeral-height verification**: it runs local Tesseract OCR to get real pixel bounding boxes, and converts a selected box's pixel height to millimeters using an in-frame calibration reference (a ruler, coin, or known package dimension) supplied by the officer, then compares it against the Rule 7 Table-I thresholds. This module is implemented and unit-tested (`test_font_height.py`) but **is not yet called from `app.py`** — it is not part of the live scan workflow. Wiring it in is the immediate next step (see Section 9) and does not require new measurement logic, only UI integration.
- Even once wired in, `font_height.py` only covers Table-I (weight/volume-based) thresholds; Table-II (length/area/number-based declarations, e.g. count items) still requires manual verification.
- **Tampering detection** (Rule 6(3)/18) relies on the vision model spotting visual inconsistencies (conflicting values, stickers, mismatched print) — not a forensic-grade determination.
- SQLite is suitable for single-instance or low-concurrency deployments; a multi-officer, high-volume rollout should migrate to PostgreSQL.
- The AI extraction step depends on an external API (Gemini); network or API-quota issues will block scanning until resolved.
- The current scan workflow covers physical label **images** only; text-based product listings (e.g. e-commerce pages) are not yet ingested — see Section 9.

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

# 3. Install dependencies
pip install streamlit google-generativeai requests streamlit-js-eval fpdf2 python-docx pandas

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

- **Wire the existing calibrated font-height module (`font_height.py`) into the main scan workflow.** The OCR + in-frame calibration logic for precise Rule 7 mm measurement is already implemented and unit-tested; it needs a UI step (reference-object input, OCR-box selection) added to `app.py`, not new measurement logic.
- Extend automated font-height verification to Table-II (count/number-based) declarations, which the current module does not cover.
- Add ingestion of **text-based product listings** (e.g. e-commerce product pages) alongside image scanning — the rule engine (`compute_compliance`) is already input-agnostic (it operates on a found/missing field dictionary), so this mainly requires a new extraction path rather than changes to the compliance logic itself.
- Move to PostgreSQL and object storage (e.g. S3-compatible) for multi-officer, high-volume deployments.
- Add a mobile-native or PWA wrapper for field use without a laptop.
- Expand the dashboard with officer-level and region-level breakdowns once location data collection is consistent.
