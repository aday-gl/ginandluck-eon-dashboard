#!/usr/bin/env python3
"""
rebuild_dashboard.py — minimal data-swap rebuilder.

Reads the existing EON_Dashboard.html as a template (it carries the latest
CSS/JS, exec-summary panels, Weekly Brief, Notes pips, fin-grid rows, and
ASCII-safe encoding pass) and only replaces the three injected data blocks:
  - const HISTORY    = {...}
  - const CHART_DATA = {...}
  - const AVAIL      = [...]

The HISTORY data is loaded fresh from eon_data/*.json. CHART_DATA and AVAIL
are derived from the HISTORY in the same shape the prior rebuild produced.

If you need full template regeneration, run generate_eon_dashboard.py first,
then this script will adopt the new template on the next run.
"""

import json, os, glob, re, datetime
from typing import Any

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(WORKSPACE, "eon_data")
OUTPUT    = os.path.join(WORKSPACE, "EON_Dashboard.html")
INDEX     = os.path.join(WORKSPACE, "index.html")

VENUE_META = [
    {"id": "ccatl", "name": "CC Atlanta",       "full": "Close Company Atlanta",     "color": "#E07B54"},
    {"id": "ccnsh", "name": "CC Nashville",     "full": "Close Company Nashville",   "color": "#6B8CBA"},
    {"id": "mg",    "name": "Municipal Grand",  "full": "Municipal Grand F&B",       "color": "#7CB87A"},
    {"id": "la",    "name": "D&C LA",           "full": "Death & Co Los Angeles",    "color": "#C47DC0"},
    {"id": "dvr",   "name": "D&C Denver",       "full": "Death & Co Denver",         "color": "#E8C45A"},
    {"id": "ev",    "name": "D&C East Village", "full": "Death & Co East Village",   "color": "#E87A7A"},
    {"id": "dc",    "name": "D&C DC",           "full": "Death & Co Washington DC",  "color": "#5AA8C4"},
    {"id": "sea",   "name": "D&C Seattle",     "full": "Death & Co Seattle",        "color": "#9BB7A0"},
]


_META_BY_ID = {m["id"]: m for m in VENUE_META}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def normalize_venue(v: dict) -> dict:
    """Map slim EON records (net_sales/guests/check_avg/narrative) onto the rich
    schema the dashboard template renders (full_name/guest_count/comp_pct/
    notes_summary/highlights/...). Idempotent: already-rich records pass through.
    Derives what it can from the slim fields; leaves genuinely-absent figures null
    (the template shows '—' for those)."""
    meta = _META_BY_ID.get(v.get("id"), {})
    note = v.get("notes_summary") or v.get("narrative") or ""

    # --- display name & color ---
    v["full_name"] = v.get("full_name") or meta.get("full") or v.get("name")
    v["color"]     = v.get("color") or meta.get("color") or "#555"

    # --- guests / check avg (slim uses guests/check_avg) ---
    if v.get("guest_count") in (None, "") and v.get("guests") is not None:
        v["guest_count"] = v.get("guests")
    if v.get("guest_check_avg") in (None, "") and v.get("check_avg") is not None:
        v["guest_check_avg"] = v.get("check_avg")

    # --- target: a 0 / negative target means "no target set" (e.g. new venue) ---
    if _num(v.get("target")) is not None and _num(v.get("target")) <= 0:
        v["target"] = None

    # --- comp % (compute from comps vs net if not provided) ---
    if v.get("comp_pct") in (None, ""):
        comps, net = _num(v.get("comps")), _num(v.get("net_sales"))
        if comps is not None and net:
            v["comp_pct"] = round(comps / net * 100, 1)

    # --- food sales: recover from narrative prose ("Food $677") if unstructured ---
    if v.get("food_sales") in (None, "") and note:
        m = re.search(r"Food\s*\$([\d,]+(?:\.\d+)?)", note)
        if m:
            v["food_sales"] = float(m.group(1).replace(",", ""))

    # --- MOD: pull from narrative tail ("MOD: JK/MKZ.") if unstructured ---
    if not v.get("mod") and note:
        m = re.search(r"MOD:\s*([^.]+)", note)
        if m:
            v["mod"] = m.group(1).strip().rstrip(" .")

    # --- qualitative summary ---
    if not v.get("notes_summary"):
        v["notes_summary"] = v.get("narrative") or None

    # --- containers the template iterates ---
    for k in ("eightysixed", "maintenance_flags", "sub_venues"):
        if not isinstance(v.get(k), list):
            v[k] = []

    # --- highlights drive the Exec Summary; synthesize a target flag if absent ---
    if not v.get("highlights"):
        hls = []
        net, tgt = _num(v.get("net_sales")), _num(v.get("target"))
        if net is not None and tgt:
            pct = (net / tgt - 1) * 100
            txt = f"{'Beat' if pct >= 0 else 'Missed'} target {pct:+.1f}% (${net:,.0f} vs ${tgt:,.0f})"
            hls.append({"type": "win" if pct >= 0 else "flag", "text": txt})
        v["highlights"] = hls

    return v


