"""
╔══════════════════════════════════════════════════════════════╗
║        FASHION TREND INTELLIGENCE  v5.0                      ║
║        Ethnic & Value Retail · India Market                  ║
╚══════════════════════════════════════════════════════════════╝

NEW in v5.0:
  - Related Query Extraction  — surfaces "what else people search" 
    alongside your concept; reveals next-season leads automatically
  - Weekly Watchlist          — save concepts to watchlist.json, run 
    all of them in one go every Sunday; appends history to Excel
  - Trend Alert System        — after every scan, checks if velocity 
    crossed your threshold; writes alerts.log + prints WARNING in red

FIXED in v5.0:
  - Emoji font warnings on Windows (DejaVu Sans missing glyphs)
    All emojis in chart text replaced with ASCII equivalents so the
    PNG saves cleanly on every OS without UserWarning spam.

Previous fixes (v4.x):
  - urllib3 v2 method_whitelist crash (Python 3.12/3.14)
  - Negative-only scores: anchor-normalised composite scoring
  - Color/silhouette/print blindness: smart concept parser
  - Rate-limit crashes: exponential backoff
  - matplotlib layout warnings: gridspec

INSTALL (run once in VSCode terminal):
  pip install pytrends pandas matplotlib scipy numpy openpyxl
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("TkAgg")          # explicit backend — avoids blank window on some Windows setups
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import os, time, re, sys, json, warnings
from datetime import datetime, date

# Suppress ALL font/glyph warnings — we've replaced emojis in chart text
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

# ─────────────────────────────────────────────
#  URLLIB3 v2 PATCH  (must run before pytrends import)
# ─────────────────────────────────────────────
def _patch_urllib3_retry():
    try:
        from urllib3.util.retry import Retry
        _orig = Retry.__init__
        def _new(self, *a, **kw):
            if "method_whitelist" in kw:
                kw["allowed_methods"] = kw.pop("method_whitelist") if "allowed_methods" not in kw else kw.pop("method_whitelist") and kw["allowed_methods"]
            _orig(self, *a, **kw)
        Retry.__init__ = _new
    except Exception:
        pass

_patch_urllib3_retry()

# ─────────────────────────────────────────────
#  OPTIONAL IMPORTS
# ─────────────────────────────────────────────
try:
    from pytrends.request import TrendReq
    PYTRENDS_OK = True
except ImportError:
    PYTRENDS_OK = False
    print("WARNING: pytrends not installed. Run:  pip install pytrends")

try:
    import openpyxl
    OPENPYXL_OK = True
except ImportError:
    OPENPYXL_OK = False

# ─────────────────────────────────────────────
#  PATHS & CONFIG
# ─────────────────────────────────────────────
OUTPUT_DIR    = "output"
WATCHLIST_FILE = "watchlist.json"
ALERTS_LOG    = "alerts.log"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Default alert threshold: if velocity >= this value, fire an alert
DEFAULT_ALERT_THRESHOLD = 10.0

TIMEFRAME_OPTIONS = {
    "1": ("today 3-m",  "Last 3 months"),
    "2": ("today 12-m", "Last 12 months"),
    "3": ("today 5-y",  "Last 5 years"),
}

GEO_OPTIONS = {
    "1": ("IN",    "India (all)"),
    "2": ("IN-MH", "Maharashtra"),
    "3": ("IN-DL", "Delhi NCR"),
    "4": ("IN-KA", "Karnataka"),
    "5": ("IN-WB", "West Bengal"),
    "6": ("IN-TN", "Tamil Nadu"),
    "7": ("IN-GJ", "Gujarat"),
    "8": ("IN-RJ", "Rajasthan"),
}

CATEGORY_ANCHORS = {
    "kurti":    "kurti",
    "kurta":    "kurta",
    "saree":    "saree",
    "lehenga":  "lehenga",
    "anarkali": "anarkali",
    "salwar":   "salwar suit",
    "sharara":  "sharara",
    "palazzo":  "palazzo pants",
    "dupatta":  "dupatta",
    "blouse":   "blouse design",
    "coord":    "co-ord set",
    "co-ord":   "co-ord set",
    "default":  "ethnic wear india",
}

COLORS = {
    "indigo","rust","olive","mustard","terracotta","ivory","sage","blush",
    "coral","teal","navy","burgundy","mauve","ochre","ecru","cobalt",
    "red","blue","green","yellow","pink","black","white","grey","gray",
    "orange","purple","lilac","peach","beige","cream","brown","maroon",
}
SILHOUETTES = {
    "tiered","flared","fitted","a-line","straight","oversized","wrap",
    "peplum","asymmetric","cape","draped","layered","balloon","boxy",
}
PRINTS = {
    "block print","floral","geometric","abstract","paisley","ikat","bandhani",
    "shibori","kalamkari","ajrakh","batik","stripes","checks","polka",
    "mirror work","embroidery","zari","gota","thread work","sequin",
}
FABRICS = {
    "linen","cotton","silk","chiffon","georgette","crepe","rayon","chanderi",
    "mul","khadi","tussar","organza","velvet","brocade","net",
}

# ─────────────────────────────────────────────
#  TRENDREQ FACTORY
# ─────────────────────────────────────────────
def make_pytrends():
    if not PYTRENDS_OK:
        raise RuntimeError("pytrends not installed. Run: pip install pytrends")
    for kw in [
        {"hl":"en-IN","tz":330,"timeout":(30,90),"retries":2,"backoff_factor":0.5},
        {"hl":"en-IN","tz":330,"timeout":(30,90)},
        {"hl":"en-IN","tz":330},
    ]:
        try:
            return TrendReq(**kw)
        except TypeError:
            continue
    raise RuntimeError("Cannot initialise TrendReq — check pytrends version.")

# ─────────────────────────────────────────────
#  SMART CONCEPT PARSER
# ─────────────────────────────────────────────
def parse_concept(raw: str) -> dict:
    text = raw.lower().strip()
    found = {"garment":None,"color":[],"silhouette":[],"print":[],"fabric":[],"raw":raw}

    for p in sorted(PRINTS, key=lambda x: -len(x)):
        if p in text:
            found["print"].append(p)
            text = text.replace(p, "")

    for w in re.sub(r"[^\w\s]","",text).split():
        if w in COLORS:           found["color"].append(w)
        elif w in SILHOUETTES:    found["silhouette"].append(w)
        elif w in FABRICS:        found["fabric"].append(w)

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
        if raw.lower() not in {"garment","silhouette","print","fabric","color"}:
            keywords.append(f"{raw} india")
        if found["color"]:  keywords.append(f"{found['color'][0]} ethnic wear")
        if found["fabric"]: keywords.append(f"{found['fabric'][0]} kurti")

    seen = []
    for k in keywords:
        k = k.strip()
        if k and k not in seen:
            seen.append(k)
    found["keywords"] = seen[:5]
    found["anchor"]   = CATEGORY_ANCHORS.get(found["garment"] or "default",
                                              CATEGORY_ANCHORS["default"])
    return found

# ─────────────────────────────────────────────
#  SCORING ENGINE
# ─────────────────────────────────────────────
def compute_score(series: pd.Series, anchor_series: pd.Series = None) -> dict:
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

    score = float(np.clip(vol*0.30 + mom*0.40 + rec*0.30, 0, 100))
    vel   = float(last_q - first_q)

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

def get_mandate(score, velocity, corr) -> dict:
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

def get_horizon(score, velocity) -> str:
    if velocity > 8:  return "Incoming — accelerating fast"
    if velocity > 3:  return "Rising — early majority"
    if score > 55 and velocity >= -2: return "Peak — current season"
    if velocity < -5: return "Declining — late cycle"
    return "Niche — stable micro-trend"

def detect_seasonality(series: pd.Series) -> str:
    if series.empty: return "Unknown"
    try:
        s = series.copy()
        s.index = pd.to_datetime(s.index)
        m = s.idxmax().month
        if m in {8,9,10,11}:  return "Festive season peak (Aug-Nov)"
        if m in {11,12,1,2}:  return "Wedding season peak (Nov-Feb)"
        return f"Peak in month {m} (off-season)"
    except Exception:
        return "Unknown"

# ─────────────────────────────────────────────
#  PYTRENDS FETCHER
# ─────────────────────────────────────────────
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
                print(f"  Rate limited. Waiting {wait}s (retry {attempt+1}/{max_retries})...")
                time.sleep(wait)
            else:
                print(f"  Error for '{keyword}': {e}")
                return pd.DataFrame()
    print(f"  Failed after {max_retries} attempts for '{keyword}'")
    return pd.DataFrame()

# ─────────────────────────────────────────────
#  NEW: RELATED QUERY EXTRACTION
# ─────────────────────────────────────────────
def fetch_related_queries(pt, keyword, geo, timeframe) -> dict:
    """
    Fetches Google Trends 'related queries' for a keyword.
    Returns dict with 'top' and 'rising' DataFrames.
    These are what people search alongside/after your keyword —
    invaluable for spotting next-season leads.
    """
    result = {"top": pd.DataFrame(), "rising": pd.DataFrame()}
    try:
        pt.build_payload([keyword], geo=geo, timeframe=timeframe)
        rq = pt.related_queries()
        if keyword in rq:
            result["top"]    = rq[keyword].get("top",    pd.DataFrame()) or pd.DataFrame()
            result["rising"] = rq[keyword].get("rising", pd.DataFrame()) or pd.DataFrame()
    except Exception as e:
        print(f"  Related queries unavailable for '{keyword}': {e}")
    return result

def print_related_queries(related: dict, keyword: str):
    """Prints related queries in a formatted terminal table."""
    print(f"\n  ── Related Queries for: {keyword.upper()} ──")

    top    = related.get("top",    pd.DataFrame())
    rising = related.get("rising", pd.DataFrame())

    if not top.empty and "query" in top.columns:
        print("\n  TOP (most searched alongside):")
        for _, row in top.head(8).iterrows():
            val = str(row.get("value","")).strip()
            qry = str(row.get("query","")).strip()
            print(f"    {qry:<40} value: {val}")
    else:
        print("  TOP: no data")

    if not rising.empty and "query" in rising.columns:
        print("\n  RISING (breakout searches — next-season leads):")
        for _, row in rising.head(8).iterrows():
            val = str(row.get("value","")).strip()
            qry = str(row.get("query","")).strip()
            tag = "  <-- BREAKOUT" if val == "Breakout" else ""
            print(f"    {qry:<40} value: {val}{tag}")
    else:
        print("  RISING: no data")

def export_related_to_excel(ws_parent, related: dict, keyword: str):
    """Adds a Related Queries sheet to an existing workbook."""
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = ws_parent.parent
    ws = wb.create_sheet(f"Related - {keyword[:20]}")

    TEAL = "FF00796B"
    def hdr(r, c, v):
        cell = ws.cell(row=r, column=c, value=v)
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.alignment = Alignment(horizontal="center")

    ws.cell(row=1, column=1,
            value=f"Related Queries — {keyword}").font = Font(bold=True, size=12)

    hdr(3,1,"Type"); hdr(3,2,"Query"); hdr(3,3,"Value")
    ws.column_dimensions["B"].width = 40

    row = 4
    for kind, df in [("Top", related.get("top", pd.DataFrame())),
                     ("Rising", related.get("rising", pd.DataFrame()))]:
        if not df.empty and "query" in df.columns:
            for _, r in df.head(10).iterrows():
                ws.cell(row=row, column=1, value=kind)
                ws.cell(row=row, column=2, value=str(r.get("query","")))
                ws.cell(row=row, column=3, value=str(r.get("value","")))
                row += 1

# ─────────────────────────────────────────────
#  NEW: WEEKLY WATCHLIST
# ─────────────────────────────────────────────
def load_watchlist() -> list:
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_watchlist(items: list):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

def manage_watchlist():
    """Interactive watchlist manager — add, remove, view, run."""
    while True:
        items = load_watchlist()
        print("\n" + "─"*62)
        print("  WEEKLY WATCHLIST MANAGER")
        print("─"*62)
        if items:
            for i, it in enumerate(items, 1):
                print(f"  {i:>2}. {it['concept']:<38} geo={it.get('geo','IN')}  tf={it.get('tf','today 12-m')}")
        else:
            print("  (watchlist is empty)")
        print("\n  a. Add concept      r. Remove concept")
        print("  s. Run watchlist    b. Back to main menu")
        ch = input("\n  Choose: ").strip().lower()

        if ch == "a":
            while True:
                concept = input("  Concept to track (min 3 chars, e.g. 'rust kurti'): ").strip()
                if len(concept) < 3:
                    print("  Too short — please enter a real fashion concept (e.g. 'tiered anarkali')")
                    continue
                if concept.lower() in {"s","a","r","b","1","2","3","4","5"}:
                    print("  That looks like a menu key, not a concept. Try e.g. 'indigo block print kurti'")
                    continue
                break
            geo_choice = input("  Geography [1-8, default 1]: ").strip() or "1"
            geo, _ = GEO_OPTIONS.get(geo_choice, GEO_OPTIONS["1"])
            tf_choice  = input("  Timeframe [1/2/3, default 2]: ").strip() or "2"
            tf, _  = TIMEFRAME_OPTIONS.get(tf_choice, TIMEFRAME_OPTIONS["2"])
            alert_v = input(f"  Alert velocity threshold [default {DEFAULT_ALERT_THRESHOLD}]: ").strip()
            try:    alert_v = float(alert_v)
            except: alert_v = DEFAULT_ALERT_THRESHOLD
            items.append({"concept": concept, "geo": geo, "tf": tf,
                          "alert_threshold": alert_v,
                          "added": datetime.now().isoformat()})
            save_watchlist(items)
            print(f"  Added: {concept}")

        elif ch == "r":
            idx = input("  Remove item number: ").strip()
            try:
                items.pop(int(idx)-1)
                save_watchlist(items)
                print("  Removed.")
            except Exception:
                print("  Invalid number.")

        elif ch == "s":
            run_watchlist_scan(items)

        elif ch == "b":
            break

def run_watchlist_scan(items: list):
    """Runs all watchlist items and appends results to watchlist_report.xlsx."""
    if not items:
        print("  Watchlist is empty. Add concepts first.")
        return
    if not PYTRENDS_OK:
        print("  pytrends not installed.")
        return

    print(f"\n  Running watchlist scan — {len(items)} concept(s) — {datetime.now():%d %b %Y %H:%M}")
    print("  "+"─"*58)

    try:
        pt = make_pytrends()
    except Exception as e:
        print(f"  Cannot connect: {e}")
        return

    results      = []
    anchor_cache = {}          # cache anchors — avoids re-fetching same parent term
    consecutive_fails = 0      # track back-to-back failures to detect sustained rate-limit

    for idx_item, item in enumerate(items):
        concept = item["concept"]
        geo     = item.get("geo", "IN")
        tf      = item.get("tf", "today 12-m")
        thresh  = item.get("alert_threshold", DEFAULT_ALERT_THRESHOLD)

        print(f"\n  Scanning: {concept}  (geo={geo})")
        parsed = parse_concept(concept)
        kw     = parsed["keywords"][0]
        anchor = parsed["anchor"]

        # ── Anchor: use cache, skip if already known to be rate-limited ──
        cache_key = f"{anchor}|{geo}|{tf}"
        if cache_key in anchor_cache:
            anchor_s = anchor_cache[cache_key]
            print(f"  (anchor '{anchor}' from cache)")
        elif consecutive_fails >= 2:
            print(f"  (skipping anchor fetch — rate-limited, will retry next run)")
            anchor_s = pd.Series(dtype=float)
        else:
            print(f"  Fetching anchor: '{anchor}'...")
            adf = fetch_with_backoff(pt, anchor, geo, tf)
            anchor_s = (adf[anchor]
                        if not adf.empty and anchor in adf.columns
                        else pd.Series(dtype=float))
            anchor_cache[cache_key] = anchor_s
            time.sleep(8)   # polite gap after anchor fetch

        # ── Main keyword fetch ──
        df = fetch_with_backoff(pt, kw, geo, tf)
        if not df.empty and kw in df.columns:
            consecutive_fails = 0
            sc  = compute_score(df[kw], anchor_s)
            man = get_mandate(sc["score"], sc["velocity"], sc["corr"])
            hor = get_horizon(sc["score"], sc["velocity"])
            print(f"    score={sc['score']}  vel={sc['velocity']:+.1f}  {man['label']}")
            check_and_fire_alert(concept, sc, thresh)
            results.append({
                "date":      datetime.now().strftime("%d-%b-%Y"),
                "concept":   concept,
                "geo":       geo,
                "score":     sc["score"],
                "velocity":  sc["velocity"],
                "momentum":  sc["momentum"],
                "recency":   sc["recency"],
                "corr":      sc["corr"],
                "mandate":   man["label"],
                "horizon":   hor,
            })
        else:
            consecutive_fails += 1
            print(f"    No data for '{kw}'")
            results.append({"date": datetime.now().strftime("%d-%b-%Y"),
                            "concept": concept, "geo": geo,
                            "score": "N/A", "velocity": "N/A",
                            "momentum":"N/A","recency":"N/A","corr":"N/A",
                            "mandate": "NO DATA", "horizon": "—"})

        # ── Cooldown between items ──
        if idx_item < len(items) - 1:   # no need to wait after last item
            cooldown = 60 if consecutive_fails >= 2 else 15
            if cooldown == 60:
                print(f"  Multiple rate-limits hit. Cooling down {cooldown}s before next item...")
            else:
                print(f"  Cooling down {cooldown}s before next concept...")
            time.sleep(cooldown)

    # Append to Excel
    _append_watchlist_excel(results)

    # Summary table
    print("\n  ── WATCHLIST SCAN SUMMARY ──")
    print(f"  {'Concept':<35} {'Score':>7} {'Velocity':>10}  Mandate")
    print("  " + "─"*68)
    for r in results:
        sc_v = r['score'] if isinstance(r['score'], str) else f"{r['score']:.1f}"
        vel  = r['velocity'] if isinstance(r['velocity'], str) else f"{r['velocity']:+.1f}"
        print(f"  {r['concept']:<35} {sc_v:>7} {vel:>10}  {r['mandate']}")
    print()

def _append_watchlist_excel(results: list):
    """Appends scan results to watchlist_report.xlsx (creates if missing)."""
    if not OPENPYXL_OK:
        return
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    path = os.path.join(OUTPUT_DIR, "watchlist_report.xlsx")
    COLS = ["date","concept","geo","score","velocity","momentum",
            "recency","corr","mandate","horizon"]
    HEADER_COLOR = "FF1A237E"

    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb["Watchlist"] if "Watchlist" in wb.sheetnames else wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Watchlist"
        for c, col in enumerate(COLS, 1):
            cell = ws.cell(row=1, column=c, value=col.upper())
            cell.font = Font(bold=True, color="FFFFFFFF")
            cell.fill = PatternFill("solid", fgColor=HEADER_COLOR)
            cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions["B"].width = 35
        ws.column_dimensions["J"].width = 28

    for r in results:
        ws.append([r.get(c,"") for c in COLS])

    wb.save(path)
    print(f"\n  Watchlist report saved: {path}")

# ─────────────────────────────────────────────
#  NEW: TREND ALERT SYSTEM
# ─────────────────────────────────────────────
def check_and_fire_alert(concept: str, score_dict: dict,
                         threshold: float = DEFAULT_ALERT_THRESHOLD):
    """
    Fires an alert if velocity >= threshold.
    Writes to alerts.log and prints a red WARNING in terminal.
    """
    velocity = score_dict.get("velocity", 0)
    score    = score_dict.get("score", 0)
    mandate  = get_mandate(score, velocity, score_dict.get("corr", 0))

    if abs(velocity) >= threshold:
        direction = "SURGE" if velocity > 0 else "DROP"
        msg = (f"[{datetime.now():%Y-%m-%d %H:%M}]  "
               f"ALERT {direction}: '{concept}'  "
               f"vel={velocity:+.1f}  score={score}  "
               f"mandate={mandate['label']}")

        # Write to log file
        with open(ALERTS_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

        # Print prominently in terminal
        print("\n" + "!"*62)
        print(f"  *** TREND ALERT — {direction} DETECTED ***")
        print(f"  Concept  : {concept}")
        print(f"  Velocity : {velocity:+.1f}  (threshold: +/-{threshold})")
        print(f"  Score    : {score}/100")
        print(f"  Mandate  : {mandate['label']}")
        print(f"  Logged   : {ALERTS_LOG}")
        print("!"*62 + "\n")
    else:
        print(f"  No alert (vel={velocity:+.1f}, threshold={threshold})")

def view_alerts():
    """Prints the alerts log."""
    print("\n  ── TREND ALERTS LOG ──")
    if not os.path.exists(ALERTS_LOG):
        print("  No alerts fired yet.")
        return
    with open(ALERTS_LOG, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines:
        print("  Log is empty.")
        return
    for line in lines[-30:]:   # show last 30 alerts
        print(" ", line.rstrip())
    print(f"\n  Full log: {ALERTS_LOG}")

# ─────────────────────────────────────────────
#  TERMINAL HELPERS
# ─────────────────────────────────────────────
def print_bar(label, value, max_val=100, width=30):
    filled = int((value/max_val)*width) if max_val else 0
    print(f"  {label:<20} [{'█'*filled}{'░'*(width-filled)}] {value:.1f}")

def print_velocity_meter(velocity):
    clamped = max(-50, min(50, velocity))
    pos     = 25 + int(clamped/2)
    bar     = ["-"]*51
    bar[25] = "|"
    bar[max(0,min(50,pos))] = "O"   # 'O' instead of emoji bullet
    direction = "^ Rising" if velocity>0 else "v Falling" if velocity<0 else "- Flat"
    print(f"\n  VELOCITY   [{''.join(bar)}]  {velocity:+.1f}  {direction}")

# ─────────────────────────────────────────────
#  EXCEL REPORT EXPORT
# ─────────────────────────────────────────────
def export_excel(query, master_df, scores, mandate, horizon,
                 concepts, related_data=None, output_dir=OUTPUT_DIR):
    if not OPENPYXL_OK:
        print("  openpyxl not installed. Skipping Excel export.")
        return None

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils.dataframe import dataframe_to_rows
    from openpyxl.chart import LineChart, Reference

    wb = Workbook()
    ws = wb.active
    ws.title = "Intelligence Summary"

    GREEN="FF4CAF50"; AMBER="FFFFC107"; RED="FFF44336"
    DARK="FF212121"; HDR="FF37474F"

    def hdr(r, c, v, bg=HDR):
        cell = ws.cell(row=r,column=c,value=v)
        cell.font = Font(bold=True,color="FFFFFFFF",size=11)
        cell.fill = PatternFill("solid",fgColor=bg)
        cell.alignment = Alignment(horizontal="center",vertical="center")

    ws.merge_cells("A1:F1")
    t=ws["A1"]; t.value=f"FASHION TREND INTELLIGENCE — {query.upper()}"
    t.font=Font(bold=True,size=14,color="FFFFFFFF")
    t.fill=PatternFill("solid",fgColor=DARK)
    t.alignment=Alignment(horizontal="center",vertical="center")
    ws.row_dimensions[1].height=30

    meta=[("Generated",datetime.now().strftime("%d %b %Y  %H:%M")),
          ("Query",query),("Mandate",mandate["label"]),
          ("Confidence",mandate["confidence"]),("Horizon",horizon),
          ("Rationale",mandate["rationale"])]
    for i,(k,v) in enumerate(meta,start=3):
        ws.cell(row=i,column=1,value=k).font=Font(bold=True)
        ws.cell(row=i,column=2,value=v)
    ws.column_dimensions["A"].width=18
    ws.column_dimensions["B"].width=58

    row=11
    for c,lbl in enumerate(["Keyword","Score","Volume","Momentum","Recency","Velocity"],1):
        hdr(row,c,lbl)
    for i,(kw,sc) in enumerate(scores.items(),start=row+1):
        ws.cell(row=i,column=1,value=kw)
        for j,k in enumerate(["score","volume","momentum","recency","velocity"],2):
            ws.cell(row=i,column=j,value=sc.get(k,0))
        sv=sc.get("score",0)
        ws.cell(row=i,column=2).fill=PatternFill("solid",
            fgColor=GREEN if sv>=60 else AMBER if sv>=35 else RED)

    if not master_df.empty:
        ws_data=wb.create_sheet("Raw Trend Data")
        for r in dataframe_to_rows(master_df.reset_index(),index=False,header=True):
            ws_data.append(r)
        ws_data.column_dimensions["A"].width=14
        chart=LineChart(); chart.title=f"Search Interest — {query}"
        chart.style=10; chart.height=12; chart.width=22
        data_ref=Reference(ws_data,min_col=2,
                           max_col=min(len(master_df.columns)+1,6),
                           min_row=1,max_row=len(master_df)+1)
        chart.add_data(data_ref,titles_from_data=True)
        ws_data.add_chart(chart,"A"+str(len(master_df)+4))

    # Add related queries sheet if available
    if related_data:
        primary_kw = list(scores.keys())[0] if scores else query
        export_related_to_excel(ws, related_data, primary_kw)

    clean=re.sub(r"\W+","_",query)[:25]
    ts=datetime.now().strftime("%Y%m%d_%H%M")
    path=os.path.join(output_dir,f"intel_{clean}_{ts}.xlsx")
    wb.save(path)
    return path

# ─────────────────────────────────────────────
#  CHART RENDERER  (no emojis in text — fixes Windows font warnings)
# ─────────────────────────────────────────────
def render_chart(query, master_df, scores, mandate,
                 horizon, seasonality, geo_label, tf_label):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(16,13), facecolor="#0d1117")
    gs  = gridspec.GridSpec(3,2,figure=fig,
                            height_ratios=[2.5,1.5,1],
                            hspace=0.45,wspace=0.35)
    ax1=fig.add_subplot(gs[0,:]); ax2=fig.add_subplot(gs[1,0])
    ax3=fig.add_subplot(gs[1,1]); ax4=fig.add_subplot(gs[2,:])

    pal=["#00e5ff","#69ff47","#ff6d00","#e040fb","#ffff00"]

    for i,(kw,sc) in enumerate(scores.items()):
        if kw in master_df.columns:
            ax1.plot(master_df.index, master_df[kw],
                     label=f"{kw} ({sc['score']})",
                     color=pal[i%len(pal)], linewidth=1.8, alpha=0.75)
    if "AGG_TREND" in master_df.columns:
        ax1.plot(master_df.index, master_df["AGG_TREND"],
                 color="#ff3d00", linewidth=4, label="Overall momentum", zorder=5)

    ax1.set_facecolor("#161b22")
    ax1.set_title(f"SEARCH MOMENTUM: {query.upper()}  |  {geo_label}  |  {tf_label}",
                  fontsize=13, color="#ffd600", pad=10, fontweight="bold")
    ax1.set_ylabel("Interest (0-100)", fontsize=10, color="#8b949e")
    ax1.set_ylim(0,105)
    ax1.legend(loc="upper left", fontsize=8, facecolor="#21262d", edgecolor="#30363d")
    ax1.tick_params(colors="#8b949e", labelsize=8)
    ax1.grid(axis="y", color="#21262d", linewidth=0.5)

    kw_labels  = list(scores.keys())
    velocities = [scores[k]["velocity"] for k in kw_labels]
    ax2.barh(kw_labels, velocities,
             color=["#69ff47" if v>=0 else "#ff3d00" for v in velocities], height=0.55)
    ax2.axvline(0, color="#8b949e", linewidth=0.8)
    ax2.set_facecolor("#161b22")
    ax2.set_title("Velocity Meter", fontsize=10, color="#ffd600", pad=8)
    ax2.tick_params(colors="#8b949e", labelsize=8)
    ax2.set_xlabel("Momentum pts", fontsize=8, color="#8b949e")

    psc = list(scores.values())[0] if scores else {}
    sv  = [psc.get("volume",0), psc.get("momentum",0), psc.get("recency",0)]
    ax3.bar(["Volume","Momentum","Recency"], sv,
            color=["#00e5ff","#69ff47","#ff6d00"], width=0.5)
    ax3.set_facecolor("#161b22"); ax3.set_ylim(0,110)
    ax3.set_title("Score Breakdown", fontsize=10, color="#ffd600", pad=8)
    ax3.tick_params(colors="#8b949e", labelsize=9)
    ax3.set_ylabel("Score", fontsize=8, color="#8b949e")
    for bar,v in zip(ax3.patches,sv):
        ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()+2,
                 f"{v:.0f}", ha="center", color="white", fontsize=9)

    ax4.axis("off"); ax4.set_facecolor("#0d1117")
    final  = round(np.mean([s["score"] for s in scores.values()]),1)
    sc_col = "#69ff47" if final>=60 else "#ffab40" if final>=35 else "#ff3d00"
    # ASCII labels only — no emojis — avoids all Windows font glyph warnings
    ax4.text(0.01,0.92,
             f"FINAL SCORE: {final}/100   {mandate['label']}   [{mandate['confidence']} confidence]",
             transform=ax4.transAxes, fontsize=15, color=sc_col,
             fontweight="bold", va="top")
    ax4.text(0.01,0.52,
             f"HORIZON: {horizon}     SEASONALITY: {seasonality}",
             transform=ax4.transAxes, fontsize=10, color="#8b949e", va="top")
    ax4.text(0.01,0.14,
             f"RATIONALE: {mandate['rationale']}",
             transform=ax4.transAxes, fontsize=9, color="white", va="top")

    clean=re.sub(r"\W+","_",query)[:30]
    ts=datetime.now().strftime("%Y%m%d_%H%M")
    path=os.path.join(OUTPUT_DIR,f"intel_{clean}_{ts}.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.show()
    print(f"\n  Chart saved: {path}")
    return path

# ─────────────────────────────────────────────
#  SINGLE CONCEPT SCANNER
# ─────────────────────────────────────────────
def run_scanner(concept_override=None, geo_override=None,
                tf_override=None, alert_threshold=DEFAULT_ALERT_THRESHOLD,
                silent=False):
    """
    Main scanner. Accepts overrides for watchlist/programmatic calls.
    Returns score dict so watchlist can log results.
    """
    if not silent:
        print("\n" + "█"*62)
        print("  FASHION TREND INTELLIGENCE  v5.0  |  Ethnic & Value Retail")
        print("█"*62)
        print("""
  TYPE what you want to analyse. Mix garment + color + print freely.

  Examples:
    indigo block print kurti
    tiered anarkali with floral embroidery
    rust linen co-ord set
    mustard sharara
    olive green georgette lehenga
    saree
