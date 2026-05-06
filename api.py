"""
Fashion Trend Intelligence v5.0 — Flask API Backend
Run locally:  python api.py
Deploy:       gunicorn api:app
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd, numpy as np, time, os, json, re, sys, warnings
from datetime import datetime

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
#  URLLIB3 PATCH  (must run before pytrends)
# ─────────────────────────────────────────────
def _patch_urllib3():
    try:
        from urllib3.util.retry import Retry
        _orig = Retry.__init__
        def _new(self, *a, **kw):
            if "method_whitelist" in kw:
                kw["allowed_methods"] = kw.pop("method_whitelist")
            _orig(self, *a, **kw)
        Retry.__init__ = _new
    except Exception:
        pass
_patch_urllib3()

try:
    from pytrends.request import TrendReq
    PYTRENDS_OK = True
except ImportError:
    PYTRENDS_OK = False

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
OUTPUT_DIR   = "output"
WATCHLIST_FILE = "watchlist.json"
ALERTS_LOG   = "alerts.log"
os.makedirs(OUTPUT_DIR, exist_ok=True)
DEFAULT_THRESHOLD = 10.0

CATEGORY_ANCHORS = {
    "kurti":"kurti","kurta":"kurta","saree":"saree","lehenga":"lehenga",
    "anarkali":"anarkali","salwar":"salwar suit","sharara":"sharara",
    "palazzo":"palazzo pants","dupatta":"dupatta","blouse":"blouse design",
    "coord":"co-ord set","co-ord":"co-ord set","default":"ethnic wear india",
}
COLORS = {"indigo","rust","olive","mustard","terracotta","ivory","sage","blush",
    "coral","teal","navy","burgundy","mauve","ochre","ecru","cobalt",
    "red","blue","green","yellow","pink","black","white","grey","gray",
    "orange","purple","lilac","peach","beige","cream","brown","maroon"}
SILHOUETTES = {"tiered","flared","fitted","a-line","straight","oversized","wrap",
    "peplum","asymmetric","cape","draped","layered","balloon","boxy"}
PRINTS = {"block print","floral","geometric","abstract","paisley","ikat","bandhani",
    "shibori","kalamkari","ajrakh","batik","stripes","checks","polka",
    "mirror work","embroidery","zari","gota","thread work","sequin"}
FABRICS = {"linen","cotton","silk","chiffon","georgette","crepe","rayon","chanderi",
    "mul","khadi","tussar","organza","velvet","brocade","net"}

GEO_MAP = {
    "IN":"India","IN-MH":"Maharashtra","IN-DL":"Delhi NCR",
    "IN-KA":"Karnataka","IN-WB":"West Bengal","IN-TN":"Tamil Nadu",
    "IN-GJ":"Gujarat","IN-RJ":"Rajasthan",
}

# ─────────────────────────────────────────────
#  CORE FUNCTIONS
# ─────────────────────────────────────────────
def make_pytrends():
    if not PYTRENDS_OK:
        raise RuntimeError("pytrends not installed")
    for kw in [
        {"hl":"en-IN","tz":330,"timeout":(30,90),"retries":2,"backoff_factor":0.5},
        {"hl":"en-IN","tz":330,"timeout":(30,90)},
        {"hl":"en-IN","tz":330},
    ]:
        try:
            return TrendReq(**kw)
        except TypeError:
            continue
    raise RuntimeError("Cannot initialise TrendReq")

def parse_concept(raw):
    text = raw.lower().strip()
    found = {"garment":None,"color":[],"silhouette":[],"print":[],"fabric":[],"raw":raw}
    for p in sorted(PRINTS, key=lambda x: -len(x)):
        if p in text:
            found["print"].append(p)
            text = text.replace(p, "")
    for w in re.sub(r"[^\w\s]","",text).split():
        if w in COLORS:         found["color"].append(w)
        elif w in SILHOUETTES:  found["silhouette"].append(w)
        elif w in FABRICS:      found["fabric"].append(w)
    for key in CATEGORY_ANCHORS:
        if key in raw.lower():
            found["garment"] = key
            break
    keywords = [raw]
    g = found["garment"]
    if g:
        if found["color"]:      keywords.append(f"{found['color'][0]} {g}")
        if found["silhouette"]: keywords.append(f"{found['silhouette'][0]} {g}")
        if found["print"]:      keywords.append(f"{found['print'][0]} {g}")
        if found["fabric"]:     keywords.append(f"{found['fabric'][0]} {g}")
    else:
        keywords.append(f"{raw} india")
        if found["color"]:  keywords.append(f"{found['color'][0]} ethnic wear")
        if found["fabric"]: keywords.append(f"{found['fabric'][0]} kurti")
    seen = []
    for k in keywords:
        k = k.strip()
        if k and k not in seen: seen.append(k)
    found["keywords"] = seen[:5]
    found["anchor"] = CATEGORY_ANCHORS.get(found["garment"] or "default", CATEGORY_ANCHORS["default"])
    return found

def fetch_with_backoff(pt, keyword, geo, timeframe, max_retries=4):
    for attempt in range(max_retries):
        try:
            pt.build_payload([keyword], geo=geo, timeframe=timeframe)
            df = pt.interest_over_time()
            if not df.empty and keyword in df.columns:
                return df[[keyword]]
            return pd.DataFrame()
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "too many" in err or "rate" in err:
                wait = (2**attempt) * 5
                time.sleep(wait)
            else:
                return pd.DataFrame()
    return pd.DataFrame()

def compute_score(series, anchor_series=None):
    y = series.values.astype(float)
    n = len(y)
    if n < 4:
        return {"score":0,"volume":0,"momentum":0,"recency":0,"velocity":0,"corr":0,"slope":0}
    x = np.arange(n)
    raw_vol = float(np.mean(y))
    if anchor_series is not None and len(anchor_series) >= 4:
        anch = max(1.0, float(np.mean(anchor_series.values)))
        vol  = min(100.0, (raw_vol / anch) * 100)
    else:
        vol = raw_vol
    slope, _ = np.polyfit(x, y, 1)
    mom = float(np.clip((slope/(raw_vol+1e-6))*1000 + 50, 0, 100))
    q       = max(1, n // 4)
    last_q  = float(np.mean(y[-q:]))
    first_q = float(np.mean(y[:q]))
    rec     = float(np.clip((last_q/(first_q+1e-6) - 0.5)*66.7, 0, 100))
    score   = float(np.clip(vol*0.30 + mom*0.40 + rec*0.30, 0, 100))
    vel     = float(last_q - first_q)
    try:
        corr = float(np.corrcoef(x, y)[0,1])
        if np.isnan(corr): corr = 0.0
    except Exception:
        corr = 0.0
    return {
        "score":    round(score,1),
        "volume":   round(vol,1),
        "momentum": round(mom,1),
        "recency":  round(rec,1),
        "velocity": round(vel,2),
        "corr":     round(corr,3),
        "slope":    round(float(slope),4),
    }

def get_mandate(score, velocity, corr):
    if score >= 65 and velocity > 3:
        return {"label":"[BUY]","confidence":"High",
                "rationale":"Strong upward momentum + rising recency demand. Increase OTB allocation."}
    if score >= 65:
        return {"label":"[BUY/HOLD]","confidence":"Medium-High",
                "rationale":"High volume, velocity slowing. Commit current depth; don't chase more."}
    if score >= 40 and velocity > 1:
        return {"label":"[HOLD]","confidence":"Medium",
                "rationale":"Growing niche. Test buy at limited depth this season; review next cycle."}
    if score >= 40:
        return {"label":"[HOLD/WATCH]","confidence":"Medium",
                "rationale":"Steady interest, no growth. Maintain inventory; no fresh buy yet."}
    if score >= 20 and velocity > 0:
        return {"label":"[WATCH]","confidence":"Low",
                "rationale":"Low volume but slight uptick. Monitor 2 more weeks before OTB commit."}
    return {"label":"[EXIT]","confidence":"High",
            "rationale":"Declining/low consumer intent. Clear stock; avoid fresh OTB."}

def get_horizon(score, velocity):
    if velocity > 8:  return "Incoming — accelerating fast"
    if velocity > 3:  return "Rising — early majority"
    if score > 55 and velocity >= -2: return "Peak — current season"
    if velocity < -5: return "Declining — late cycle"
    return "Niche — stable micro-trend"

def detect_seasonality(series):
    if series.empty: return "Unknown"
    try:
        s = series.copy()
        s.index = pd.to_datetime(s.index)
        m = s.idxmax().month
        if m in {8,9,10,11}:  return "Festive season peak (Aug-Nov)"
        if m in {11,12,1,2}:  return "Wedding season peak (Nov-Feb)"
        return f"Peak in month {m}"
    except Exception:
        return "Unknown"

def fire_alert(concept, score_dict, threshold=DEFAULT_THRESHOLD):
    velocity = score_dict.get("velocity", 0)
    score    = score_dict.get("score", 0)
    if abs(velocity) >= threshold:
        direction = "SURGE" if velocity > 0 else "DROP"
        mandate   = get_mandate(score, velocity, score_dict.get("corr", 0))
        msg = (f"[{datetime.now():%Y-%m-%d %H:%M}]  "
               f"ALERT {direction}: '{concept}'  "
               f"vel={velocity:+.1f}  score={score}  mandate={mandate['label']}\n")
        with open(ALERTS_LOG, "a", encoding="utf-8") as f:
            f.write(msg)
        return {"fired": True, "direction": direction, "velocity": velocity}
    return {"fired": False}

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_watchlist(items):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

def fetch_related(pt, keyword, geo, timeframe):
    result = {"top": [], "rising": []}
    try:
        pt.build_payload([keyword], geo=geo, timeframe=timeframe)
        rq = pt.related_queries()
        if keyword in rq:
            top    = rq[keyword].get("top",    pd.DataFrame()) or pd.DataFrame()
            rising = rq[keyword].get("rising", pd.DataFrame()) or pd.DataFrame()
            if not top.empty and "query" in top.columns:
                result["top"]    = top.head(8).to_dict("records")
            if not rising.empty and "query" in rising.columns:
                result["rising"] = rising.head(8).to_dict("records")
    except Exception:
        pass
    return result

# ─────────────────────────────────────────────
#  FLASK APP
# ─────────────────────────────────────────────
app = Flask(__name__, static_folder=".")
CORS(app)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# ── HEALTH CHECK ──
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "pytrends": PYTRENDS_OK,
                    "time": datetime.now().isoformat()})

# ── SCAN ──
@app.route("/api/scan", methods=["POST"])
def scan():
    data      = request.json or {}
    concept   = data.get("concept", "").strip()
    geo       = data.get("geo", "IN")
    tf        = data.get("tf",  "today 12-m")
    do_related= bool(data.get("related", False))
    threshold = float(data.get("alert_threshold", DEFAULT_THRESHOLD))

    if not concept:
        return jsonify({"error": "Please enter a concept."}), 400
    if not PYTRENDS_OK:
        return jsonify({"error": "pytrends not installed on server."}), 500

    parsed = parse_concept(concept)
    kw     = parsed["keywords"][0]
    anchor = parsed["anchor"]

    try:
        pt = make_pytrends()
    except Exception as e:
        return jsonify({"error": f"Cannot connect to Google Trends: {str(e)}"}), 500

    # anchor
    adf      = fetch_with_backoff(pt, anchor, geo, tf)
    anchor_s = (adf[anchor] if not adf.empty and anchor in adf.columns
                else pd.Series(dtype=float))
    time.sleep(4)

    # main keyword
    df = fetch_with_backoff(pt, kw, geo, tf)
    if df.empty or kw not in df.columns:
        return jsonify({"error": f"No Google Trends data found for '{concept}'. Try a broader term like just the garment name."}), 404

    sc       = compute_score(df[kw], anchor_s)
    mandate  = get_mandate(sc["score"], sc["velocity"], sc["corr"])
    horizon  = get_horizon(sc["score"], sc["velocity"])
    seasonal = detect_seasonality(df[kw])
    alert    = fire_alert(concept, sc, threshold)

    related = {"top": [], "rising": []}
    if do_related:
        time.sleep(3)
        related = fetch_related(pt, kw, geo, tf)

    return jsonify({
        "score":    sc,
        "mandate":  mandate,
        "horizon":  horizon,
        "seasonal": seasonal,
        "alert":    alert,
        "parsed":   {k: parsed[k] for k in ["garment","color","silhouette","print","fabric","keywords","anchor"]},
        "series":   [int(v) for v in df[kw].fillna(0).tolist()],
        "dates":    [str(d)[:10] for d in df.index.tolist()],
        "related":  related,
        "geo_label": GEO_MAP.get(geo, geo),
    })

# ── COMPARE ──
@app.route("/api/compare", methods=["POST"])
def compare():
    data     = request.json or {}
    concepts = [c.strip() for c in data.get("concepts", []) if c.strip()][:4]
    geo      = data.get("geo", "IN")
    tf       = data.get("tf",  "today 12-m")

    if len(concepts) < 2:
        return jsonify({"error": "Enter at least 2 concepts."}), 400
    if not PYTRENDS_OK:
        return jsonify({"error": "pytrends not installed."}), 500

    try:
        pt = make_pytrends()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    results = []
    for concept in concepts:
        parsed = parse_concept(concept)
        kw     = parsed["keywords"][0]
        df     = fetch_with_backoff(pt, kw, geo, tf)
        time.sleep(5)
        if not df.empty and kw in df.columns:
            sc  = compute_score(df[kw])
            man = get_mandate(sc["score"], sc["velocity"], sc["corr"])
            results.append({
                "concept": concept, "score": sc, "mandate": man,
                "series":  [int(v) for v in df[kw].fillna(0).tolist()],
                "dates":   [str(d)[:10] for d in df.index.tolist()],
            })
        else:
            results.append({"concept": concept, "error": "no data", "score": None, "mandate": None})

    return jsonify({"results": results})

# ── REGIONAL ──
@app.route("/api/regional", methods=["POST"])
def regional():
    data    = request.json or {}
    concept = data.get("concept", "").strip()
    tf      = data.get("tf", "today 12-m")

    if not concept:
        return jsonify({"error": "Enter a concept."}), 400
    if not PYTRENDS_OK:
        return jsonify({"error": "pytrends not installed."}), 500

    REGIONS = [
        ("India",       "IN"),  ("Maharashtra", "IN-MH"),
        ("Delhi NCR",   "IN-DL"),("Karnataka",  "IN-KA"),
        ("West Bengal", "IN-WB"),("Tamil Nadu",  "IN-TN"),
        ("Gujarat",     "IN-GJ"),("Rajasthan",   "IN-RJ"),
    ]

    parsed = parse_concept(concept)
    kw     = parsed["keywords"][0]
    results = []

    try:
        pt = make_pytrends()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    for name, geo in REGIONS:
        df = fetch_with_backoff(pt, kw, geo, tf)
        time.sleep(6)
        if not df.empty and kw in df.columns:
            sc = compute_score(df[kw])
            results.append({"region": name, "geo": geo,
                            "score": sc["score"], "velocity": sc["velocity"]})
        else:
            results.append({"region": name, "geo": geo, "score": 0, "velocity": 0})

    return jsonify({"concept": concept, "keyword": kw, "results": results})

# ── WATCHLIST ──
@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    return jsonify(load_watchlist())

@app.route("/api/watchlist/add", methods=["POST"])
def add_to_watchlist():
    item = request.json or {}
    if not item.get("concept", "").strip():
        return jsonify({"error": "No concept provided"}), 400
    wl = load_watchlist()
    item["added"] = datetime.now().isoformat()
    item["score"] = None
    item["velocity"] = None
    wl.append(item)
    save_watchlist(wl)
    return jsonify({"ok": True, "count": len(wl)})

@app.route("/api/watchlist/remove", methods=["POST"])
def remove_from_watchlist():
    idx = request.json.get("index", -1)
    wl  = load_watchlist()
    try:
        wl.pop(int(idx))
        save_watchlist(wl)
        return jsonify({"ok": True})
    except (IndexError, ValueError):
        return jsonify({"error": "Invalid index"}), 400

@app.route("/api/watchlist/run", methods=["POST"])
def run_watchlist_api():
    threshold = float((request.json or {}).get("alert_threshold", DEFAULT_THRESHOLD))
    wl = load_watchlist()
    if not wl:
        return jsonify({"error": "Watchlist is empty"}), 400
    if not PYTRENDS_OK:
        return jsonify({"error": "pytrends not installed"}), 500

    try:
        pt = make_pytrends()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    for item in wl:
        parsed = parse_concept(item["concept"])
        kw     = parsed["keywords"][0]
        df     = fetch_with_backoff(pt, kw, item.get("geo","IN"), item.get("tf","today 12-m"))
        time.sleep(8)
        if not df.empty and kw in df.columns:
            sc = compute_score(df[kw])
            item["score"]    = sc["score"]
            item["velocity"] = sc["velocity"]
            item["mandate"]  = get_mandate(sc["score"], sc["velocity"], sc["corr"])["label"]
            fire_alert(item["concept"], sc, threshold)
        else:
            item["score"]    = None
            item["velocity"] = None
            item["mandate"]  = "NO DATA"

    save_watchlist(wl)
    return jsonify(wl)

# ── ALERTS ──
@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    if not os.path.exists(ALERTS_LOG):
        return jsonify([])
    with open(ALERTS_LOG, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    return jsonify(lines[-50:])

@app.route("/api/alerts/clear", methods=["POST"])
def clear_alerts():
    if os.path.exists(ALERTS_LOG):
        open(ALERTS_LOG, "w").close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  Fashion Trend Intelligence v5.0 — Starting...")
    print("  Open: http://localhost:5000")
    print("="*55 + "\n")
    app.run(debug=True, port=5000)
