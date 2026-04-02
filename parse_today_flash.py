#!/usr/bin/env python3
"""
parse_today_flash.py — Daily R365 Flash Report parser for G&L EON Dashboard.

Usage:
  python3 parse_today_flash.py               # auto-detect today's date
  python3 parse_today_flash.py 2026-04-02    # parse a specific date

Looks for:
  {WORKSPACE}/daily-flash-report/FlashReport_YYYY-MM-DD.pdf
  Falls back to the most recently modified PDF in that folder.

Reads monthly budgets from:
  {WORKSPACE}/2026_budgets/GL-BM-Budgets.xlsx

Writes/updates:
  {WORKSPACE}/eon_data/YYYY-MM-DD.json
  (Preserves existing Slack narrative fields — only overlays R365 financials)
"""

import json, os, re, glob, sys
import pdfplumber
import openpyxl
from datetime import datetime, date

WORKSPACE   = os.path.dirname(os.path.abspath(__file__))
FLASH_DIR   = os.path.join(WORKSPACE, "daily-flash-report")
DATA_DIR    = os.path.join(WORKSPACE, "eon_data")
BUDGET_FILE = os.path.join(WORKSPACE, "2026_budgets", "GL-BM-Budgets.xlsx")

os.makedirs(DATA_DIR, exist_ok=True)

# ── Venue name → ID mapping ───────────────────────────────────────────────────
R365_NAME_TO_ID = {
    "close company atlanta":      "ccatl",
    "close company nashville":    "ccnsh",
    "death & co dc":              "dc",
    "death & co washington dc":   "dc",
    "death & co denver":          "dvr",
    "death & co east village":    "ev",
    "death & co la":              "la",
    "death & co los angeles":     "la",
}

R365_VENUE_META = {
    "ccatl": {"name": "CC Atlanta",       "full": "Close Company Atlanta"},
    "ccnsh": {"name": "CC Nashville",     "full": "Close Company Nashville"},
    "dc":    {"name": "D&C DC",           "full": "Death & Co DC"},
    "dvr":   {"name": "D&C Denver",       "full": "Death & Co Denver"},
    "ev":    {"name": "D&C East Village", "full": "Death & Co East Village"},
    "la":    {"name": "D&C LA",           "full": "Death & Co LA"},
}

COL_SALES     = 1
COL_FORECAST  = 2
COL_CHECK_AVG = 6
COL_GUESTS    = 9
COL_COMPS     = 33

MONTHS = ["january","february","march","april","may","june",
          "july","august","september","october","november","december"]