""")

    if concept_override:
        raw_input = concept_override
        print(f"  Concept: {raw_input}")
    else:
        while True:
            raw_input = input("  >> Your search: ").strip()
            if raw_input:
                break
            print("  Please type something (e.g. 'rust kurti' or 'block print saree')\n")

    if tf_override:
        timeframe, tf_label = tf_override, tf_override
    else:
        print("\n  Timeframe:  1=Last 3 months   2=Last 12 months   3=Last 5 years")
        tc = input("  Choose [1/2/3, default 2]: ").strip() or "2"
        timeframe, tf_label = TIMEFRAME_OPTIONS.get(tc, TIMEFRAME_OPTIONS["2"])

    if geo_override:
        geo, geo_label = geo_override, geo_override
    else:
        print("\n  Geography:")
        for k,(g,lbl) in GEO_OPTIONS.items():
            print(f"    {k}. {lbl}")
        gc = input("  Choose [1-8, default 1]: ").strip() or "1"
        geo, geo_label = GEO_OPTIONS.get(gc, GEO_OPTIONS["1"])

    export_xls = False
    fetch_related = False
    alert_thr = alert_threshold
    if not silent:
        export_xls    = input("\n  Export Excel report? [y/N]: ").strip().lower()=="y"
        fetch_related = input("  Fetch related queries?  [y/N]: ").strip().lower()=="y"
        at = input(f"  Alert threshold (velocity, default {DEFAULT_ALERT_THRESHOLD}): ").strip()
        try:    alert_thr = float(at)
        except: alert_thr = DEFAULT_ALERT_THRESHOLD

    concepts = parse_concept(raw_input)
    keywords = concepts["keywords"]
    anchor   = concepts["anchor"]

    print(f"\n  Parsed: garment={concepts['garment'] or '(auto)'} | "
          f"color={concepts['color'] or ['-']} | "
          f"silhouette={concepts['silhouette'] or ['-']} | "
          f"print={concepts['print'] or ['-']} | "
          f"fabric={concepts['fabric'] or ['-']}")
    print(f"  Keywords: {keywords}")
    print(f"  Anchor  : {anchor}")

    if not PYTRENDS_OK:
        print("\n  pytrends not installed. Run: pip install pytrends")
        return None

    try:
        pt = make_pytrends()
    except Exception as e:
        print(f"\n  Cannot connect: {e}")
        return None

    print(f"\n  Fetching anchor: '{anchor}'...")
    adf = fetch_with_backoff(pt, anchor, geo, timeframe)
    anchor_s = (adf[anchor] if not adf.empty and anchor in adf.columns
                else pd.Series(dtype=float))

    master_df=pd.DataFrame(); scores={}; seasonality="Unknown"
    print(f"\n  Fetching {len(keywords)} keyword(s)...\n")
    for kw in keywords:
        print(f"  > {kw}  ", end="", flush=True)
        df = fetch_with_backoff(pt, kw, geo, timeframe)
        if not df.empty and kw in df.columns:
            series = df[kw]; master_df[kw]=series
            sc = compute_score(series, anchor_s); scores[kw]=sc
            print(f"score={sc['score']}  vel={sc['velocity']:+.1f}  corr={sc['corr']}")
            if seasonality=="Unknown": seasonality=detect_seasonality(series)
        else:
            print("no data")
        time.sleep(3)

    if master_df.empty:
        print("\n  No data retrieved.")
        print("  Causes: too niche for Google Trends / rate limited / no internet")
        return None

    master_df["AGG_TREND"] = master_df.drop(columns=["AGG_TREND"],errors="ignore").mean(axis=1)
    avg_sc  = round(np.mean([s["score"]    for s in scores.values()]),1)
    avg_vel = round(np.mean([s["velocity"] for s in scores.values()]),2)
    avg_cor = round(np.mean([s["corr"]     for s in scores.values()]),3)
    mandate = get_mandate(avg_sc, avg_vel, avg_cor)
    horizon = get_horizon(avg_sc, avg_vel)

    # Terminal report
    print("\n"+"─"*62)
    print(f"  INTELLIGENCE REPORT: {raw_input.upper()}")
    print("─"*62)
    print(f"  Final trend score : {avg_sc}/100")
    print(f"  Correlation       : {avg_cor}")
    print(f"  Horizon           : {horizon}")
    print(f"  Seasonality       : {seasonality}")
    print(f"  Mandate           : {mandate['label']}")
    print(f"  Confidence        : {mandate['confidence']}")
    print(f"  Rationale         : {mandate['rationale']}")

    print("\n  Sub-scores:")
    for kw,sc in scores.items():
        print(f"\n  {kw.upper()}")
        print_bar("Volume",   sc["volume"])
        print_bar("Momentum", sc["momentum"])
        print_bar("Recency",  sc["recency"])
        print_bar("Score",    sc["score"])
    print_velocity_meter(avg_vel)

    # Related queries
    related_data = None
    if fetch_related:
        primary_kw  = list(scores.keys())[0]
        print(f"\n  Fetching related queries for '{primary_kw}'...")
        time.sleep(3)
        related_data = fetch_related_queries(pt, primary_kw, geo, timeframe)
        print_related_queries(related_data, primary_kw)

    # Alert check
    print(f"\n  Checking alert threshold ({alert_thr})...")
    check_and_fire_alert(raw_input, {"score":avg_sc,"velocity":avg_vel,"corr":avg_cor}, alert_thr)

    # Chart
    render_chart(raw_input, master_df, scores, mandate,
                 horizon, seasonality, geo_label, tf_label)

    # Excel
    if export_xls:
        path = export_excel(raw_input, master_df, scores, mandate,
                            horizon, concepts, related_data)
        if path: print(f"  Excel report: {path}")

    print("\n  Done. Output saved in /output folder.\n")
    return {"score":avg_sc,"velocity":avg_vel,"corr":avg_cor,
            "mandate":mandate["label"],"horizon":horizon}

# ─────────────────────────────────────────────
#  COMPARISON MODE
# ─────────────────────────────────────────────
def run_comparison():
    print("\n"+"█"*62)
    print("  COMPARISON MODE — Head-to-Head Trend Analysis")
    print("█"*62)
    print("""
  Enter up to 4 concepts to compare (blank line to finish).
  e.g. 'rust kurti', 'indigo block print saree', 'tiered anarkali'