def load_history() -> dict:
    history = {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        iso = os.path.basename(path).replace(".json", "")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            data["iso_date"] = iso
            data.setdefault("date", iso)
            if "day_of_week" not in data:
                try:
                    data["day_of_week"] = datetime.date.fromisoformat(iso).strftime("%A")
                except Exception:
                    pass
            data["venues"] = [normalize_venue(v) for v in data.get("venues", [])]
            history[iso] = data
        except Exception as e:
            print(f"  ! skipped {iso}: {e}")
    return history


def derive_chart_data(history: dict) -> dict:
    dates = sorted(history.keys())
    isos = list(dates)
    labels = []
    for iso in isos:
        try:
            d = datetime.date.fromisoformat(iso)
            labels.append(f"{d.strftime('%a')} {d.month}/{d.day}")
        except Exception:
            labels.append(iso)

    c_actual, c_target = [], []
    venue_buckets = {v["id"]: {"actual": [], "target": []} for v in VENUE_META}

    for iso in isos:
        day = history[iso]
        day_a, day_t = 0.0, 0.0
        per_venue = {v["id"]: {"actual": None, "target": None} for v in VENUE_META}
        for vrec in day.get("venues", []):
            vid = vrec.get("id")
            if vid not in per_venue:
                continue
            if vrec.get("missing"):
                continue
            ns = vrec.get("net_sales")
            tg = vrec.get("target")
            if ns is not None:
                per_venue[vid]["actual"] = round(float(ns), 2)
                day_a += float(ns)
            if tg is not None:
                per_venue[vid]["target"] = round(float(tg), 2)
                day_t += float(tg)
        c_actual.append(round(day_a, 2))
        c_target.append(round(day_t, 2))
        for vid in venue_buckets:
            venue_buckets[vid]["actual"].append(per_venue[vid]["actual"])
            venue_buckets[vid]["target"].append(per_venue[vid]["target"])

    venues = []
    for meta in VENUE_META:
        b = venue_buckets[meta["id"]]
        venues.append({
            "id":     meta["id"],
            "name":   meta["name"],
            "full":   meta["full"],
            "color":  meta["color"],
            "actual": b["actual"],
            "target": b["target"],
        })

    return {
        "dates":    labels,
        "isos":     isos,
        "c_actual": c_actual,
        "c_target": c_target,
        "venues":   venues,
    }


def find_balanced(text: str, start_pos: int) -> int:
    """Given start_pos at the opening { or [, return index of matching close."""
    opener = text[start_pos]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    i = start_pos
    while i < len(text):
        ch = text[i]
        if esc:
            esc = False
        elif ch == "\\" and in_str:
            esc = True
        elif ch == '"' and not esc:
            in_str = not in_str
        elif not in_str:
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    raise ValueError("Unbalanced braces")


def replace_const_block(html: str, name: str, new_value_json: str) -> str:
    """Replace `const NAME = {...}` or `const NAME = [...]` with new JSON value."""
    pat = re.compile(r"(const\s+" + re.escape(name) + r"\s*=\s*)([\{\[])")
    m = pat.search(html)
    if not m:
        raise ValueError(f"Could not find `const {name} = ` in template")
    prefix_end = m.end(1)
    opener_pos = m.start(2)
    closer_pos = find_balanced(html, opener_pos)
    return html[:prefix_end] + new_value_json + html[closer_pos + 1:]


GREEN = "#5BC88A"
RED   = "#E87A7A"


def _day_totals(day: dict):
    """Sum net_sales and target across non-missing venues for one day."""
    net = tgt = 0.0
    have = False
    for v in day.get("venues", []):
        if v.get("missing"):
            continue
        ns, tg = v.get("net_sales"), v.get("target")
        if ns is not None:
            net += float(ns); have = True
        if tg is not None:
            tgt += float(tg)
    return (net, tgt, have)


# ---------------------------------------------------------------------------
# Password gate (client-side). SHA-256 of the passphrase; plaintext is never in
# the page. sessionStorage remembers an unlock for the browser tab session, so
# index.html -> EON_Dashboard.html only asks once. Deters casual viewers only —
# the data is still in the page source for anyone determined.
# ---------------------------------------------------------------------------
GATE_HASH = "0699d322bcc2664ad140b28237c841719552eb4801019391dd8a439ca1e03a43"
GATE_MARK = "<!-- gl-gate -->"
GATE_HTML = GATE_MARK + r'''
<style id="gl-gate-css">
body:not(.gl-open)>*:not(#gl-gate){display:none!important}
#gl-gate{position:fixed;inset:0;z-index:99999;background:#0F1117;display:flex;align-items:center;justify-content:center;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
body.gl-open #gl-gate{display:none}
#gl-gate form{background:#1A1D27;border:1px solid #2A2D3A;border-radius:14px;padding:32px;width:320px;text-align:center}
#gl-gate h2{color:#fff;font-size:16px;margin:0 0 6px}
#gl-gate p{color:#777;font-size:12px;margin:0 0 18px}
#gl-gate input{width:100%;box-sizing:border-box;padding:11px 12px;border-radius:8px;border:1px solid #2A2D3A;background:#0F1117;color:#fff;font-size:15px;outline:none;margin-bottom:12px}
#gl-gate input:focus{border-color:#5BC88A}
#gl-gate button{width:100%;padding:11px;border:0;border-radius:8px;background:#5BC88A;color:#0F1117;font-weight:700;font-size:14px;cursor:pointer}
#gl-gate .err{color:#E87A7A;font-size:12px;margin-top:10px;min-height:14px}
</style>
<div id="gl-gate"><form id="gl-gate-form" autocomplete="off">
<h2>G&amp;L EON Reports</h2><p>Enter the password to continue</p>
<input id="gl-gate-pw" type="password" placeholder="Password" autofocus>
<button type="submit">Unlock</button><div class="err" id="gl-gate-err"></div>
</form></div>
<script>
(function(){
var H="__HASH__",K="gl_eon_unlocked";
function sha256(s){var K=[1116352408,1899447441,3049323471,3921009573,961987163,1508970993,2453635748,2870763221,3624381080,310598401,607225278,1426881987,1925078388,2162078206,2614888103,3248222580,3835390401,4022224774,264347078,604807628,770255983,1249150122,1555081692,1996064986,2554220882,2821834349,2952996808,3210313671,3336571891,3584528711,113926993,338241895,666307205,773529912,1294757372,1396182291,1695183700,1986661051,2177026350,2456956037,2730485921,2820302411,3259730800,3345764771,3516065817,3600352804,4094571909,275423344,430227734,506948616,659060556,883997877,958139571,1322822218,1537002063,1747873779,1955562222,2024104815,2227730452,2361852424,2428436474,2756734187,3204031479,3329325298];var h=[1779033703,3144134277,1013904242,2773480762,1359893119,2600822924,528734635,1541459225];var b=unescape(encodeURIComponent(s)),l=b.length*8,w=[],i;for(i=0;i<b.length;i++)w[i>>2]|=b.charCodeAt(i)<<(24-(i%4)*8);w[l>>5]|=0x80<<(24-l%32);w[((l+64>>9)<<4)+15]=l;var W=new Array(64),r=function(x,n){return(x>>>n)|(x<<(32-n))};for(var j=0;j<w.length;j+=16){var a=h[0],c=h[1],d=h[2],e=h[3],f=h[4],g=h[5],p=h[6],q=h[7];for(i=0;i<64;i++){W[i]=i<16?(w[j+i]|0):((r(W[i-2],17)^r(W[i-2],19)^(W[i-2]>>>10))+W[i-7]+(r(W[i-15],7)^r(W[i-15],18)^(W[i-15]>>>3))+W[i-16])|0;var t1=(q+(r(f,6)^r(f,11)^r(f,25))+((f&g)^(~f&p))+K[i]+W[i])|0,t2=((r(a,2)^r(a,13)^r(a,22))+((a&c)^(a&d)^(c&d)))|0;q=p;p=g;g=f;f=(e+t1)|0;e=d;d=c;c=a;a=(t1+t2)|0}h[0]=(h[0]+a)|0;h[1]=(h[1]+c)|0;h[2]=(h[2]+d)|0;h[3]=(h[3]+e)|0;h[4]=(h[4]+f)|0;h[5]=(h[5]+g)|0;h[6]=(h[6]+p)|0;h[7]=(h[7]+q)|0}var o="";for(i=0;i<8;i++)o+=("00000000"+(h[i]>>>0).toString(16)).slice(-8);return o}
function open(){document.body.classList.add("gl-open");document.getElementById("gl-gate-err").textContent="";}
try{if(sessionStorage.getItem(K)===H){open();}}catch(e){}
document.getElementById("gl-gate-form").addEventListener("submit",function(ev){ev.preventDefault();var v=document.getElementById("gl-gate-pw").value;if(sha256(v)===H){try{sessionStorage.setItem(K,H);}catch(e){}open();}else{document.getElementById("gl-gate-err").textContent="Incorrect password";document.getElementById("gl-gate-pw").select();}});
})();
</script>
'''.replace("__HASH__", GATE_HASH)


def inject_gate(html: str) -> str:
    """Insert the password gate right after <body>. Idempotent: an existing
    gate block (any version) is replaced so the hash can be rotated by
    editing GATE_HASH and re-running."""
    if GATE_MARK in html:
        start = html.index(GATE_MARK)
        end = html.index("</script>", start) + len("</script>")
        # swallow the trailing newline we add after the block
        if html[end:end+1] == "\n":
            end += 1
        html = html[:start] + html[end:]
    m = re.search(r"<body[^>]*>\n?", html)
    if not m:
        raise ValueError("No <body> tag found for gate injection")
    return html[:m.end()] + GATE_HTML + html[m.end():]


def build_index(history: dict) -> str:
    """Regenerate index.html landing page from the same HISTORY data so the
    front page can never drift from the dashboard again."""
    isos = sorted(history.keys())
    # latest day that actually has data
    latest = None
    for iso in reversed(isos):
        net, tgt, have = _day_totals(history[iso])
        if have:
            latest = (iso, net, tgt)
            break
    if latest is None:
        latest = (isos[-1] if isos else "n/a", 0.0, 0.0)

    liso, lnet, ltgt = latest
    try:
        ld = datetime.date.fromisoformat(liso)
        hero_date = ld.strftime("%A, %B %-d, %Y")
    except Exception:
        hero_date = liso
    lvar = lnet - ltgt
    lpct = (lvar / ltgt * 100) if ltgt else 0.0
    hero_color = GREEN if lvar >= 0 else RED
    sign = "+" if lvar >= 0 else "-"
    hero_var = f'{sign}${abs(lvar):,.0f} ({sign}{abs(lpct):.1f}%) vs target'

    # recent reports digest — last 10 days with data, newest first
    rows = []
    for iso in reversed(isos):
        net, tgt, have = _day_totals(history[iso])
        if not have:
            continue
        try:
            d = datetime.date.fromisoformat(iso)
            short = f"{d.strftime('%a')} {d.month}/{d.day}"
            dow = d.strftime("%A")
        except Exception:
            short, dow = iso, ""
        var = net - tgt
        pct = (var / tgt * 100) if tgt else 0.0
        col = GREEN if var >= 0 else RED
        psign = "+" if var >= 0 else "-"
        rows.append(f'''        <div style="display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid #1E2030">
          <div style="display:flex;align-items:center;gap:12px">
            <div>
              <div style="font-size:13px;font-weight:600;color:#E0E0E0">{short} <span style="color:#555;font-weight:400;font-size:12px">{dow}</span></div>
            </div>
          </div>
          <div style="text-align:right">
            <div style="font-size:14px;font-weight:700;color:#fff">${net:,.0f}</div>
            <div style="font-size:11px;color:#555">tgt ${tgt:,.0f} &nbsp;<span style="color:{col};font-weight:700">{psign}{abs(pct):.1f}%</span></div>
          </div>
        </div>''')
        if len(rows) >= 10:
            break
    digest = "\n".join(rows)
    updated = datetime.datetime.now().strftime("%B %-d, %Y at %-I:%M %p")

    return f'''<!DOCTYPE html>
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
    <div class="hero-date">{hero_date}</div>
    <div class="hero-sales">${lnet:,.0f}</div>
    <div class="hero-var" style="color:{hero_color}">{hero_var}</div>
    <a class="cta" href="EON_Dashboard.html">Open Full Dashboard &rarr;</a>
  </div>

  <div class="digest">
    <div class="digest-title">Recent Reports</div>
{digest}
  </div>

  <div class="footer">Updated {updated} &nbsp;&middot;&nbsp; Open EON_Dashboard.html for full navigation, charts &amp; venue breakdown</div>
</div>
</body>
</html>'''


def main():
    print(f"[rebuild] workspace: {WORKSPACE}")
    history = load_history()
    print(f"[rebuild] loaded {len(history)} day records")

    if not os.path.exists(OUTPUT):
        raise SystemExit(f"Template missing: {OUTPUT} — run generate_eon_dashboard.py first")

    with open(OUTPUT, "r", encoding="utf-8") as f:
        html = f.read()

    avail_iso = sorted(history.keys())
    chart_data = derive_chart_data(history)

    history_json = json.dumps(history, separators=(", ", ": "))
    chart_json   = json.dumps(chart_data, separators=(", ", ": "))
    avail_json   = json.dumps(avail_iso, separators=(", ", ": "))

    html = replace_const_block(html, "HISTORY",    history_json)
    html = replace_const_block(html, "CHART_DATA", chart_json)
    html = replace_const_block(html, "AVAIL",      avail_json)
    html = inject_gate(html)

    # ASCII-safe encoding pass — preserve smart punctuation already escaped
    html.encode("utf-8")  # validate

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[rebuild] wrote {OUTPUT} ({os.path.getsize(OUTPUT):,} bytes)")

    # regenerate the landing page from the same data (no more May-13 freeze)
    index_html = inject_gate(build_index(history))
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"[rebuild] wrote {INDEX} ({os.path.getsize(INDEX):,} bytes)")

    last = avail_iso[-1] if avail_iso else "n/a"
    print(f"[rebuild] latest date: {last}")
    print(f"[rebuild] total dates: {len(avail_iso)}")


if __name__ == "__main__":
    main()