BUDGET_TAB_MAP = {"dvr":"dvr","ev":"ev","la":"la","dc":"dc","ccatl":"ccatl","ccnsh":"ccnsh"}
PERIOD_COLS    = [2 + (i * 3) for i in range(12)]
VENUE_ORDER    = ["ccatl","ccnsh","mg","la","dvr","ev","dc"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_dollar(s):
    if not s or str(s).strip() in ("-","","N/A"): return None
    s = str(s).strip().replace("$","").replace(",","").replace(" ","")
    if s.startswith("(") and s.endswith(")"): s = "-" + s[1:-1]
    try: return round(float(s), 2)
    except ValueError: return None

def parse_int(s):
    if not s or str(s).strip() in ("-",""): return None
    s = str(s).strip().replace(",","").replace(" ","")
    if s.startswith("(") and s.endswith(")"): s = "-" + s[1:-1]
    try: return int(float(s))
    except ValueError: return None

# ── Budget loader ─────────────────────────────────────────────────────────────
def load_budgets():
    budgets = {}
    if not os.path.exists(BUDGET_FILE):
        print(f"  [warn] Budget file not found: {BUDGET_FILE}")
        return budgets
    try:
        wb = openpyxl.load_workbook(BUDGET_FILE, data_only=True)
        for tab, vid in BUDGET_TAB_MAP.items():
            if tab not in wb.sheetnames:
                continue
            ws   = wb[tab]
            rows = list(ws.values)
            target_row = None
            for i, row in enumerate(rows):
                if any(cell and "Total Net Sales" in str(cell) for cell in row):
                    target_row = i; break
            if target_row is None:
                continue
            row = rows[target_row]
            monthly = {}
            for j, col_idx in enumerate(PERIOD_COLS):
                if col_idx < len(row):
                    try: monthly[MONTHS[j]] = round(float(row[col_idx]), 2)
                    except (TypeError, ValueError): monthly[MONTHS[j]] = None
            budgets[vid] = monthly
    except Exception as e:
        print(f"  [warn] Budget load error: {e}")
    return budgets

# ── PDF finder ────────────────────────────────────────────────────────────────
def find_pdf(target_iso):
    """
    Find the Flash Report PDF for target_iso (YYYY-MM-DD).
    1. Look for FlashReport_{target_iso}.pdf
    2. Look for any PDF whose text contains 'Day of M/D/YYYY' matching the date
    3. Fall back to most recently modified PDF in the folder
    """
    named = os.path.join(FLASH_DIR, f"FlashReport_{target_iso}.pdf")
    if os.path.exists(named):
        return named

    # Scan all PDFs for matching date header
    dt = datetime.strptime(target_iso, "%Y-%m-%d")
    target_str = f"{dt.month}/{dt.day}/{dt.year}"
    for pdf_path in sorted(glob.glob(os.path.join(FLASH_DIR, "*.pdf"))):
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = pdf.pages[0].extract_text() or ""
            if f"Day of {target_str}" in text:
                return pdf_path
        except Exception:
            pass

    # Fall back to newest PDF
    pdfs = sorted(glob.glob(os.path.join(FLASH_DIR, "*.pdf")), key=os.path.getmtime, reverse=True)
    if pdfs:
        print(f"  [warn] No PDF found for {target_iso}, using most recent: {os.path.basename(pdfs[0])}")
        return pdfs[0]

    return None

# ── PDF parser ────────────────────────────────────────────────────────────────
def extract_venue_order(text):
    day_of_text = text
    m = re.search(r"Week To Date", text)
    if m:
        day_of_text = text[:m.start()]
    hits = []
    for pattern, vid in R365_NAME_TO_ID.items():
        m2 = re.search(re.escape(pattern), day_of_text, re.IGNORECASE)
        if m2:
            hits.append((m2.start(), vid))
    seen, ordered = set(), []
    for pos, vid in sorted(hits):
        if vid not in seen:
            ordered.append(vid); seen.add(vid)
    return ordered

def parse_flash_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        page  = pdf.pages[0]
        text  = page.extract_text() or ""
        tables = page.extract_tables()

    m = re.search(r"Day of\s+(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not m:
        raise ValueError("Could not find 'Day of' date in PDF")
    dt       = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    iso_date = dt.strftime("%Y-%m-%d")

    if not tables:
        raise ValueError("No tables found in PDF")

    day_of_table = tables[0]
    data_rows    = day_of_table[2:-1]
    venue_order  = extract_venue_order(text)

    if len(venue_order) != len(data_rows):
        print(f"  [warn] text found {len(venue_order)} venues, table has {len(data_rows)} rows — zipping to shorter")

    venues = []
    for vid, row in zip(venue_order, data_rows):
        meta = R365_VENUE_META.get(vid, {"name": vid, "full": vid})
        def get(col, r=row):
            return r[col] if col < len(r) else None
        venues.append({
            "id":            vid,
            "name":          meta["name"],
            "full":          meta["full"],
            "net_sales":     parse_dollar(get(COL_SALES)),
            "r365_forecast": parse_dollar(get(COL_FORECAST)),
            "check_avg":     parse_dollar(get(COL_CHECK_AVG)),
            "guests":        parse_int(get(COL_GUESTS)),
            "comps":         parse_dollar(get(COL_COMPS)),
            "data_source":   "r365",
        })

    return iso_date, venues

# ── Merge into JSON ───────────────────────────────────────────────────────────
def merge_into_json(iso_date, r365_venues, budgets):
    json_path  = os.path.join(DATA_DIR, f"{iso_date}.json")
    month_name = datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B").lower()

    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
    else:
        data = {
            "iso_date":   iso_date,
            "report_date": datetime.strptime(iso_date, "%Y-%m-%d").strftime("%B %-d, %Y"),
            "venues": [],
        }

    existing   = {v["id"]: v for v in data.get("venues", [])}
    r365_present = {rv["id"] for rv in r365_venues}

    # Clear stale R365 fields for venues absent from today's report
    for vid in R365_VENUE_META:
        if vid not in r365_present and vid in existing:
            existing[vid].update({
                "net_sales": None, "r365_forecast": None,
                "check_avg": None, "guests": None, "comps": None,
                "data_source": "r365",
            })

    # Update present venues with R365 data
    for rv in r365_venues:
        vid = rv["id"]
        mb  = (budgets.get(vid) or {}).get(month_name)
        if vid in existing:
            existing[vid].update({**rv, "monthly_budget": mb, "missing": False})
        else:
            existing[vid] = {**rv, "monthly_budget": mb, "missing": False}

    # Rebuild ordered venue list
    ordered = []
    for vid in VENUE_ORDER:
        if vid in existing:
            ordered.append(existing[vid])
    for vid, v in existing.items():
        if vid not in VENUE_ORDER:
            ordered.append(v)

    data["venues"]   = ordered
    data["iso_date"] = iso_date

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)

    return json_path

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    target_iso = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")
    print(f"Parsing Flash Report for {target_iso}")

    print("Loading budgets...")
    budgets = load_budgets()
    print(f"  Loaded budgets for: {', '.join(budgets.keys())}")

    pdf_path = find_pdf(target_iso)
    if not pdf_path:
        print(f"ERROR: No Flash Report PDF found in {FLASH_DIR}")
        sys.exit(1)

    print(f"Parsing PDF: {os.path.basename(pdf_path)}")
    iso_date, venues = parse_flash_pdf(pdf_path)
    print(f"  Report date: {iso_date}")
    print(f"  Venues found: {', '.join(v['id'] for v in venues)}")
    for v in venues:
        print(f"    {v['id']:6} | net_sales={v['net_sales']} | forecast={v['r365_forecast']} | guests={v['guests']}")

    json_path = merge_into_json(iso_date, venues, budgets)
    total = sum(v["net_sales"] or 0 for v in venues)
    print(f"\nSaved → {os.path.basename(json_path)}  (total sales: ${total:,.0f})")

if __name__ == "__main__":
    main()
