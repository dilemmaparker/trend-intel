<![CDATA[<div align="center">

# 📈 TrendIntel — Fashion Trend Intelligence v5.0

### *Data-Centric, Resource-Efficient AI Framework for Competitive Value Retail*

**Ethnic & Value Retail · India Market**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Google Trends](https://img.shields.io/badge/Google%20Trends-API-4285F4?logo=google&logoColor=white)](https://trends.google.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Deploy](https://img.shields.io/badge/Deploy-Render.com-46E3B7?logo=render&logoColor=white)](https://render.com)

*Know which trends to **buy**, hold, or exit — before margins close.*

[Live Demo](#deploy) · [Features](#-features) · [How It Works](#-scoring-methodology) · [Quick Start](#-quick-start) · [API Reference](#-api-reference)

</div>

---

## 🔍 The Problem

India's ethnic value retail sector (kurtis, sarees, lehengas, co-ord sets) faces a critical gap in trend intelligence:

| Gap | Impact |
|-----|--------|
| **Selection based solely on historic sales** | Buying teams rely on past bestsellers and STR data — zero visibility into *emerging* consumer search demand |
| **Commercial forecasters are expensive** | WGSN, Trendalytics etc. start at ₹5–15L/year — inaccessible for value retailers operating on thin margins |
| **No regional granularity** | National trend reports can't tell you how demand for block print kurtis differs between West Bengal and Gujarat |
| **Qualitative guesswork** | Decisions rely on Pinterest boards, competitor floor walks, and buyer intuition — no data backbone |

## 💡 The Solution

TrendIntel is a **free, open-source trend intelligence system** that uses **Google Trends search data** as a proxy for real-time consumer demand. It scores fashion concepts on a 0–100 scale and outputs **actionable buying mandates** — BUY, HOLD, WATCH, or EXIT — to guide Open-to-Buy (OTB) allocation decisions.

**Zero licensing cost. Real data. Regional granularity. Built for India's ethnic wear market.**

---

## ✨ Features

### 🔬 Concept Scanner
Analyse any fashion concept by freely mixing garment + color + silhouette + print + fabric. The **smart concept parser** automatically decomposes your query, identifies the garment category, selects the right anchor term, and generates up to 5 optimised keywords for Google Trends.

```
Examples:
  rust linen kurti
  tiered anarkali with floral embroidery
  mustard sharara
  olive green georgette lehenga
  block print saree
```

### ⚔️ Head-to-Head Comparison
Compare 2–4 concepts side-by-side with overlaid trend charts, score breakdowns, and a summary table showing which concept has stronger momentum.

### 📋 Weekly Watchlist
Save concepts to a persistent watchlist. Run all tracked items in a single batch scan every week — results are appended to a historical Excel report (`watchlist_report.xlsx`) for longitudinal tracking.

### 🚨 Trend Alert System
Set a velocity threshold. When any concept's velocity (last-quarter vs first-quarter interest change) crosses your threshold, TrendIntel fires an alert — logged to `alerts.log` and displayed prominently in the dashboard.

### 🗺️ Regional Pulse
Scan the same concept across **8 Indian states** (Maharashtra, Delhi NCR, Karnataka, West Bengal, Tamil Nadu, Gujarat, Rajasthan, plus all-India) to see where demand is strongest before placing regional OTB.

### 🔗 Related Query Extraction
Surface Google's "related queries" — both **Top** (most searched alongside) and **Rising** (breakout searches) — to discover next-season leads you weren't looking for.

### 📊 Seasonal Calendar
A built-in OTB planning calendar mapped to India's festive + wedding + summer retail cycles, with peak-intensity scores for every month.

### 📑 Excel Report Export
Export full intelligence reports to formatted `.xlsx` files with conditional formatting, embedded charts, score breakdowns, and related query sheets.

---

## 🧮 Scoring Methodology

Google Trends returns a **0–100 relative interest index**, not raw search counts. TrendIntel computes a composite score from three components:

### Score Components

| Component | Weight | Formula | What It Captures |
|-----------|--------|---------|-----------------|
| **Volume** | 30% | `min(100, mean(series) / mean(anchor) × 100)` | Anchor-normalised search volume — corrects for scale differences between categories |
| **Momentum** | 40% | `clip((slope / (mean + ε)) × 1000 + 50, 0, 100)` | Linear regression slope normalised by mean — a +2 slope on a term averaging 5 is more significant than +2 on a term averaging 80 |
| **Recency** | 30% | `clip((mean(last_25%) / (mean(first_25%) + ε) − 0.5) × 66.7, 0, 100)` | Last-quarter vs first-quarter comparison — captures recent acceleration |

### Final Score
```
score = volume × 0.30 + momentum × 0.40 + recency × 0.30
```

### Velocity & Correlation
```
velocity = mean(last_25%) − mean(first_25%)    // raw index-point change, used for alerts
corr     = pearson(time_index, interest_values)  // trend linearity (-1 to +1)
```

### Buying Mandates

| Mandate | Condition | Action |
|---------|-----------|--------|
| **[BUY]** | score ≥ 65 AND velocity > 3 | Strong upward momentum. Increase OTB allocation. |
| **[BUY/HOLD]** | score ≥ 65 | High volume, velocity slowing. Commit current depth; don't chase more. |
| **[HOLD]** | score ≥ 40 AND velocity > 1 | Growing niche. Test buy at limited depth; review next cycle. |
| **[HOLD/WATCH]** | score ≥ 40 | Steady interest, no growth. Maintain inventory; no fresh buy. |
| **[WATCH]** | score ≥ 20 AND velocity > 0 | Low volume but slight uptick. Monitor 2 more weeks. |
| **[EXIT]** | everything else | Declining consumer intent. Clear stock; avoid fresh OTB. |

### Trend Horizon Classification

| Horizon | Condition |
|---------|-----------|
| Incoming — accelerating fast | velocity > 8 |
| Rising — early majority | velocity > 3 |
| Peak — current season | score > 55 AND velocity ≥ -2 |
| Declining — late cycle | velocity < -5 |
| Niche — stable micro-trend | everything else |

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                        Frontend (index.html)                   │
│   Chart.js · Vanilla CSS · Font Awesome · DM Serif + Syne     │
│   Dashboard · Scanner · Compare · Watchlist · Alerts · Maps    │
└──────────────────────────┬─────────────────────────────────────┘
                           │  REST API (JSON)
┌──────────────────────────▼─────────────────────────────────────┐
│                     Flask Backend (api.py)                      │
│   /api/scan · /api/compare · /api/regional · /api/watchlist    │
│   /api/alerts · /api/health                                    │
├────────────────────────────────────────────────────────────────┤
│                  Core Engine (trend_intelligence.py)            │
│   Smart Concept Parser · Scoring Engine · Alert System         │
│   Watchlist Manager · Excel Exporter · Chart Renderer          │
└──────────────────────────┬─────────────────────────────────────┘
                           │  pytrends (unofficial API)
┌──────────────────────────▼─────────────────────────────────────┐
│                    Google Trends                                │
│   Interest over time · Related queries · Regional breakdown     │
└────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
trendintel/
├── api.py                    # Flask REST API backend (488 lines)
├── index.html                # Single-page frontend dashboard (1013 lines)
├── trend_intelligence.py     # Core CLI engine + scoring logic (1088 lines)
├── requirements.txt          # Python dependencies
├── Procfile                  # Render/Heroku deployment config
└── output/                   # Generated charts, Excel reports, watchlist reports
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- pip

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/trend-intel.git
cd trend-intel
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the web dashboard
```bash
python api.py
```
Open **http://localhost:5000** — the full dashboard with live Google Trends data.

### 4. Or run the CLI version
```bash
python trend_intelligence.py
```
Interactive terminal interface with chart rendering, Excel export, and all v5.0 features.

---

## 🔌 API Reference

All endpoints accept and return JSON. Base URL: `http://localhost:5000`

| Method | Endpoint | Description | Key Parameters |
|--------|----------|-------------|----------------|
| `GET` | `/api/health` | Backend health check | — |
| `POST` | `/api/scan` | Scan a single concept | `concept`, `geo`, `tf`, `related`, `alert_threshold` |
| `POST` | `/api/compare` | Compare 2–4 concepts | `concepts[]`, `geo`, `tf` |
| `POST` | `/api/regional` | Scan across 8 Indian states | `concept`, `tf` |
| `GET` | `/api/watchlist` | Get watchlist items | — |
| `POST` | `/api/watchlist/add` | Add concept to watchlist | `concept`, `geo`, `tf` |
| `POST` | `/api/watchlist/remove` | Remove by index | `index` |
| `POST` | `/api/watchlist/run` | Run all watchlist items | `alert_threshold` |
| `GET` | `/api/alerts` | Get alert log (last 50) | — |
| `POST` | `/api/alerts/clear` | Clear all alerts | — |

### Geography Codes
| Code | Region |
|------|--------|
| `IN` | India (all) |
| `IN-MH` | Maharashtra |
| `IN-DL` | Delhi NCR |
| `IN-KA` | Karnataka |
| `IN-WB` | West Bengal |
| `IN-TN` | Tamil Nadu |
| `IN-GJ` | Gujarat |
| `IN-RJ` | Rajasthan |

### Timeframe Options
| Value | Period |
|-------|--------|
| `today 3-m` | Last 3 months |
| `today 12-m` | Last 12 months |
| `today 5-y` | Last 5 years |

---

## 🌐 Deploy (Free)

### Render.com (Recommended)

1. Push your code to a GitHub repository
2. Go to [render.com](https://render.com) → Sign up with GitHub
3. Click **New +** → **Web Service** → Connect your repo
4. Configure:
   ```
   Runtime:        Python 3
   Build command:  pip install -r requirements.txt
   Start command:  gunicorn api:app
   ```
5. Click **Create Web Service** — live in 3–5 minutes

> **Note:** The free Render tier sleeps after 15 minutes of inactivity. First request after sleep takes ~30 seconds to wake up — perfectly fine for demos and internal tools.

---

## 🧠 Smart Concept Parser

The parser decomposes any free-text fashion query into structured attributes:

| Attribute | Examples in Library |
|-----------|-------------------|
| **Garments** | kurti, saree, anarkali, lehenga, sharara, palazzo, co-ord set, dupatta, blouse |
| **Colors** | indigo, rust, olive, mustard, terracotta, ivory, sage, blush, coral, teal, navy, burgundy, mauve... |
| **Silhouettes** | tiered, flared, fitted, a-line, straight, oversized, wrap, peplum, asymmetric, cape, draped... |
| **Prints & Techniques** | block print, floral, geometric, paisley, ikat, bandhani, shibori, kalamkari, ajrakh, mirror work, zari... |
| **Fabrics** | linen, cotton, silk, chiffon, georgette, crepe, rayon, chanderi, mul, khadi, tussar, organza... |

The parser uses this decomposition to generate up to **5 keyword variants** for Google Trends and selects the appropriate **anchor term** (e.g., "kurti" for kurti queries, "ethnic wear india" for uncategorised concepts) for anchor-normalised scoring.

---

## ⚙️ Technical Details

### Rate Limit Handling
Google Trends enforces rate limits. TrendIntel handles this with:
- **Exponential backoff** on 429 errors (5s → 10s → 20s → 40s)
- **Polite delays** between API calls (3–15 seconds)
- **Anchor caching** in watchlist scans to avoid redundant fetches
- **Consecutive failure detection** — backs off to 60s cooldown after 2+ rate-limit hits

### urllib3 v2 Compatibility
Includes a runtime patch for the `method_whitelist` → `allowed_methods` rename in urllib3 v2, which breaks older pytrends versions on Python 3.12+.

### Windows Font Fix (v5.0)
All emoji characters in matplotlib chart text replaced with ASCII equivalents to prevent `UserWarning: Glyph missing from font` spam on Windows systems lacking DejaVu Sans emoji glyphs.

---

## 📦 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| Flask | 3.0.3 | Web backend |
| Flask-CORS | 4.0.1 | Cross-origin requests |
| pytrends | 4.9.2 | Google Trends unofficial API |
| pandas | 2.2.2 | Data manipulation |
| numpy | 1.26.4 | Numerical computation |
| matplotlib | 3.9.0 | Chart rendering (CLI mode) |
| scipy | 1.13.1 | Statistical analysis |
| openpyxl | 3.1.4 | Excel export |
| gunicorn | 22.0.0 | Production WSGI server |

---

## 📖 Project Context

> **Graduation Project (Dec 2024 – Apr 2025)**
>
> *Data-Centric, Resource-Efficient AI Framework for Competitive Value Retail*

Built during a **16-week internship** at an ethnic value retail company in India. Born from a real gap observed on the buying floor — the buying team had no access to emerging consumer demand signals, relying entirely on historic sales data and qualitative guesswork.

### Development Timeline

| Phase | Period | Milestone |
|-------|--------|-----------|
| Gap identification | Dec 2024 – Jan 2025 | Observed buying process; identified absence of emerging trend signals |
| v1–v3 | Jan – Feb 2025 | Basic pytrends scanner; fixed urllib3, rate limits, negative score bugs |
| v4 | Feb – Mar 2025 | Smart concept parser; anchor normalisation; color/silhouette/print detection |
| v5 | Mar – Apr 2025 | Related query extraction; weekly watchlist; velocity alert system; web dashboard |
| Submission | Apr 2025 | Graduation project thesis |

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

---

<div align="center">

**Built with ❤️ for India's ethnic value retail market**

*₹0 license cost · Open-source data · Regional granularity · Actionable mandates*

</div>
]]>
