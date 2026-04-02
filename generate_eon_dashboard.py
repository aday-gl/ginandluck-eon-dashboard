#!/usr/bin/env python3
"""
G&L End of Night Dashboard Generator v2
- Saves each day's data to eon_data/YYYY-MM-DD.json
- Loads all historical JSON files to build growing MTD charts
- Generates a single master EON_Dashboard.html with full date navigation,
  per-venue sparklines, weekly view, and individual venue MTD lines.

Usage:
  python3 generate_eon_dashboard.py                         # use embedded DATA dict
  python3 generate_eon_dashboard.py data.json               # load from JSON file
  python3 generate_eon_dashboard.py data.json output.html   # custom output path
"""

import json, sys, os, glob
from datetime import datetime, date

WORKSPACE  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(WORKSPACE, "eon_data")
OUTPUT     = os.path.join(WORKSPACE, "EON_Dashboard.html")

VENUE_META = [
    {"id": "ccatl", "name": "CC Atlanta",      "full": "Close Company Atlanta",      "color": "#E07B54"},
    {"id": "ccnsh", "name": "CC Nashville",    "full": "Close Company Nashville",    "color": "#6B8CBA"},
    {"id": "mg",    "name": "Municipal Grand", "full": "Municipal Grand F&B",        "color": "#7CB87A"},
    {"id": "la",    "name": "D&C LA",          "full": "Death & Co Los Angeles",     "color": "#C47DC0"},
    {"id": "dvr",   "name": "D&C Denver",      "full": "Death & Co Denver",          "color": "#E8C45A"},
    {"id": "ev",    "name": "D&C East Village","full": "Death & Co East Village",    "color": "#E87A7A"},
    {"id": "dc",    "name": "D&C DC",          "full": "Death & Co Washington DC",   "color": "#5AA8C4"},
]
VENUE_IDS  = [v["id"] for v in VENUE_META]

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def save_day_data(data: dict):
    """Persist a day's parsed data to eon_data/YYYY-MM-DD.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    # derive ISO date key from report_date string or explicit key
    iso = data.get("iso_date")
    if not iso:
        try:
            dt = datetime.strptime(data["report_date"], "%B %d, %Y")
            iso = dt.strftime("%Y-%m-%d")
        except Exception:
            iso = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"{iso}.json")
    data["iso_date"] = iso
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return iso

def load_all_history() -> dict:
    """Load all eon_data/*.json files → {iso_date: data_dict}."""
    history = {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        iso = os.path.basename(path).replace(".json", "")
        try:
            with open(path) as f:
                history[iso] = json.load(f)
        except Exception:
            pass
    return history

def build_mtd_series(history: dict):
    """
    Build consolidated + per-venue daily series from history.
    Returns:
      dates[]               sorted ISO date strings
      consolidated_actual[] sum of net_sales across reporting venues
      consolidated_target[] sum of targets
      venue_series          {venue_id: {"actual": [], "target": []}}
    """
    dates = sorted(history.keys())
    consolidated_actual, consolidated_target = [], []
    venue_series = {vid: {"actual": [], "target": []} for vid in VENUE_IDS}

    for d in dates:
        day = history[d]
        day_actual, day_target = 0, 0
        venue_totals = {vid: {"actual": None, "target": None} for vid in VENUE_IDS}

        for v in day.get("venues", []):
            vid = v.get("id")
            if v.get("missing") or vid not in VENUE_IDS:
                continue
            ns = v.get("net_sales") or 0
            tg = v.get("target") or 0
            day_actual += ns
            day_target += tg
            venue_totals[vid]["actual"] = ns
            venue_totals[vid]["target"] = tg

        consolidated_actual.append(round(day_actual, 2))
        consolidated_target.append(round(day_target, 2))
        for vid in VENUE_IDS:
            venue_series[vid]["actual"].append(venue_totals[vid]["actual"])
            venue_series[vid]["target"].append(venue_totals[vid]["target"])

    return dates, consolidated_actual, consolidated_target, venue_series

def compute_monthly_budgets(history: dict) -> dict:
    """
    Scan all history entries and collect monthly_budget per venue per month.
    Returns {YYYY-MM: {venue_id: budget_value}}
    Only uses the first non-None monthly_budget found for each venue/month.
    """
    budgets = {}
    for iso, day in sorted(history.items()):
        ym = iso[:7]
        for v in day.get("venues", []):
            vid = v.get("id")
            mb  = v.get("monthly_budget")
            if vid and mb is not None:
                if ym not in budgets:
                    budgets[ym] = {}
                if vid not in budgets[ym]:
                    budgets[ym][vid] = mb
    return budgets

def label_date(iso: str) -> str:
    """'2026-03-30' → 'Mon 3/30'"""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%d")
        return dt.strftime("%a %-m/%-d")
    except Exception:
        return iso

def fmt(v, prefix="$"):
    if v is None: return "—"
    if isinstance(v, float) and v == int(v): v = int(v)
    return f"{prefix}{v:,}"

def vpct(actual, target):
    if not actual or not target: return None
    return round((actual - target) / target * 100, 1)

def vcolor(actual, target):
    p = vpct(actual, target)
    if p is None: return "#888"
    if p >= 5:   return "#5BC88A"
    if p >= -5:  return "#E8C45A"
    return "#E87A7A"

def hl_icon(t):
    return {"win": ("✅","#5BC88A"), "urgent": ("🚨","#E87A7A"),
            "flag": ("⚠️","#E8C45A"), "info": ("ℹ️","#8AAFCA")}.get(t, ("•","#aaa"))

# ─────────────────────────────────────────────────────────────
# HTML GENERATION
# ─────────────────────────────────────────────────────────────

def generate_html(today_data: dict, history: dict) -> str:
    dates, c_actual, c_target, v_series = build_mtd_series(history)

    # date labels for chart axis
    date_labels = [label_date(d) for d in dates]

    # per-venue color map
    color_map = {v["id"]: v["color"] for v in VENUE_META}

    # build JavaScript HISTORY object (full day data per date key)
    history_js = json.dumps(history, ensure_ascii=False)

    # monthly budgets per venue: {YYYY-MM: {venue_id: value}}
    monthly_budgets = compute_monthly_budgets(history)
    monthly_budgets_js = json.dumps(monthly_budgets)

    # chart series JS
    chart_data_js = json.dumps({
        "dates":    date_labels,
        "isos":     dates,
        "c_actual": c_actual,
        "c_target": c_target,
        "venues":   [
            {
                "id":     vm["id"],
                "name":   vm["name"],
                "full":   vm["full"],
                "color":  vm["color"],
                "actual": v_series[vm["id"]]["actual"],
                "target": v_series[vm["id"]]["target"],
            }
            for vm in VENUE_META
        ]
    })

    # available dates list for nav
    avail_dates_js = json.dumps(sorted(history.keys()))

    today_iso = today_data.get("iso_date", sorted(history.keys())[-1] if history else "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>G&L EON Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0F1117;color:#E0E0E0;min-height:100vh}}

/* NAV */
.top-nav{{background:#16181F;border-bottom:1px solid #2A2D3A;padding:0 28px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0}}
.brand{{padding:18px 0;font-size:16px;font-weight:700;color:#fff;letter-spacing:-.3px}}
.brand span{{color:#888;font-weight:400;font-size:13px;margin-left:8px}}
.date-nav{{display:flex;align-items:center;gap:0;background:#1C1F2A;border-radius:8px;border:1px solid #2A2D3A;overflow:hidden}}
.date-nav button{{background:none;border:none;color:#888;padding:9px 14px;cursor:pointer;font-size:13px;transition:background .15s}}
.date-nav button:hover{{background:#252836;color:#fff}}
.date-display{{padding:9px 16px;font-size:13px;font-weight:600;color:#C8CAFF;white-space:nowrap;border-left:1px solid #2A2D3A;border-right:1px solid #2A2D3A}}
.view-tabs{{display:flex;gap:4px;padding:12px 0 12px 20px}}
.view-tab{{background:none;border:1px solid #2A2D3A;border-radius:6px;color:#666;padding:6px 14px;cursor:pointer;font-size:12px;font-weight:600;transition:all .15s}}
.view-tab.active{{background:#252836;border-color:#4A4D60;color:#C8CAFF}}

/* MAIN */
.main{{padding:24px 28px;max-width:1700px;margin:0 auto}}

/* KPI STRIP */
.kpi-strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}}
@media(max-width:900px){{.kpi-strip{{grid-template-columns:repeat(2,1fr)}}}}
.kpi{{background:#16181F;border:1px solid #2A2D3A;border-radius:10px;padding:16px 18px}}
.kpi-label{{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:#555;margin-bottom:5px}}
.kpi-value{{font-size:26px;font-weight:700;color:#fff;line-height:1}}
.kpi-sub{{font-size:11px;color:#555;margin-top:3px}}
.pos{{color:#5BC88A!important}}.neg{{color:#E87A7A!important}}.neu{{color:#E8C45A!important}}

/* SECTION */
.section-label{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#555;margin-bottom:12px}}
.card{{background:#16181F;border:1px solid #2A2D3A;border-radius:10px;padding:20px 22px;margin-bottom:20px}}

/* MTD CHART */
.mtd-chart-wrap{{position:relative;height:260px}}
.chart-legend-custom{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}
.legend-item{{display:flex;align-items:center;gap:5px;font-size:11px;color:#888;cursor:pointer;padding:4px 9px;border-radius:5px;border:1px solid #2A2D3A;transition:all .15s}}
.legend-item:hover,.legend-item.active{{background:#252836;color:#E0E0E0;border-color:#4A4D60}}
.legend-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.legend-dash{{width:14px;height:2px;border-top:2px dashed;flex-shrink:0}}

/* EXEC SUMMARY */
.exec-cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
@media(max-width:900px){{.exec-cols{{grid-template-columns:1fr}}}}
.exec-group-title{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px}}
.exec-list{{list-style:none;display:flex;flex-direction:column;gap:7px}}
.exec-list li{{font-size:12px;color:#C0C0C0;line-height:1.45;padding:7px 10px;background:#1C1F2A;border-radius:6px}}
.exec-list li strong{{color:#E0E0E0}}

/* VENUE GRID */
.venue-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:18px}}
@media(max-width:600px){{.venue-grid{{grid-template-columns:1fr}}}}

/* VENUE CARD */
.vcard{{background:#16181F;border:1px solid #2A2D3A;border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:13px}}
.vcard-head{{display:flex;align-items:center;gap:8px}}
.vcard-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.vcard-name{{font-size:14px;font-weight:700;color:#fff;flex:1}}
.vcard-date{{font-size:11px;color:#555}}
.date-warn{{font-size:11px;color:#E8C45A;background:#E8C45A11;padding:5px 9px;border-radius:5px;border-left:3px solid #E8C45A}}
.sales-row{{display:grid;grid-template-columns:2fr 1.1fr 1.1fr;gap:8px}}
.sbox{{background:#1C1F2A;border-radius:8px;padding:9px 11px}}
.sbox-label{{font-size:9px;text-transform:uppercase;letter-spacing:.6px;color:#555;margin-bottom:3px}}
.sbox-val{{font-size:30px;font-weight:800;color:#fff;line-height:1;letter-spacing:-.5px}}
.sbox-sm{{font-size:14px;font-weight:600;color:#C0C0C0;line-height:1}}
.sbox-pct{{font-size:16px;font-weight:700;line-height:1;text-align:center}}
.sbox-abs{{font-size:11px;color:#666;margin-top:2px;text-align:center}}
.fin-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}}
.fin{{background:#1C1F2A;border-radius:6px;padding:6px 9px}}
.fin-label{{font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.4px}}
.fin-val{{font-size:12px;font-weight:600;color:#B0B0B0;margin-top:1px}}
.sub-rows{{background:#1C1F2A;border-radius:8px;padding:9px 11px;display:flex;flex-direction:column;gap:4px}}
.sub-row{{display:flex;justify-content:space-between;font-size:12px;color:#888}}
.sub-row span:last-child{{color:#C0C0C0;font-weight:600}}
.ops-row{{display:flex;gap:14px;flex-wrap:wrap}}
.ops-item{{font-size:11px;color:#777}}
.ops-item b{{color:#555;font-weight:400}}
.vnotes{{font-size:12px;color:#888;line-height:1.5;border-left:2px solid #2A2D3A;padding-left:9px;font-style:italic}}
.tags{{display:flex;flex-wrap:wrap;gap:5px}}
.tag{{font-size:10px;padding:3px 7px;border-radius:4px;font-weight:500}}
.tag-86{{background:#E87A7A22;color:#E87A7A;border:1px solid #E87A7A33}}
.tag-maint{{background:#E8C45A22;color:#E8C45A;border:1px solid #E8C45A33}}
.hls{{display:flex;flex-direction:column;gap:6px}}
.hl{{display:flex;align-items:flex-start;gap:7px;padding:7px 9px;background:#1C1F2A;border-radius:6px;font-size:12px;color:#B0B0B0;line-height:1.4}}
.hl-icon{{flex-shrink:0;font-size:12px}}

/* PACE BAR */
.pace-section{{background:#1C1F2A;border-radius:8px;padding:10px 12px}}
.pace-meta{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:8px;gap:8px}}
.pace-stat{{min-width:0}}
.pace-stat-label{{font-size:9px;text-transform:uppercase;letter-spacing:.6px;color:#555;margin-bottom:2px}}
.pace-stat-val{{font-size:14px;font-weight:700;color:#fff;white-space:nowrap}}
.pace-stat-val.budget{{color:#C8CAFF}}
.pace-bar-track{{height:7px;background:#2A2D3A;border-radius:4px;overflow:hidden;margin-bottom:5px}}
.pace-bar-fill{{height:100%;border-radius:4px;transition:width .3s ease}}
.pace-footer{{display:flex;justify-content:space-between;font-size:10px;color:#555}}
.pace-footer .pace-pct{{font-weight:700}}

/* SPARKLINE */
.spark-wrap{{height:60px;position:relative}}

/* WEEKLY VIEW */
.weekly-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-bottom:18px}}
@media(max-width:900px){{.weekly-grid{{grid-template-columns:repeat(4,1fr)}}}}
.wday-card{{background:#16181F;border:1px solid #2A2D3A;border-radius:8px;padding:12px 10px;text-align:center}}
.wday-label{{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}}
.wday-val{{font-size:16px;font-weight:700;color:#fff}}
.wday-pct{{font-size:11px;margin-top:2px}}
.wday-card.today{{border-color:#4A4D60;background:#1C1F2A}}
.week-chart-wrap{{height:220px;position:relative}}

/* MISSING CARD */
.vcard-missing{{opacity:.55}}
.missing-badge{{background:#2A2D3A;color:#666;padding:2px 8px;border-radius:4px;font-size:10px}}
.missing-reason{{font-size:12px;color:#555;font-style:italic}}

/* FOOTER */
.footer{{text-align:center;padding:20px;color:#333;font-size:11px;border-top:1px solid #1A1D27;margin-top:32px}}

/* scrollbar */
::-webkit-scrollbar{{width:5px}}
::-webkit-scrollbar-track{{background:#0F1117}}
::-webkit-scrollbar-thumb{{background:#2A2D3A;border-radius:3px}}
</style>
</head>
<body>

<!-- TOP NAV -->
<div class="top-nav">
  <div style="display:flex;align-items:center;gap:0;flex-wrap:wrap">
    <div class="brand">G&amp;L End of Night<span id="brandSub">Loading…</span></div>
    <div class="view-tabs">
      <button class="view-tab active" onclick="switchView('daily')" id="tab-daily">Daily</button>
      <button class="view-tab" onclick="switchView('weekly')" id="tab-weekly">Weekly</button>
      <button class="view-tab" onclick="switchView('mtd')" id="tab-mtd">MTD</button>
      <button class="view-tab" onclick="switchView('ytd')" id="tab-ytd">YTD</button>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;padding:12px 0">
    <div class="date-nav">
      <button onclick="stepDate(-1)" title="Previous day">&#8592;</button>
      <div class="date-display" id="dateDisplay">—</div>
      <button onclick="stepDate(1)" title="Next day">&#8594;</button>
    </div>
  </div>
</div>

<div class="main">

  <!-- DAILY VIEW -->
  <div id="view-daily">
    <!-- KPI strip -->
    <div class="kpi-strip">
      <div class="kpi">
        <div class="kpi-label">Total Net Sales</div>
        <div class="kpi-value" id="kpi-sales">—</div>
        <div class="kpi-sub" id="kpi-venues-sub">—</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Consolidated Target</div>
        <div class="kpi-value" style="color:#C8CAFF" id="kpi-target">—</div>
        <div class="kpi-sub">Daily sales target</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Variance</div>
        <div class="kpi-value" id="kpi-var">—</div>
        <div class="kpi-sub" id="kpi-varpct">—</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Venues Reporting</div>
        <div class="kpi-value" style="color:#C8CAFF" id="kpi-count">—</div>
        <div class="kpi-sub" id="kpi-day">—</div>
      </div>
    </div>

    <!-- Executive Summary -->
    <div class="card" id="exec-card">
      <div class="section-label">Executive Summary</div>
      <div class="exec-cols" id="exec-cols"><!-- filled by JS --></div>
    </div>

    <!-- Venue Grid -->
    <div class="section-label">Venue Breakdown</div>
    <div class="venue-grid" id="venue-grid"><!-- filled by JS --></div>
  </div>

  <!-- WEEKLY VIEW -->
  <div id="view-weekly" style="display:none">
    <div class="card">
      <div class="section-label">Last 7 Days — Daily Consolidated</div>
      <div class="weekly-grid" id="weekly-day-cards"><!-- filled by JS --></div>
      <div class="week-chart-wrap"><canvas id="weeklyChart"></canvas></div>
    </div>
    <div class="card">
      <div class="section-label">Venue Performance — Last 7 Days</div>
      <div id="weekly-venue-table"><!-- filled by JS --></div>
    </div>
  </div>

  <!-- MTD VIEW -->
  <div id="view-mtd" style="display:none">
    <div class="card">
      <div class="section-label">Month-to-Date Revenue — Actual vs. Target</div>
      <div class="mtd-chart-wrap"><canvas id="mtdChart"></canvas></div>
      <div class="chart-legend-custom" id="mtdLegend"><!-- filled by JS --></div>
      <div style="font-size:10px;color:#444;margin-top:10px">
        Consolidated totals across all reporting venues. Chart builds as nightly reports accumulate.
      </div>
    </div>
  </div>

  <!-- YTD VIEW -->
  <div id="view-ytd" style="display:none">
    <!-- YTD KPI strip -->
    <div class="kpi-strip" id="ytd-kpis" style="margin-bottom:20px"><!-- filled by JS --></div>

    <!-- Monthly bar chart + cumulative line -->
    <div class="card" style="margin-bottom:20px">
      <div class="section-label">Monthly Revenue — Actual vs. Target</div>
      <div style="height:240px;position:relative"><canvas id="ytdMonthlyChart"></canvas></div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="section-label">Cumulative YTD — Running Total</div>
      <div style="height:200px;position:relative"><canvas id="ytdCumulativeChart"></canvas></div>
    </div>

    <!-- Per-venue monthly table -->
    <div class="card">
      <div class="section-label">Venue Monthly Breakdown</div>
      <div id="ytd-venue-table" style="overflow-x:auto"><!-- filled by JS --></div>
    </div>
  </div>

</div>

<div class="footer">Gin &amp; Luck — EON Dashboard &nbsp;·&nbsp; Auto-generated from Slack EON reports</div>

<!-- ════════════════════════════════════════════════════════ -->
<script>
// ── DATA ─────────────────────────────────────────────────────
const HISTORY         = {history_js};
const CHART_DATA      = {chart_data_js};
const AVAIL           = {avail_dates_js};  // sorted ISO dates
const TODAY_ISO       = "{today_iso}";
const VENUE_META      = {json.dumps(VENUE_META)};
const MONTHLY_BUDGETS = {monthly_budgets_js};  // {{YYYY-MM: {{venue_id: budget}}}}

// ── STATE ─────────────────────────────────────────────────────
let currentISO  = AVAIL.length ? AVAIL[AVAIL.length - 1] : TODAY_ISO;
let currentView = 'daily';
let chartInstances = {{}};
let visibleVenues  = new Set(VENUE_META.map(v => v.id)); // all on by default for MTD

// ── UTIL ──────────────────────────────────────────────────────
function fmtC(v) {{
  if (v == null) return '—';
  return '$' + Math.round(v).toLocaleString();
}}
function fmtPct(a, t) {{
  if (!a || !t) return null;
  return ((a - t) / t * 100).toFixed(1);
}}
function pctColor(a, t) {{
  const p = fmtPct(a, t);
  if (p === null) return '#888';
  if (p >= 5)    return '#5BC88A';
  if (p >= -5)   return '#E8C45A';
  return '#E87A7A';
}}
function labelIso(iso) {{
  if (!iso) return '—';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('en-US', {{weekday:'short', month:'short', day:'numeric', year:'numeric'}});
}}
function shortIso(iso) {{
  if (!iso) return '—';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('en-US', {{weekday:'short', month:'numeric', day:'numeric'}});
}}
function destroyChart(id) {{
  if (chartInstances[id]) {{ chartInstances[id].destroy(); delete chartInstances[id]; }}
}}

// ── NAVIGATION ────────────────────────────────────────────────
function stepDate(delta) {{
  const idx = AVAIL.indexOf(currentISO);
  const next = idx + delta;
  if (next >= 0 && next < AVAIL.length) {{
    currentISO = AVAIL[next];
    renderCurrentView();
  }}
}}

function switchView(v) {{
  currentView = v;
  ['daily','weekly','mtd','ytd'].forEach(x => {{
    document.getElementById('view-' + x).style.display = (x === v) ? '' : 'none';
    document.getElementById('tab-' + x).classList.toggle('active', x === v);
  }});
  renderCurrentView();
}}

function renderCurrentView() {{
  const day = HISTORY[currentISO];
  document.getElementById('dateDisplay').textContent = labelIso(currentISO);
  document.getElementById('brandSub').textContent =
    day ? ' — ' + (day.day_of_week || '') + ', ' + (day.report_date || '') : '';

  if (currentView === 'daily')  renderDaily(day);
  if (currentView === 'weekly') renderWeekly();
  if (currentView === 'mtd')    renderMTD();
  if (currentView === 'ytd')    renderYTD();
}}

// ── DAILY VIEW ────────────────────────────────────────────────
function renderDaily(day) {{
  if (!day) {{
    document.getElementById('venue-grid').innerHTML =
      '<div style="color:#555;padding:20px">No data for this date.</div>';
    return;
  }}
  const venues  = (day.venues || []).filter(v => !v.missing);
  const missing = (day.venues || []).filter(v => v.missing);
  const totalS  = venues.reduce((s, v) => s + (v.net_sales || 0), 0);
  const totalT  = venues.reduce((s, v) => s + (v.target || 0), 0);
  const variance = totalS - totalT;
  const vp = fmtPct(totalS, totalT);
  const vc = pctColor(totalS, totalT);

  // KPI strip
  document.getElementById('kpi-sales').textContent = fmtC(totalS);
  document.getElementById('kpi-target').textContent = fmtC(totalT);
  document.getElementById('kpi-venues-sub').textContent =
    venues.length + ' venues consolidated';
  const kpiVar = document.getElementById('kpi-var');
  kpiVar.textContent = (variance >= 0 ? '+' : '') + fmtC(variance);
  kpiVar.className = 'kpi-value ' + (variance >= 0 ? 'pos' : 'neg');
  document.getElementById('kpi-varpct').textContent =
    (vp !== null ? (vp > 0 ? '+' : '') + vp + '%' : '—') + ' to target';
  document.getElementById('kpi-varpct').style.color = vc;
  document.getElementById('kpi-count').textContent =
    venues.length + ' / ' + (day.venues || []).length;
  document.getElementById('kpi-day').textContent = day.day_of_week || '—';

  // Exec summary
  const urgent = [], flags = [], wins = [];
  (day.venues || []).forEach(v => {{
    if (v.missing) return;
    (v.highlights || []).forEach(h => {{
      const li = `<li><strong>${{v.name}}:</strong> ${{h.text}}</li>`;
      if (h.type === 'urgent') urgent.push(li);
      else if (h.type === 'flag') flags.push(li);
      else if (h.type === 'win') wins.push(li);
    }});
  }});
  function grp(items, title, color) {{
    if (!items.length) return '';
    return `<div>
      <div class="exec-group-title" style="color:${{color}}">${{title}}</div>
      <ul class="exec-list">${{items.join('')}}</ul>
    </div>`;
  }}
  document.getElementById('exec-cols').innerHTML =
    grp(urgent, '🚨 Needs Attention', '#E87A7A') +
    grp(flags,  '⚠️ Watch Items',     '#E8C45A') +
    grp(wins,   '✅ Wins & Highlights','#5BC88A');

  // Venue grid
  let html = '';
  (day.venues || []).forEach(v => {{
    if (v.missing) {{
      html += `
      <div class="vcard vcard-missing" style="border-top:3px solid ${{v.color||'#555'}}">
        <div class="vcard-head">
          <span class="vcard-dot" style="background:${{v.color||'#555'}}"></span>
          <span class="vcard-name">${{v.full_name}}</span>
          <span class="missing-badge">No Daily Data</span>
        </div>
        <div class="missing-reason">${{v.missing_reason||''}}</div>
      </div>`;
      return;
    }}
    const ns = v.net_sales;
    // Use r365_forecast if available, fall back to legacy target field
    const tg = v.r365_forecast != null ? v.r365_forecast : (v.target || null);
    const vPct = fmtPct(ns, tg);
    const vCol = pctColor(ns, tg);
    const varAbs = (ns && tg) ? (ns - tg) : null;

    // ── MTD Pace computation ──────────────────────────────────
    const curYM      = currentISO.slice(0, 7);
    const mtdDates   = AVAIL.filter(d => d.startsWith(curYM) && d <= currentISO);
    let mtdActual = 0;
    mtdDates.forEach(iso => {{
      const dd = HISTORY[iso];
      if (!dd) return;
      const vv = (dd.venues || []).find(x => x.id === v.id);
      if (vv && !vv.missing) mtdActual += (vv.net_sales || 0);
    }});
    const daysElapsed  = mtdDates.length || 1;
    const ymParts      = curYM.split('-');
    const daysInMonth  = new Date(parseInt(ymParts[0]), parseInt(ymParts[1]), 0).getDate();
    const paceProj     = Math.round((mtdActual / daysElapsed) * daysInMonth);
    const mb           = (MONTHLY_BUDGETS[curYM] || {{}})[v.id] || null;
    const paceVsBudget = mb ? Math.round(paceProj / mb * 100) : null;
    const paceBarWidth = mb ? Math.min(Math.round(paceProj / mb * 100), 100) : 0;
    const paceColor    = paceVsBudget === null ? '#555'
                         : paceVsBudget >= 100  ? '#5BC88A'
                         : paceVsBudget >= 90   ? '#E8C45A'
                         : '#E87A7A';

    // sparkline data for this venue (last 14 days)
    const vm = VENUE_META.find(x => x.id === v.id);
    const sparkId = 'spark_' + v.id + '_' + currentISO.replace(/-/g,'');

    // sub venues
    let subHtml = '';
    if (v.sub_venues && v.sub_venues.length) {{
      subHtml = '<div class="sub-rows">' +
        v.sub_venues.map(s => `<div class="sub-row"><span>${{s.name}}</span><span>${{fmtC(s.sales)}}</span></div>`).join('') +
        '</div>';
    }}

    // tags
    const tags86   = (v.eightysixed||[]).map(t => `<span class="tag tag-86">86: ${{t}}</span>`).join('');
    const tagsMaint = (v.maintenance_flags||[]).map(t => `<span class="tag tag-maint">🔧 ${{t}}</span>`).join('');
    const tagsHtml  = (tags86 + tagsMaint) ? `<div class="tags">${{tags86}}${{tagsMaint}}</div>` : '';

    // highlights
    const icons = {{win:'✅',urgent:'🚨',flag:'⚠️',info:'ℹ️'}};
    const hlHtml = (v.highlights||[]).map(h =>
      `<div class="hl"><span class="hl-icon">${{icons[h.type]||'•'}}</span><span>${{h.text}}</span></div>`
    ).join('');

    const dateNote = v.date_note ? `<div class="date-warn">${{v.date_note}}</div>` : '';

    html += `
    <div class="vcard" style="border-top:3px solid ${{v.color||'#888'}}">
      <div class="vcard-head">
        <span class="vcard-dot" style="background:${{v.color||'#888'}}"></span>
        <span class="vcard-name">${{v.full_name}}</span>
        <span class="vcard-date">${{v.date_reported||''}}</span>
      </div>
      ${{dateNote}}
      <div class="sales-row">
        <div class="sbox">
          <div class="sbox-label">Net Sales</div>
          <div class="sbox-val">${{fmtC(ns)}}</div>
        </div>
        <div class="sbox">
          <div class="sbox-label">${{v.data_source === 'r365' ? 'R365 Forecast' : 'Daily Target'}}</div>
          <div class="sbox-sm">${{fmtC(tg)}}</div>
        </div>
        <div class="sbox" style="background:${{vCol}}18;border:1px solid ${{vCol}}33;text-align:center">
          <div class="sbox-label">vs Forecast</div>
          <div class="sbox-pct" style="color:${{vCol}}">${{vPct !== null ? (vPct > 0 ? '+' : '') + vPct + '%' : '—'}}</div>
          <div class="sbox-abs">${{varAbs !== null ? (varAbs >= 0 ? '+' : '') + fmtC(varAbs) : '—'}}</div>
        </div>
      </div>
      ${{mb !== null ? `
      <div class="pace-section">
        <div class="pace-meta">
          <div class="pace-stat">
            <div class="pace-stat-label">MTD Actual</div>
            <div class="pace-stat-val">${{Math.round(mtdActual).toLocaleString()}}</div>
          </div>
          <div class="pace-stat" style="text-align:center">
            <div class="pace-stat-label">Projected Pace</div>
            <div class="pace-stat-val" style="color:${{paceColor}}">${{paceProj.toLocaleString()}}</div>
          </div>
          <div class="pace-stat" style="text-align:right">
            <div class="pace-stat-label">Monthly Budget</div>
            <div class="pace-stat-val budget">${{Math.round(mb).toLocaleString()}}</div>
          </div>
        </div>
        <div class="pace-bar-track">
          <div class="pace-bar-fill" style="width:${{paceBarWidth}}%;background:${{paceColor}}"></div>
        </div>
        <div class="pace-footer">
          <span>${{daysElapsed}} of ${{daysInMonth}} days elapsed</span>
          <span class="pace-pct" style="color:${{paceColor}}">${{paceVsBudget !== null ? paceVsBudget + '% of budget pace' : 'no budget'}}</span>
        </div>
      </div>` : ''}}
      <div class="fin-grid">
        <div class="fin"><div class="fin-label">Food</div><div class="fin-val">${{fmtC(v.food_sales)}}</div></div>
        <div class="fin"><div class="fin-label">Beverage</div><div class="fin-val">${{fmtC(v.beverage_sales)}}</div></div>
        <div class="fin"><div class="fin-label">Events</div><div class="fin-val">${{fmtC(v.event_sales)}}</div></div>
        <div class="fin"><div class="fin-label">Comps</div><div class="fin-val">${{fmtC(v.comps)}}${{v.comp_pct ? ' (' + v.comp_pct + '%)' : ''}}</div></div>
        <div class="fin"><div class="fin-label">Guests</div><div class="fin-val">${{v.guests != null ? v.guests : (v.guest_count || '—')}}</div></div>
        <div class="fin"><div class="fin-label">Check Avg</div><div class="fin-val">${{fmtC(v.check_avg != null ? v.check_avg : v.guest_check_avg)}}</div></div>
      </div>
      ${{subHtml}}
      <div class="ops-row">
        <span class="ops-item"><b>MOD:</b> ${{v.mod||'—'}}</span>
        <span class="ops-item"><b>Weather:</b> ${{v.weather||'—'}}</span>
      </div>
      ${{v.notes_summary ? `<div class="vnotes">${{v.notes_summary}}</div>` : ''}}
      ${{tagsHtml}}
      ${{hlHtml ? `<div class="hls">${{hlHtml}}</div>` : ''}}
      <!-- Sparkline: last 14 days for this venue -->
      <div>
        <div style="font-size:9px;text-transform:uppercase;letter-spacing:.6px;color:#444;margin-bottom:5px">14-Day Trend</div>
        <div class="spark-wrap"><canvas id="${{sparkId}}"></canvas></div>
      </div>
    </div>`;
  }});

  document.getElementById('venue-grid').innerHTML = html;

  // Render sparklines after DOM update
  requestAnimationFrame(() => {{
    (day.venues || []).forEach(v => {{
      if (v.missing) return;
      renderSparkline(v.id, currentISO);
    }});
  }});
}}

function renderSparkline(venueId, currentDate) {{
  const sparkId = 'spark_' + venueId + '_' + currentDate.replace(/-/g,'');
  const canvas  = document.getElementById(sparkId);
  if (!canvas) return;
  destroyChart(sparkId);

  const vd = CHART_DATA.venues.find(v => v.id === venueId);
  if (!vd) return;

  // get last 14 days up to and including currentDate
  const allDates  = CHART_DATA.isos;
  const curIdx    = allDates.indexOf(currentDate);
  const endIdx    = curIdx >= 0 ? curIdx : allDates.length - 1;
  const startIdx  = Math.max(0, endIdx - 13);
  const sliceDates   = CHART_DATA.dates.slice(startIdx, endIdx + 1);
  const sliceActual  = vd.actual.slice(startIdx, endIdx + 1);
  const sliceTarget  = vd.target.slice(startIdx, endIdx + 1);

  const vm = VENUE_META.find(v => v.id === venueId);
  const color = vm ? vm.color : '#888';

  chartInstances[sparkId] = new Chart(canvas.getContext('2d'), {{
    type: 'bar',
    data: {{
      labels: sliceDates,
      datasets: [
        {{
          label: 'Actual',
          data: sliceActual,
          backgroundColor: color + '88',
          borderColor: color,
          borderWidth: 1,
          borderRadius: 2,
        }},
        {{
          label: 'Target',
          data: sliceTarget,
          type: 'line',
          borderColor: '#888',
          borderDash: [4, 3],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#1C1F2A',
          borderColor: '#2A2D3A',
          borderWidth: 1,
          titleColor: '#fff',
          bodyColor: '#aaa',
          callbacks: {{
            label: ctx => ctx.dataset.label + ': $' + Math.round(ctx.raw || 0).toLocaleString()
          }}
        }}
      }},
      scales: {{
        x: {{ display: false }},
        y: {{
          display: false,
          beginAtZero: true,
          suggestedMin: 0
        }}
      }}
    }}
  }});
}}

// ── WEEKLY VIEW ───────────────────────────────────────────────
function renderWeekly() {{
  destroyChart('weeklyChart');

  // last 7 available dates up to currentISO
  const curIdx   = AVAIL.indexOf(currentISO);
  const endIdx   = curIdx >= 0 ? curIdx : AVAIL.length - 1;
  const startIdx = Math.max(0, endIdx - 6);
  const week     = AVAIL.slice(startIdx, endIdx + 1);

  // Day cards
  let cardHtml = '';
  week.forEach(iso => {{
    const day = HISTORY[iso];
    if (!day) {{ cardHtml += `<div class="wday-card"><div class="wday-label">${{shortIso(iso)}}</div><div class="wday-val">—</div></div>`; return; }}
    const reporting = (day.venues||[]).filter(v => !v.missing);
    const s = reporting.reduce((a,v) => a + (v.net_sales||0), 0);
    const t = reporting.reduce((a,v) => a + (v.target||0), 0);
    const vp = fmtPct(s, t);
    const vc = pctColor(s, t);
    const isToday = iso === currentISO;
    cardHtml += `
    <div class="wday-card${{isToday ? ' today' : ''}}">
      <div class="wday-label">${{shortIso(iso)}}</div>
      <div class="wday-val">${{fmtC(s)}}</div>
      <div class="wday-pct" style="color:${{vc}}">${{vp !== null ? (vp>0?'+':'') + vp + '%' : '—'}}</div>
    </div>`;
  }});
  document.getElementById('weekly-day-cards').innerHTML = cardHtml;

  // Bar chart
  const labels  = week.map(shortIso);
  const actuals = week.map(iso => {{
    const d = HISTORY[iso];
    if (!d) return 0;
    return (d.venues||[]).filter(v=>!v.missing).reduce((a,v)=>a+(v.net_sales||0),0);
  }});
  const targets = week.map(iso => {{
    const d = HISTORY[iso];
    if (!d) return 0;
    return (d.venues||[]).filter(v=>!v.missing).reduce((a,v)=>a+(v.target||0),0);
  }});

  chartInstances['weeklyChart'] = new Chart(
    document.getElementById('weeklyChart').getContext('2d'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{
          label: 'Actual',
          data: actuals,
          backgroundColor: '#5BC88A88',
          borderColor: '#5BC88A',
          borderWidth: 1,
          borderRadius: 4,
        }},
        {{
          label: 'Target',
          data: targets,
          type: 'line',
          borderColor: '#C8CAFF',
          borderDash: [6,4],
          borderWidth: 2,
          pointRadius: 4,
          pointBackgroundColor: '#C8CAFF',
          fill: false,
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#888', font: {{ size: 12 }} }} }},
        tooltip: {{
          backgroundColor: '#1C1F2A', borderColor: '#2A2D3A', borderWidth: 1,
          titleColor: '#fff', bodyColor: '#aaa',
          callbacks: {{ label: ctx => ctx.dataset.label + ': $' + Math.round(ctx.raw).toLocaleString() }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1E2030' }}, ticks: {{ color: '#666', font: {{ size: 11 }} }} }},
        y: {{
          grid: {{ color: '#1E2030' }},
          ticks: {{ color: '#666', font: {{ size: 11 }}, callback: v => '$' + (v/1000).toFixed(0) + 'k' }}
        }}
      }}
    }}
  }});

  // Venue table
  let tHtml = `<table style="width:100%;border-collapse:collapse;font-size:12px">
    <thead>
      <tr style="border-bottom:1px solid #2A2D3A">
        <th style="text-align:left;padding:8px 6px;color:#555;font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.6px">Venue</th>`;
  week.forEach(iso => {{ tHtml += `<th style="padding:8px 6px;color:#555;font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.6px">${{shortIso(iso)}}</th>`; }});
  tHtml += `<th style="padding:8px 6px;color:#555;font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.6px">7-Day Total</th></tr></thead><tbody>`;

  VENUE_META.forEach(vm => {{
    tHtml += `<tr style="border-bottom:1px solid #1E2030">
      <td style="padding:8px 6px;color:#E0E0E0;font-weight:600">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${{vm.color}};margin-right:6px"></span>
        ${{vm.name}}
      </td>`;
    let total = 0;
    week.forEach(iso => {{
      const d = HISTORY[iso];
      const v = d ? (d.venues||[]).find(x=>x.id===vm.id) : null;
      const s = (v && !v.missing) ? (v.net_sales||0) : null;
      const t = (v && !v.missing) ? (v.target||0) : null;
      const vc = s !== null ? pctColor(s, t) : '#555';
      if (s !== null) total += s;
      tHtml += `<td style="text-align:center;padding:8px 6px;color:${{s !== null ? '#C0C0C0' : '#333'}}">${{s !== null ? fmtC(s) : '—'}}</td>`;
    }});
    tHtml += `<td style="text-align:center;padding:8px 6px;color:#fff;font-weight:600">${{total > 0 ? fmtC(total) : '—'}}</td></tr>`;
  }});
  tHtml += '</tbody></table>';
  document.getElementById('weekly-venue-table').innerHTML = tHtml;
}}

// ── MTD VIEW ──────────────────────────────────────────────────
function renderMTD() {{
  destroyChart('mtdChart');

  // filter to current month only
  const curDate = new Date(currentISO + 'T12:00:00');
  const curYM   = currentISO.slice(0, 7); // "2026-03"
  const monthDates = CHART_DATA.isos.filter(iso => iso.startsWith(curYM));
  const allIsos    = CHART_DATA.isos;
  const monthIdx   = monthDates.map(d => allIsos.indexOf(d));

  const labels    = monthDates.map(label_date_js);
  const c_actual  = monthIdx.map(i => CHART_DATA.c_actual[i]);
  const c_target  = monthIdx.map(i => CHART_DATA.c_target[i]);

  const datasets = [
    {{
      label: 'Consolidated Actual',
      data: c_actual,
      borderColor: '#5BC88A',
      backgroundColor: 'rgba(91,200,138,0.07)',
      borderWidth: 3,
      pointRadius: 4,
      fill: true,
      tension: 0.3,
      order: 0,
    }},
    {{
      label: 'Consolidated Target',
      data: c_target,
      borderColor: '#C8CAFF',
      borderDash: [6,4],
      borderWidth: 2,
      pointRadius: 3,
      fill: false,
      tension: 0.3,
      order: 1,
    }},
    ...VENUE_META.map((vm, i) => {{
      const vd = CHART_DATA.venues.find(v => v.id === vm.id);
      const data = monthIdx.map(idx => vd ? vd.actual[idx] : null);
      return {{
        label: vm.name,
        data,
        borderColor: vm.color,
        backgroundColor: vm.color + '20',
        borderWidth: 1.5,
        pointRadius: 2,
        fill: false,
        tension: 0.3,
        hidden: !visibleVenues.has(vm.id),
        order: i + 2,
      }};
    }})
  ];

  chartInstances['mtdChart'] = new Chart(
    document.getElementById('mtdChart').getContext('2d'), {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#1C1F2A', borderColor: '#2A2D3A', borderWidth: 1,
          titleColor: '#fff', bodyColor: '#aaa',
          callbacks: {{
            label: ctx => ctx.dataset.label + ': ' +
              (ctx.raw != null ? '$' + Math.round(ctx.raw).toLocaleString() : '—')
          }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1E2030' }}, ticks: {{ color: '#666', font: {{ size: 11 }} }} }},
        y: {{
          grid: {{ color: '#1E2030' }},
          ticks: {{ color: '#666', font: {{ size: 11 }}, callback: v => '$' + (v/1000).toFixed(0) + 'k' }}
        }}
      }}
    }}
  }});

  // Build custom legend
  let legendHtml = `
    <div class="legend-item active" onclick="toggleMTDLine(-1, this)" data-idx="0">
      <span class="legend-dot" style="background:#5BC88A"></span> Consolidated Actual
    </div>
    <div class="legend-item active" onclick="toggleMTDLine(-2, this)" data-idx="1">
      <span class="legend-dash" style="border-color:#C8CAFF"></span> Consolidated Target
    </div>`;
  VENUE_META.forEach((vm, i) => {{
    const active = visibleVenues.has(vm.id) ? 'active' : '';
    legendHtml += `<div class="legend-item ${{active}}" onclick="toggleMTDVenue('${{vm.id}}', this)">
      <span class="legend-dot" style="background:${{vm.color}}"></span> ${{vm.name}}
    </div>`;
  }});
  document.getElementById('mtdLegend').innerHTML = legendHtml;
}}

function toggleMTDLine(dsIdx, el) {{
  const chart = chartInstances['mtdChart'];
  if (!chart) return;
  const idx = dsIdx < 0 ? (dsIdx === -1 ? 0 : 1) : dsIdx;
  const meta = chart.getDatasetMeta(idx);
  meta.hidden = !meta.hidden;
  chart.update();
  el.classList.toggle('active');
}}

function toggleMTDVenue(venueId, el) {{
  const chart = chartInstances['mtdChart'];
  if (!chart) return;
  // venue datasets start at index 2
  const idx = 2 + VENUE_META.findIndex(v => v.id === venueId);
  const meta = chart.getDatasetMeta(idx);
  meta.hidden = !meta.hidden;
  chart.update();
  el.classList.toggle('active');
  if (visibleVenues.has(venueId)) visibleVenues.delete(venueId);
  else visibleVenues.add(venueId);
}}

function label_date_js(iso) {{
  try {{
    const d = new Date(iso + 'T12:00:00');
    return d.toLocaleDateString('en-US', {{weekday:'short', month:'numeric', day:'numeric'}});
  }} catch(e) {{ return iso; }}
}}

// ── YTD VIEW ──────────────────────────────────────────────────
function renderYTD() {{
  destroyChart('ytdMonthlyChart');
  destroyChart('ytdCumulativeChart');

  // Current year derived from currentISO
  const curYear = currentISO.slice(0, 4);

  // ── Aggregate by month ────────────────────────────────────
  const monthMap = {{}};   // "2026-01" → {{actual:0, target:0, venues:{{id:{{actual,target}}}}}}
  const allMonths = [];

  Object.entries(HISTORY).forEach(([iso, day]) => {{
    if (!iso.startsWith(curYear)) return;
    const ym = iso.slice(0, 7);
    if (!monthMap[ym]) {{
      monthMap[ym] = {{ actual: 0, target: 0, venues: {{}} }};
      allMonths.push(ym);
    }}
    const rv = (day.venues || []).filter(v => !v.missing);
    rv.forEach(v => {{
      monthMap[ym].actual += (v.net_sales || 0);
      monthMap[ym].target += (v.target    || 0);
      if (!monthMap[ym].venues[v.id]) monthMap[ym].venues[v.id] = {{actual:0, target:0}};
      monthMap[ym].venues[v.id].actual += (v.net_sales || 0);
      monthMap[ym].venues[v.id].target += (v.target    || 0);
    }});
  }});

  allMonths.sort();

  // Build full year skeleton so all 12 months appear on axis
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const allYearMonths = MONTHS.map((_, i) => `${{curYear}}-${{String(i+1).padStart(2,'0')}}`);
  const monthLabels   = MONTHS;
  const actualByMonth = allYearMonths.map(ym => monthMap[ym] ? monthMap[ym].actual : null);
  const targetByMonth = allYearMonths.map(ym => monthMap[ym] ? monthMap[ym].target : null);

  // Cumulative running totals
  let cumActual = 0, cumTarget = 0;
  const cumActualArr = [], cumTargetArr = [];
  allYearMonths.forEach(ym => {{
    if (monthMap[ym]) {{
      cumActual += monthMap[ym].actual;
      cumTarget += monthMap[ym].target;
      cumActualArr.push(cumActual);
      cumTargetArr.push(cumTarget);
    }} else {{
      cumActualArr.push(null);
      cumTargetArr.push(null);
    }}
  }});

  // ── YTD KPI strip ─────────────────────────────────────────
  const ytdActual = allMonths.reduce((s, ym) => s + (monthMap[ym]?.actual || 0), 0);
  const ytdTarget = allMonths.reduce((s, ym) => s + (monthMap[ym]?.target || 0), 0);
  const ytdVar    = ytdActual - ytdTarget;
  const ytdVarPct = ytdTarget ? (ytdVar / ytdTarget * 100).toFixed(1) : null;
  const ytdVC     = ytdVar >= 0 ? '#5BC88A' : '#E87A7A';
  const ytdSign   = ytdVar >= 0 ? '+' : '';
  const daysIn    = allMonths.reduce((s, ym) => {{
    return s + Object.keys(HISTORY).filter(d => d.startsWith(ym)).length;
  }}, 0);

  document.getElementById('ytd-kpis').innerHTML = `
    <div class="kpi">
      <div class="kpi-label">YTD Net Sales</div>
      <div class="kpi-value">${{fmtC(ytdActual)}}</div>
      <div class="kpi-sub">${{daysIn}} days of data · ${{curYear}}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">YTD Target</div>
      <div class="kpi-value" style="color:#C8CAFF">${{fmtC(ytdTarget)}}</div>
      <div class="kpi-sub">Consolidated across all venues</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">YTD Variance</div>
      <div class="kpi-value" style="color:${{ytdVC}}">${{ytdSign}}${{fmtC(ytdVar)}}</div>
      <div class="kpi-sub" style="color:${{ytdVC}}">${{ytdVarPct !== null ? ytdSign + ytdVarPct + '%' : '—'}} vs target</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Months Active</div>
      <div class="kpi-value" style="color:#C8CAFF">${{allMonths.length}}<span style="font-size:16px;color:#555"> /12</span></div>
      <div class="kpi-sub">Building as reports accumulate</div>
    </div>`;

  // ── Monthly bar chart ─────────────────────────────────────
  chartInstances['ytdMonthlyChart'] = new Chart(
    document.getElementById('ytdMonthlyChart').getContext('2d'), {{
    type: 'bar',
    data: {{
      labels: monthLabels,
      datasets: [
        {{
          label: 'Actual Revenue',
          data: actualByMonth,
          backgroundColor: actualByMonth.map((v, i) => {{
            if (v === null) return 'transparent';
            const t = targetByMonth[i];
            return (t && v >= t) ? '#5BC88A88' : '#E8C45A88';
          }}),
          borderColor: actualByMonth.map((v, i) => {{
            if (v === null) return 'transparent';
            const t = targetByMonth[i];
            return (t && v >= t) ? '#5BC88A' : '#E8C45A';
          }}),
          borderWidth: 1,
          borderRadius: 4,
          order: 2,
        }},
        {{
          label: 'Target',
          data: targetByMonth,
          type: 'line',
          borderColor: '#C8CAFF',
          borderDash: [6, 4],
          borderWidth: 2,
          pointRadius: targetByMonth.map(v => v !== null ? 4 : 0),
          pointBackgroundColor: '#C8CAFF',
          fill: false,
          spanGaps: false,
          order: 1,
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#888', font: {{ size: 12 }} }} }},
        tooltip: {{
          backgroundColor: '#1C1F2A', borderColor: '#2A2D3A', borderWidth: 1,
          titleColor: '#fff', bodyColor: '#aaa',
          callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.raw != null ? '$' + Math.round(ctx.raw).toLocaleString() : '—') }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1E2030' }}, ticks: {{ color: '#666', font: {{ size: 11 }} }} }},
        y: {{
          grid: {{ color: '#1E2030' }}, beginAtZero: true,
          ticks: {{ color: '#666', font: {{ size: 11 }}, callback: v => '$' + (v >= 1000000 ? (v/1000000).toFixed(1)+'M' : (v/1000).toFixed(0)+'k') }}
        }}
      }}
    }}
  }});

  // ── Cumulative chart ──────────────────────────────────────
  chartInstances['ytdCumulativeChart'] = new Chart(
    document.getElementById('ytdCumulativeChart').getContext('2d'), {{
    type: 'line',
    data: {{
      labels: monthLabels,
      datasets: [
        {{
          label: 'Cumulative Actual',
          data: cumActualArr,
          borderColor: '#5BC88A',
          backgroundColor: 'rgba(91,200,138,0.08)',
          borderWidth: 2.5,
          pointRadius: cumActualArr.map(v => v !== null ? 4 : 0),
          pointBackgroundColor: '#5BC88A',
          fill: true,
          tension: 0.3,
          spanGaps: false,
        }},
        {{
          label: 'Cumulative Target',
          data: cumTargetArr,
          borderColor: '#C8CAFF',
          borderDash: [6, 4],
          borderWidth: 2,
          pointRadius: cumTargetArr.map(v => v !== null ? 3 : 0),
          pointBackgroundColor: '#C8CAFF',
          fill: false,
          tension: 0.3,
          spanGaps: false,
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#888', font: {{ size: 12 }} }} }},
        tooltip: {{
          backgroundColor: '#1C1F2A', borderColor: '#2A2D3A', borderWidth: 1,
          titleColor: '#fff', bodyColor: '#aaa',
          callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.raw != null ? '$' + Math.round(ctx.raw).toLocaleString() : '—') }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1E2030' }}, ticks: {{ color: '#666', font: {{ size: 11 }} }} }},
        y: {{
          grid: {{ color: '#1E2030' }},
          ticks: {{ color: '#666', font: {{ size: 11 }}, callback: v => '$' + (v >= 1000000 ? (v/1000000).toFixed(1)+'M' : (v/1000).toFixed(0)+'k') }}
        }}
      }}
    }}
  }});

  // ── Per-venue monthly table ───────────────────────────────
  if (!allMonths.length) {{
    document.getElementById('ytd-venue-table').innerHTML =
      '<div style="color:#555;padding:16px;font-size:13px">No data yet for ' + curYear + '. Table will populate as reports accumulate.</div>';
    return;
  }}

  const activeMonths = allYearMonths.filter(ym => monthMap[ym]);
  let tHtml = `<table style="width:100%;border-collapse:collapse;font-size:12px;min-width:600px">
    <thead><tr style="border-bottom:1px solid #2A2D3A">
      <th style="text-align:left;padding:9px 8px;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.6px;font-weight:600">Venue</th>`;
  activeMonths.forEach(ym => {{
    const [, m] = ym.split('-');
    tHtml += `<th style="padding:9px 8px;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.6px;font-weight:600;text-align:right">${{MONTHS[parseInt(m)-1]}}</th>`;
  }});
  tHtml += `<th style="padding:9px 8px;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.6px;font-weight:600;text-align:right">YTD Total</th>
    </tr></thead><tbody>`;

  VENUE_META.forEach(vm => {{
    const ytdV = activeMonths.reduce((s, ym) => s + (monthMap[ym]?.venues[vm.id]?.actual || 0), 0);
    tHtml += `<tr style="border-bottom:1px solid #1E2030">
      <td style="padding:9px 8px;color:#E0E0E0;font-weight:600;white-space:nowrap">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${{vm.color}};margin-right:7px"></span>${{vm.name}}
      </td>`;
    activeMonths.forEach(ym => {{
      const a = monthMap[ym]?.venues[vm.id]?.actual;
      const t = monthMap[ym]?.venues[vm.id]?.target;
      const vc = (a != null && t != null) ? (a >= t ? '#5BC88A' : (a > t * 0.9 ? '#E8C45A' : '#E87A7A')) : '#333';
      tHtml += `<td style="text-align:right;padding:9px 8px;color:${{a != null ? '#C0C0C0' : '#333'}}">${{a != null ? '$' + Math.round(a).toLocaleString() : '—'}}</td>`;
    }});
    tHtml += `<td style="text-align:right;padding:9px 8px;color:#fff;font-weight:700">${{ytdV > 0 ? '$' + Math.round(ytdV).toLocaleString() : '—'}}</td>
    </tr>`;
  }});

  // Totals row
  tHtml += `<tr style="border-top:2px solid #2A2D3A;background:#1C1F2A">
    <td style="padding:9px 8px;color:#E0E0E0;font-weight:700">All Venues</td>`;
  activeMonths.forEach(ym => {{
    const a = monthMap[ym]?.actual;
    tHtml += `<td style="text-align:right;padding:9px 8px;color:#fff;font-weight:700">${{a != null ? '$' + Math.round(a).toLocaleString() : '—'}}</td>`;
  }});
  tHtml += `<td style="text-align:right;padding:9px 8px;color:#5BC88A;font-weight:700">${{ytdActual ? '$' + Math.round(ytdActual).toLocaleString() : '—'}}</td></tr>`;
  tHtml += '</tbody></table>';
  document.getElementById('ytd-venue-table').innerHTML = tHtml;
}}

// ── INIT ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  if (AVAIL.length) currentISO = AVAIL[AVAIL.length - 1];
  renderCurrentView();
}});
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def generate_index(history: dict, dashboard_filename: str = "EON_Dashboard.html") -> str:
    """
    Generate a lightweight index.html for the shared Drive folder.
    Shows the last 7 days as digest cards, with a prominent link to the full dashboard.
    """
    sorted_dates = sorted(history.keys(), reverse=True)
    latest_iso   = sorted_dates[0] if sorted_dates else None
    latest_day   = history.get(latest_iso, {}) if latest_iso else {}

    # Latest day headline stats
    reporting = [v for v in latest_day.get("venues", []) if not v.get("missing")]
    total_s = sum(v.get("net_sales") or 0 for v in reporting)
    total_t = sum(v.get("target")    or 0 for v in reporting)
    var_abs = total_s - total_t
    var_pct = round((var_abs / total_t * 100), 1) if total_t else 0
    var_sign = "+" if var_abs >= 0 else ""
    var_color = "#5BC88A" if var_abs >= 0 else "#E87A7A"

    def latest_label():
        if not latest_iso: return "—"
        d = datetime.strptime(latest_iso, "%Y-%m-%d")
        return d.strftime("%A, %B %-d, %Y")

    # Digest rows — last 7 days
    digest_html = ""
    for iso in sorted_dates[:7]:
        day  = history[iso]
        rv   = [v for v in day.get("venues", []) if not v.get("missing")]
        s    = sum(v.get("net_sales") or 0 for v in rv)
        t    = sum(v.get("target")    or 0 for v in rv)
        va   = s - t
        vp   = round((va / t * 100), 1) if t else 0
        vc   = "#5BC88A" if va >= 0 else "#E87A7A"
        vs   = "+" if va >= 0 else ""
        try:
            d_label = datetime.strptime(iso, "%Y-%m-%d").strftime("%a %-m/%-d")
        except Exception:
            d_label = iso
        dow   = day.get("day_of_week", "")
        badge = f'<span style="color:{vc};font-weight:700">{vs}{vp}%</span>'
        urgent_count = sum(
            1 for v in day.get("venues", [])
            for h in v.get("highlights", []) if h.get("type") == "urgent"
        )
        flag_html = (f'<span style="color:#E87A7A;font-size:11px">🚨 {urgent_count} urgent</span>'
                     if urgent_count else "")
        digest_html += f"""
        <div style="display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid #1E2030">
          <div style="display:flex;align-items:center;gap:12px">
            <div>
              <div style="font-size:13px;font-weight:600;color:#E0E0E0">{d_label} <span style="color:#555;font-weight:400;font-size:12px">{dow}</span></div>
              {f'<div style="margin-top:3px">{flag_html}</div>' if flag_html else ""}
            </div>
          </div>
          <div style="text-align:right">
            <div style="font-size:14px;font-weight:700;color:#fff">${s:,.0f}</div>
            <div style="font-size:11px;color:#555">tgt ${t:,.0f} &nbsp;{badge}</div>
          </div>
        </div>"""

    generated_at = datetime.now().strftime("%B %-d, %Y at %-I:%M %p")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>G&L EON Reports</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0F1117;color:#E0E0E0;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:40px 20px}}
  .container{{width:100%;max-width:560px}}
  .header{{text-align:center;margin-bottom:32px}}
  .header h1{{font-size:22px;font-weight:700;color:#fff;letter-spacing:-.3px}}
  .header p{{font-size:13px;color:#555;margin-top:6px}}
  .hero{{background:linear-gradient(135deg,#1C2030,#1A1D27);border:1px solid #2A2D3A;border-radius:14px;padding:28px;margin-bottom:20px;text-align:center}}
  .hero-label{{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#555;margin-bottom:8px}}
  .hero-date{{font-size:16px;font-weight:600;color:#C8CAFF;margin-bottom:18px}}
  .hero-sales{{font-size:42px;font-weight:800;color:#fff;line-height:1;margin-bottom:6px}}
  .hero-var{{font-size:15px;margin-bottom:22px}}
  .cta{{display:inline-block;background:#5BC88A;color:#0F1117;font-weight:700;font-size:15px;padding:13px 32px;border-radius:9px;text-decoration:none;transition:opacity .15s}}
  .cta:hover{{opacity:.88}}
  .digest{{background:#16181F;border:1px solid #2A2D3A;border-radius:12px;overflow:hidden;margin-bottom:20px}}
  .digest-title{{padding:13px 16px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#555;border-bottom:1px solid #1E2030}}
  .footer{{font-size:11px;color:#333;text-align:center;margin-top:8px}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Gin &amp; Luck</h1>
    <p>End of Night Reports</p>
  </div>

  <div class="hero">
    <div class="hero-label">Latest Report</div>
    <div class="hero-date">{latest_label()}</div>
    <div class="hero-sales">${total_s:,.0f}</div>
    <div class="hero-var" style="color:{var_color}">{var_sign}${abs(var_abs):,.0f} ({var_sign}{var_pct}%) vs target</div>
    <a class="cta" href="{dashboard_filename}">Open Full Dashboard →</a>
  </div>

  <div class="digest">
    <div class="digest-title">Recent Reports</div>
    {digest_html}
  </div>

  <div class="footer">Updated {generated_at} &nbsp;·&nbsp; Open EON_Dashboard.html for full navigation, charts &amp; venue breakdown</div>
</div>
</body>
</html>"""


def find_missing_days(lookback: int = 7) -> list:
    """
    Return a sorted list of ISO date strings (YYYY-MM-DD) for the last
    `lookback` days that have no corresponding file in eon_data/.
    Today is excluded — we never flag the current day as missing.
    """
    from datetime import timedelta
    today = date.today()
    missing = []
    for i in range(1, lookback + 1):
        d = today - timedelta(days=i)
        iso = d.strftime("%Y-%m-%d")
        path = os.path.join(DATA_DIR, f"{iso}.json")
        if not os.path.exists(path):
            missing.append(iso)
    return sorted(missing)


def regenerate_only(output_path: str):
    """Reload all history and rebuild HTML/index without saving new day data."""
    history = load_all_history()
    print(f"Loaded {len(history)} days of history")
    latest_iso = sorted(history.keys())[-1] if history else None
    today_data = history.get(latest_iso, {})

    html = generate_html(today_data, history)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Dashboard written → {output_path}")

    index_path = os.path.join(os.path.dirname(output_path), "index.html")
    idx_html = generate_index(history, os.path.basename(output_path))
    with open(index_path, "w") as f:
        f.write(idx_html)
    print(f"Index written    → {index_path}")
    return len(history)


def save_only(data: dict):
    """Save a day's JSON data to eon_data/ without regenerating HTML."""
    iso = save_day_data(data)
    print(f"Saved day data → eon_data/{iso}.json")
    return iso


def run(today_data: dict, output_path: str):
    iso = save_day_data(today_data)
    print(f"Saved day data → eon_data/{iso}.json")
    history = load_all_history()
    print(f"Loaded {len(history)} days of history")

    html = generate_html(today_data, history)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Dashboard written → {output_path}")

    # Also write index.html in the same folder
    index_path = os.path.join(os.path.dirname(output_path), "index.html")
    idx_html = generate_index(history, os.path.basename(output_path))
    with open(index_path, "w") as f:
        f.write(idx_html)
    print(f"Index written    → {index_path}")

    return iso, len(history)


# ─────────────────────────────────────────────────────────────
# DEFAULT DATA — March 30, 2026
# ─────────────────────────────────────────────────────────────
TODAY_DATA = {
    "report_date": "March 30, 2026",
    "iso_date":    "2026-03-30",
    "day_of_week": "Monday",
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "venues": [
        {
            "id": "ccatl", "name": "CC Atlanta",
            "full_name": "Close Company Atlanta", "color": "#E07B54",
            "date_reported": "3/30/2026", "missing": False,
            "target": 985, "net_sales": 4968,
            "food_sales": 43, "beverage_sales": 4925, "event_sales": 0,
            "comps": 56.30, "comp_pct": 1.1,
            "guest_count": 108, "guest_check_avg": 46.0,
            "mod": "MKZ", "weather": "Sunny, 75°",
            "notes_summary": "Bartenders Day Off with Empirical crew — strong event, great team energy and incremental revenue.",
            "maintenance_flags": ["Combi oven down — Rational helpdesk tech reset required"],
            "eightysixed": ["Aperol"],
            "highlights": [
                {"type": "win",    "text": "Bartenders Day Off event drove strong incremental revenue and team morale"},
                {"type": "urgent", "text": "Combi oven down — requires Rational tech manual reset; local company contacted"},
                {"type": "info",   "text": "Aperol 86'd"}
            ]
        },
        {
            "id": "ccnsh", "name": "CC Nashville",
            "full_name": "Close Company Nashville", "color": "#6B8CBA",
            "date_reported": "3/30/2026", "missing": False,
            "target": 979, "net_sales": 934,
            "food_sales": 53, "beverage_sales": 881, "event_sales": 0,
            "comps": 145, "comp_pct": 15.5,
            "guest_count": 30, "guest_check_avg": 31.0,
            "mod": "KE / Tay", "weather": "Mild, nice",
            "notes_summary": "Slower Monday. ~1/3 of sales in final 2.5 hrs. Industry-heavy comp night with a memorable hospitality moment.",
            "maintenance_flags": [],
            "eightysixed": ["Cucumbers", "Totchos"],
            "highlights": [
                {"type": "flag", "text": "Comps at 15.5% — higher than typical Monday (industry guests + food gift)"},
                {"type": "win",  "text": "First-ever martini experience for a 68-year-old guest — memorable moment"},
                {"type": "info", "text": "86'd: Cucumbers, Totchos"}
            ]
        },
        {
            "id": "mg", "name": "Municipal Grand",
            "full_name": "Municipal Grand F&B", "color": "#7CB87A",
            "date_reported": "3/30/2026", "missing": False,
            "target": 6000, "net_sales": 5929,
            "food_sales": 2265, "beverage_sales": 3664, "event_sales": 62,
            "comps": 132, "comp_pct": 2.2,
            "guest_count": 120, "guest_check_avg": None,
            "mod": "James & Karim (eve)", "weather": "Beautiful, great weather",
            "notes_summary": "6pm hour completely full. Sun Club generating evening activity. Team executing as a dialed-in machine.",
            "maintenance_flags": [], "eightysixed": [],
            "sub_venues": [
                {"name": "Municipal Bar AM", "sales": 843},
                {"name": "Municipal Bar PM", "sales": 4626},
                {"name": "Sun Club",         "sales": 460},
                {"name": "Hot Eye (closed)", "sales": 0}
            ],
            "highlights": [
                {"type": "win",  "text": "Restaurant completely full at 6pm — walk-in demand strong"},
                {"type": "win",  "text": "Team executing seamlessly; minimal corrections needed across the board"},
                {"type": "info", "text": "Sun Club evening activity growing — summer ramp-up beginning"}
            ]
        },
        {
            "id": "la", "name": "D&C LA",
            "full_name": "Death & Co Los Angeles", "color": "#C47DC0",
            "date_reported": "3/30/2026", "missing": False,
            "target": 2701, "net_sales": 4166,
            "food_sales": 842, "beverage_sales": 3324, "event_sales": 0,
            "comps": 137, "comp_pct": 3.3,
            "guest_count": 107, "guest_check_avg": 38.94,
            "mod": "Mikey P / Vic", "weather": "Cool (no A/C in basement)",
            "notes_summary": "First night on new POS — chaotic behind the scenes but guests unaware. A/C and pebble ice machine down. $1,435 in POS void test transactions does not reflect true comps.",
            "maintenance_flags": [
                "A/C not working in basement — tech scheduled by Matt",
                "Pebble ice machine down — borrowing crushed ice from Manuela"
            ],
            "eightysixed": ["Aval cider draft", "Lamb burger"],
            "highlights": [
                {"type": "urgent", "text": "A/C down in basement — Matt has tech follow-up scheduled"},
                {"type": "urgent", "text": "Pebble ice machine down — operating on borrowed ice; icesurance notified"},
                {"type": "flag",   "text": "New POS night 1 — $1,435 void tests inflate comp line; not actual guest comps"},
                {"type": "win",    "text": "Guests unaware of POS chaos — excellent composure from team"}
            ]
        },
        {
            "id": "dvr", "name": "D&C Denver",
            "full_name": "Death & Co Denver", "color": "#E8C45A",
            "date_reported": "3/30/2026", "missing": False,
            "target": 6027, "net_sales": 5307,
            "food_sales": 1543, "beverage_sales": 3764, "event_sales": 0,
            "comps": 162.55, "comp_pct": 3.06,
            "guest_count": 120, "guest_check_avg": 44.2,
            "mod": "Kira (PM) / Carey (AM)", "weather": "N/A",
            "notes_summary": "Ran out of oysters early on Oyster Monday. Down one server. FKA Twigs concert at Mission drove several pops.",
            "maintenance_flags": ["Dishwasher issues — submitted to Intelity"],
            "eightysixed": [],
            "sub_venues": [
                {"name": "D&C AM (Coffee)", "sales": 719.14},
                {"name": "D&C PM (Bar)",    "sales": 4588.11}
            ],
            "highlights": [
                {"type": "flag", "text": "Ran out of oysters early on Oyster Monday — consider increasing par"},
                {"type": "flag", "text": "Down one server — staffing gap to address"},
                {"type": "info", "text": "Concert foot traffic (FKA Twigs @ Mission) drove pops at 4:15, 6:45, 7, 8:45pm"},
                {"type": "info", "text": "Dishwasher issues submitted to Intelity"}
            ]
        },
        {
            "id": "ev", "name": "D&C East Village",
            "full_name": "Death & Co East Village", "color": "#E87A7A",
            "date_reported": "3/30/2026", "missing": False,
            "target": 2775, "net_sales": 3814,
            "food_sales": 505, "beverage_sales": 3206, "event_sales": 0,
            "comps": 87.66, "comp_pct": 2.3,
            "guest_count": 98, "guest_check_avg": 39.0,
            "mod": "Courtney & Arriel", "weather": "Warm",
            "notes_summary": "Slow open, healthy by 8pm. Sold out 69 oysters by 10pm. Top sellers: Buckhorn Exchange, Revenant, Root & Rye. Late-night thin after 11:30.",
            "maintenance_flags": [], "eightysixed": [],
            "highlights": [
                {"type": "win",  "text": "Sold out 69 oysters by 10pm — Monday oyster program building momentum"},
                {"type": "win",  "text": "Guest Taylor in to celebrate engagement — memorable hospitality moment"},
                {"type": "info", "text": "Late-night traffic drops off after 11:30pm — opportunity to develop midnight+ audience"}
            ]
        },
        {
            "id": "dc", "name": "D&C DC",
            "full_name": "Death & Co Washington DC", "color": "#5AA8C4",
            "date_reported": "3/29/2026",
            "date_note": "Most recent report is Sunday 3/29 — DC may not operate Mondays",
            "missing": False,
            "target": 4135.53, "net_sales": 4145.14,
            "food_sales": 698.50, "beverage_sales": 3446.64, "event_sales": 0,
            "comps": 92.60, "comp_pct": 2.2,
            "guest_count": 73, "guest_check_avg": 56.78,
            "mod": "Khaleel", "weather": "Sunny but chilly",
            "notes_summary": "Two Garden events: Women's History Month pop-up + private event that grew from 40 to 74 guests. Short-staffed but strong execution.",
            "maintenance_flags": ["Hot water heaters — parts ordered, awaiting status from John and Gregory"],
            "eightysixed": [],
            "highlights": [
                {"type": "win",    "text": "Private event overflowed to 74 guests (from 40) — group intends to rebook next year"},
                {"type": "flag",   "text": "Staffing gap — down a barback for event nights"},
                {"type": "urgent", "text": "Hot water heater parts still pending — follow up with John and Gregory"}
            ]
        }
    ]
}

# Also seed the last few days we already read from Slack for MTD context
SEED_HISTORY = {
    "2026-03-28": {
        "report_date": "March 28, 2026", "iso_date": "2026-03-28", "day_of_week": "Saturday",
        "venues": [
            {"id":"ccatl","name":"CC Atlanta","missing":False,"target":8097,"net_sales":7976,"food_sales":336,"beverage_sales":7640,"event_sales":0,"comps":122,"comp_pct":1.5,"guest_count":226,"guest_check_avg":35.29,"highlights":[]},
            {"id":"ccnsh","name":"CC Nashville","missing":False,"target":16987,"net_sales":12105,"food_sales":306,"beverage_sales":11799,"event_sales":0,"comps":237.75,"comp_pct":1.9,"guest_count":445,"guest_check_avg":27.20,"highlights":[]},
            {"id":"mg","name":"Municipal Grand","missing":True,"missing_reason":"No report found for 3/28"},
            {"id":"la","name":"D&C LA","missing":False,"target":18000,"net_sales":13324,"food_sales":2892,"beverage_sales":10432,"event_sales":0,"comps":451,"comp_pct":3.4,"guest_count":358,"guest_check_avg":90.54,"highlights":[]},
            {"id":"dvr","name":"D&C Denver","missing":True,"missing_reason":"No report found for 3/28"},
            {"id":"ev","name":"D&C East Village","missing":False,"target":8393,"net_sales":8571,"food_sales":909,"beverage_sales":7662,"event_sales":0,"comps":221,"comp_pct":2.6,"guest_count":226,"guest_check_avg":38,"highlights":[]},
            {"id":"dc","name":"D&C DC","missing":False,"target":12724.53,"net_sales":10552.19,"food_sales":884.20,"beverage_sales":9667.99,"event_sales":0,"comps":103.10,"comp_pct":0.9,"guest_count":250,"guest_check_avg":42.21,"highlights":[]},
        ]
    },
    "2026-03-29": {
        "report_date": "March 29, 2026", "iso_date": "2026-03-29", "day_of_week": "Sunday",
        "venues": [
            {"id":"ccatl","name":"CC Atlanta","missing":True,"missing_reason":"No report found for 3/29"},
            {"id":"ccnsh","name":"CC Nashville","missing":False,"target":1360,"net_sales":1129,"food_sales":115,"beverage_sales":1014,"event_sales":0,"comps":115,"comp_pct":10.2,"guest_count":38,"guest_check_avg":29.7,"highlights":[]},
            {"id":"mg","name":"Municipal Grand","missing":True,"missing_reason":"No report found for 3/29"},
            {"id":"la","name":"D&C LA","missing":False,"target":5395,"net_sales":3655,"food_sales":613,"beverage_sales":3042,"event_sales":0,"comps":185,"comp_pct":5.1,"guest_count":113,"guest_check_avg":77.77,"highlights":[]},
            {"id":"dvr","name":"D&C Denver","missing":False,"target":8055.95,"net_sales":9815.10,"food_sales":2737,"beverage_sales":7078.10,"event_sales":0,"comps":369.74,"comp_pct":3.77,"guest_count":245,"guest_check_avg":None,"highlights":[]},
            {"id":"ev","name":"D&C East Village","missing":False,"target":5000,"net_sales":3336,"food_sales":369,"beverage_sales":2906,"event_sales":0,"comps":72.92,"comp_pct":2.2,"guest_count":104,"guest_check_avg":32,"highlights":[]},
            {"id":"dc","name":"D&C DC","missing":False,"target":4135.53,"net_sales":4145.14,"food_sales":698.50,"beverage_sales":3446.64,"event_sales":0,"comps":92.60,"comp_pct":2.2,"guest_count":73,"guest_check_avg":56.78,"highlights":[]},
        ]
    },
}


if __name__ == "__main__":
    # ── Special modes ──────────────────────────────────────────
    #
    #  --check-gaps [N]          Print ISO dates missing from eon_data/ (last N days, default 7)
    #  --save-only path.json     Save a day JSON to eon_data/ without rebuilding HTML
    #  --regenerate              Rebuild HTML/index from existing eon_data/ files only
    #
    # Normal usage (no flags):
    #  python3 generate_eon_dashboard.py [data.json [output.html]]

    os.makedirs(DATA_DIR, exist_ok=True)

    if "--check-gaps" in sys.argv:
        idx = sys.argv.index("--check-gaps")
        try:
            lb = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            lb = 7
        gaps = find_missing_days(lb)
        if gaps:
            print("MISSING_DAYS:" + ",".join(gaps))
        else:
            print("MISSING_DAYS:none")
        sys.exit(0)

    if "--save-only" in sys.argv:
        idx = sys.argv.index("--save-only")
        json_path = sys.argv[idx + 1]
        with open(json_path) as f:
            d = json.load(f)
        iso = save_only(d)
        print(f"Saved {iso} (save-only mode)")
        sys.exit(0)

    if "--regenerate" in sys.argv:
        out = sys.argv[-1] if not sys.argv[-1].startswith("--") else OUTPUT
        if not out.endswith(".html"):
            out = OUTPUT
        n = regenerate_only(out)
        print(f"Regenerated from {n} days of history")
        sys.exit(0)

    # ── Normal run ─────────────────────────────────────────────
    # Seed prior days if not already saved
    for iso, data in SEED_HISTORY.items():
        path = os.path.join(DATA_DIR, f"{iso}.json")
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Seeded {iso}")

    # Determine input data
    if len(sys.argv) >= 2 and sys.argv[1].endswith(".json"):
        with open(sys.argv[1]) as f:
            today_data = json.load(f)
    else:
        today_data = TODAY_DATA

    # Determine output path
    out = sys.argv[2] if len(sys.argv) >= 3 else OUTPUT

    run(today_data, out)