""")
    concepts_raw=[]
    for i in range(1,5):
        c=input(f"  Concept {i} (or Enter to finish): ").strip()
        if not c: break
        concepts_raw.append(c)
    if len(concepts_raw)<2:
        print("  Need at least 2 concepts."); return

    tc=input("\n  Timeframe [1=3m/2=12m/3=5y, default 2]: ").strip() or "2"
    timeframe,tf_label=TIMEFRAME_OPTIONS.get(tc,TIMEFRAME_OPTIONS["2"])
    geo,geo_label="IN","India"

    if not PYTRENDS_OK:
        print("  pytrends not installed."); return
    try:
        pt=make_pytrends()
    except Exception as e:
        print(f"  Cannot connect: {e}"); return

    results={}
    for raw in concepts_raw:
        parsed=parse_concept(raw); kw=parsed["keywords"][0]
        print(f"\n  Fetching: '{kw}'...")
        df=fetch_with_backoff(pt, kw, geo, timeframe)
        if not df.empty and kw in df.columns:
            sc=compute_score(df[kw])
            results[raw]={"df":df[kw],"score":sc,"kw":kw}
            print(f"    score={sc['score']}  vel={sc['velocity']:+.1f}")
        else:
            print(f"    No data for '{kw}'")
        time.sleep(4)

    if not results:
        print("  No data."); return

    plt.style.use("dark_background")
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(16,6),facecolor="#0d1117")
    pal=["#00e5ff","#69ff47","#ff6d00","#e040fb"]
    for i,(lbl,res) in enumerate(results.items()):
        ax1.plot(res["df"].index,res["df"].values,
                 label=f"{lbl} ({res['score']['score']})",
                 color=pal[i],linewidth=2)
    ax1.set_facecolor("#161b22")
    ax1.set_title("Trend Comparison",color="#ffd600",fontsize=12,fontweight="bold")
    ax1.legend(fontsize=8,facecolor="#21262d")
    ax1.tick_params(colors="#8b949e",labelsize=8)
    ax1.set_ylabel("Interest (0-100)",color="#8b949e",fontsize=9)

    labels_=[l for l in results]; scores_=[results[l]["score"]["score"] for l in labels_]
    ax2.bar(labels_,scores_,color=[pal[i] for i in range(len(labels_))],width=0.5)
    ax2.set_facecolor("#161b22"); ax2.set_ylim(0,110)
    ax2.set_title("Final Score Comparison",color="#ffd600",fontsize=12,fontweight="bold")
    ax2.tick_params(colors="#8b949e",labelsize=8)
    for bar,v in zip(ax2.patches,scores_):
        ax2.text(bar.get_x()+bar.get_width()/2,bar.get_height()+1.5,
                 str(v),ha="center",color="white",fontsize=10,fontweight="bold")
    plt.suptitle(f"HEAD-TO-HEAD: {' vs '.join(labels_[:2])}{'...' if len(labels_)>2 else ''}  |  {tf_label}",
                 color="#ffd600",fontsize=13,fontweight="bold",y=1.01)
    plt.tight_layout()
    ts=datetime.now().strftime("%Y%m%d_%H%M")
    path=os.path.join(OUTPUT_DIR,f"compare_{ts}.png")
    plt.savefig(path,dpi=150,bbox_inches="tight",facecolor="#0d1117")
    plt.show()
    print(f"\n  Comparison chart: {path}")

    print("\n  COMPARISON SUMMARY")
    print(f"  {'Concept':<35}{'Score':>7}{'Velocity':>10}  Mandate")
    print("  "+"─"*68)
    for lbl,res in results.items():
        sc=res["score"]
        m=get_mandate(sc["score"],sc["velocity"],sc["corr"])
        print(f"  {lbl:<35}{sc['score']:>7}{sc['velocity']:>+10.1f}  {m['label']}")
    print()

# ─────────────────────────────────────────────
#  MAIN MENU
# ─────────────────────────────────────────────
def main():
    print("\n"+"="*62)
    print("  FASHION TREND INTELLIGENCE  v5.0")
    print("  Ethnic & Value Retail  |  India Market")
    print("="*62)
    print("""
  1. Single concept analysis
  2. Compare multiple concepts (head-to-head)
  3. Weekly watchlist  (save + run tracked concepts)
  4. View trend alerts log
  5. Exit
""")
    ch=input("  Choose mode [1-5]: ").strip()
    if   ch=="1": run_scanner()
    elif ch=="2": run_comparison()
    elif ch=="3": manage_watchlist()
    elif ch=="4": view_alerts()
    elif ch=="5": sys.exit(0)
    else:
        print("  Invalid — running single-concept mode.")
        run_scanner()

if __name__=="__main__":
    main()
