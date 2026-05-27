#!/usr/bin/env python3
"""
PUB 151 Sea Distance Calculator
Data: US Navy "Distances Between Ports" (Pub. 151) — authoritative maritime distances.

Algorithm (correct PUB-151 method):
  1. Build a graph of the 25 junction points only (junction ↔ junction edges).
  2. Each port connects to nearby junctions (port.junctions dict).
  3. Distance A→B = min over all junction pairs (j_a, j_b) of:
       A.junctions[j_a]  +  junction_path(j_a→j_b)  +  B.junctions[j_b]
     Also check A.destinations[B] for a direct entry.

Usage:
    python3 pub151_distance.py "Shanghai, China" "Rotterdam, Netherlands"
    python3 pub151_distance.py excel
"""

import json, heapq, re, sys, os, time
from collections import defaultdict
import pandas as pd

# ── Load data ─────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
_P151_PATH = os.path.join(_DIR, "PUB151_distances.json")

if not os.path.exists(_P151_PATH):
    raise FileNotFoundError(
        f"Missing {_P151_PATH}\n"
        "Run: curl -s https://raw.githubusercontent.com/kaklin/sea-routes/master/"
        "PUB151_distances.json -o PUB151_distances.json"
    )

with open(_P151_PATH) as f:
    _PUB151: dict = json.load(f)

# ── Junction point canonical names ────────────────────────────────────────────
# These are the 25 waypoints PUB 151 routes traffic through.
_JUNCTION_NAMES = {
    "Bishop Rock, England",
    "Cape Leeuwin, Australia",
    "Cape Of Good Hope, South Africa",
    "Fastnet Rock, Ireland",
    "Grand Banks South",
    "Honshu, Japan",
    "Ile D'Ouessant, France",
    "Inishtrahull, Ireland",
    "Montreal, Canada",
    "Nord-Ostsee-Kanal (East Entrance), Germany",
    "Panama, Panama",
    "Pentland Firth, Scotland",
    "Port Said, Egypt",
    "Punta Arenas, Chile",
    "Selat Lombok, Indonesia",
    "Selat Sunda, Indonesia",
    "Selat Wetar, Indonesia",
    "Singapore",
    "Skagens Odde, Denmark",
    "Strait Of Gibraltar",
    "Straits Of Florida",
    "Torres Strait, Australia",
    "Tsugaru-Kaikyo, Japan",
    "Wilson Promontory, Australia",
    "Yucatan Channel",
}

# Strip route-variant hints like "(via Suez Canal)" from junction references
_HINT_RE = re.compile(r'\s*\([^)]*\)\s*')

def _strip_hint(s: str) -> str:
    return _HINT_RE.sub('', s).strip()

# Normalise to lower-case for fuzzy matching
def _norm(s: str) -> str:
    return _strip_hint(s).lower()

# Canonical lookup: normalised → key in _PUB151
_CANON: dict[str, str] = {}
for _k in _PUB151:
    _CANON.setdefault(_norm(_k), _k)

# Map junction display-name variants → canonical PUB151 key
_JUNC_CANON: dict[str, str] = {}
for _jn in _JUNCTION_NAMES:
    _jn_norm = _norm(_jn)
    # exact match
    if _jn in _PUB151:
        _JUNC_CANON[_jn_norm] = _jn
    elif _jn_norm in _CANON:
        _JUNC_CANON[_jn_norm] = _CANON[_jn_norm]
    else:
        # partial match
        for _k in _PUB151:
            if _jn_norm in _norm(_k):
                _JUNC_CANON[_jn_norm] = _k
                break

_JUNC_CANON_VALUES = set(_JUNC_CANON.values())

def _to_junc(name: str) -> str | None:
    """Resolve any junction reference string to its canonical PUB151 key."""
    return _JUNC_CANON.get(_norm(name))

# ── Build junction-only graph ─────────────────────────────────────────────────
_JGRAPH: dict[str, dict[str, float]] = defaultdict(dict)

def _jadd(a: str, b: str, d: float):
    if d > 0:
        if b not in _JGRAPH[a] or _JGRAPH[a][b] > d:
            _JGRAPH[a][b] = d
        if a not in _JGRAPH[b] or _JGRAPH[b][a] > d:
            _JGRAPH[b][a] = d

for _jname in _JUNC_CANON_VALUES:
    _jdata = _PUB151.get(_jname, {})
    _jedges = _jdata.get("junctions", {})
    if not isinstance(_jedges, dict):
        continue
    for _nbr, _dist in _jedges.items():
        if not isinstance(_dist, (int, float)):
            continue
        _nbr_canon = _to_junc(_nbr)
        if _nbr_canon:
            _jadd(_jname, _nbr_canon, float(_dist))

# ── Dijkstra on junction-only graph ──────────────────────────────────────────
def _jdijkstra(start: str, end: str) -> float:
    """Return shortest distance between two junction nodes."""
    if start == end:
        return 0.0
    dist = {start: 0.0}
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        if u == end:
            return d
        for v, w in _JGRAPH.get(u, {}).items():
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return float("inf")

# Pre-compute all-pairs shortest paths between junctions (25×25 = 625, fast)
_JALL: dict[tuple[str, str], float] = {}
_jlist = sorted(_JUNC_CANON_VALUES)
for _ja in _jlist:
    for _jb in _jlist:
        if _ja != _jb:
            _JALL[(_ja, _jb)] = _jdijkstra(_ja, _jb)
        else:
            _JALL[(_ja, _jb)] = 0.0

# ── Resolve port → its junction distances ─────────────────────────────────────
def _port_junctions(pub151_key: str) -> dict[str, float]:
    """Return {junction_canonical: distance_nm} for a port."""
    data = _PUB151.get(pub151_key, {})
    result: dict[str, float] = {}
    jraw = data.get("junctions", {})
    if not isinstance(jraw, dict):
        return result
    for jname, dist in jraw.items():
        if not isinstance(dist, (int, float)):
            continue
        jc = _to_junc(jname)
        if jc:
            # keep minimum distance if multiple route variants exist
            if jc not in result or result[jc] > dist:
                result[jc] = float(dist)
    return result

def _port_destinations(pub151_key: str) -> dict[str, float]:
    """Return normalised {dest_name_lower: distance_nm} direct destinations."""
    data = _PUB151.get(pub151_key, {})
    raw = data.get("destinations", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for dest, dist in raw.items():
        if isinstance(dist, (int, float)):
            dn = _norm(dest)
            if dn not in result or result[dn] > dist:
                result[dn] = float(dist)
    return result

# ── Port alias table ───────────────────────────────────────────────────────────
# "our name": ("PUB151 name", coastal_offset_nm)
_ALIASES: dict[str, tuple[str, float]] = {
    # Chinese origins
    "Ningbo, China":       ("Shanghai, China",         125.0),
    "Yantian, China":      ("Hong Kong, China",          20.0),
    "Shekou, China":       ("Hong Kong, China",          15.0),
    "Shenzhen, China":     ("Hong Kong, China",          25.0),
    "Guangzhou, China":    ("Huang-Pu, China",           30.0),
    "Nansha, China":       ("Huang-Pu, China",           40.0),
    "Taicang, China":      ("Shanghai, China",           55.0),
    "Yangzhou, China":     ("Shanghai, China",          100.0),
    "Nanjing, China":      ("Shanghai, China",          170.0),
    "Suzhou, China":       ("Shanghai, China",           60.0),
    "Hangzhou, China":     ("Shanghai, China",          130.0),
    "Yiwu, China":         ("Shanghai, China",          200.0),
    "Xian, China":         ("Shanghai, China",          800.0),
    "Shantou, China":      ("Xiamen, China",            140.0),
    "Zhangjiagang, China": ("Shanghai, China",           90.0),
    # Destinations
    "Felixstowe, United Kingdom": ("Felixstowe, England",  0.0),
    "Felixstowe":                 ("Felixstowe, England",  0.0),
    "Dunkerque, France":          ("Dunkirk, France",      0.0),
    "Dunkirk":                    ("Dunkirk, France",      0.0),
    "Gothenburg, Sweden":         ("Gothenburg, Sweden",   0.0),
    "Antwerp":                    ("Antwerp, Belgium",     0.0),
    "Koper, Slovenia":            ("Koper, Yugoslavia",    0.0),
    "Piraeus, Greece":            ("Piraeus, Greece",      0.0),
    "Constanta, Romania":         ("Constanta, Romania",   0.0),
    "Gdynia, Poland":             ("Gdynia, Poland",       0.0),
    "Szczecin, Poland":           ("Szczecin, Poland",     0.0),
    "Zeebrugge, Belgium":         ("Zeebrugge, Belgium",   0.0),
    "Long Beach":                 ("Long Beach, California, U.S.A.", 0.0),
    "Los Angeles":                ("Los Angeles, California, U.S.A.", 0.0),
    "Vancouver, Canada":          ("Vancouver, British Columbia, Canada", 0.0),
    "Montreal, Canada":           ("Montreal, Canada",     0.0),
    "Santos, Brazil":             ("Santos, Brazil",       0.0),
    "Buenos Aires, Argentina":    ("Buenos Aires, Argentina", 0.0),
    "Callao, Peru":               ("Callao, Peru",         0.0),
    "Durban, South Africa":       ("Durban, South Africa", 0.0),
    "Cape Town, South Africa":    ("Cape Town, South Africa", 0.0),
    "Casablanca, Morocco":        ("Casablanca, Morocco",  0.0),
    "Jeddah, Saudi Arabia":       ("Jeddah, Saudi Arabia", 0.0),
    "Ashdod, Israel":             ("Ashdod, Israel",       0.0),
    "Haifa, Israel":              ("Haifa, Israel",        0.0),
    "Dubai":                      ("Dubai, United Arab Emirates", 0.0),
    "Melbourne, Australia":       ("Melbourne, Australia", 0.0),
    "Sydney, Australia":          ("Sydney, Australia",    0.0),
    "Brisbane, Australia":        ("Brisbane, Australia",  0.0),
    "Fremantle, Australia":       ("Fremantle, Australia", 0.0),
    "Auckland, New Zealand":      ("Auckland, New Zealand", 0.0),
    "Ho Chi Minh":                ("Ho Chi Minh, Vietnam", 0.0),
    "Port Klang, Malaysia":       ("Port Klang, Malaysia", 0.0),
    "Colombo":                    ("Colombo, Sri Lanka",   0.0),
    "Mumbai":                     ("Bombay, India",        0.0),
    "Busan, South Korea":         ("Busan, South Korea",   0.0),
    "Incheon, South Korea":       ("Incheon, South Korea", 0.0),
}

def resolve_port(raw: str) -> tuple[str | None, float]:
    """Return (pub151_canonical_key, offset_nm) or (None, 0)."""
    raw = raw.strip()

    # 1. Direct match
    if raw in _PUB151:
        return raw, 0.0
    n = _norm(raw)
    if n in _CANON:
        return _CANON[n], 0.0

    # 2. Alias table
    if raw in _ALIASES:
        alias, offset = _ALIASES[raw]
        if alias in _PUB151:
            return alias, offset
        an = _norm(alias)
        if an in _CANON:
            return _CANON[an], offset

    # 3. City-name partial match
    city = raw.split(',')[0].strip().lower()
    for k in _PUB151:
        if k.lower().startswith(city + ',') or k.lower() == city:
            return k, 0.0

    return None, 0.0

# ── Main distance function ────────────────────────────────────────────────────
def distance(origin: str, destination: str) -> dict | None:
    """
    Calculate sea distance via PUB 151 junction routing.
    Returns dict(distance_nm, distance_km, route_junctions) or None.
    """
    orig_key, orig_off = resolve_port(origin)
    dest_key, dest_off = resolve_port(destination)

    if orig_key is None or dest_key is None:
        return None
    if orig_key == dest_key:
        total = orig_off + dest_off
        return {"distance_nm": round(total), "distance_km": round(total * 1.852), "route_junctions": []}

    # Check direct destination entry
    best = float("inf")
    best_juctions: list[str] = []

    orig_dests = _port_destinations(orig_key)
    dest_norm = _norm(dest_key)
    if dest_norm in orig_dests:
        best = orig_dests[dest_norm] + orig_off + dest_off
        best_juctions = ["(direct)"]

    # Junction routing
    orig_juncs = _port_junctions(orig_key)
    dest_juncs = _port_junctions(dest_key)

    for j_a, d_a in orig_juncs.items():
        for j_b, d_b in dest_juncs.items():
            jj = _JALL.get((j_a, j_b), float("inf"))
            total = d_a + jj + d_b + orig_off + dest_off
            if total < best:
                best = total
                best_juctions = ([j_a] if j_a != j_b else []) + (
                    [j_b] if j_a != j_b else [j_a]
                )

    if best == float("inf"):
        return None

    return {
        "distance_nm": round(best),
        "distance_km": round(best * 1.852),
        "route_junctions": best_juctions,
    }

# ── CLI ───────────────────────────────────────────────────────────────────────
def search(origin: str, destination: str):
    print(f"\n查询: {origin} → {destination}")
    ok, off = resolve_port(origin)
    dk, doff = resolve_port(destination)
    if ok: print(f"  起点 → {ok}" + (f" (+{off:.0f}nm offset)" if off else ""))
    if dk: print(f"  终点 → {dk}" + (f" (+{doff:.0f}nm offset)" if doff else ""))
    r = distance(origin, destination)
    if r:
        print(f"  海上距离:  {r['distance_nm']:,} 海里  ({r['distance_km']:,} km)")
        if r["route_junctions"] and r["route_junctions"] != ["(direct)"]:
            print(f"  关键节点:  {' → '.join(r['route_junctions'])}")
    else:
        print("  [错误] 无法计算距离")


def process_excel(file_path: str = "运输数据_三维汇总表_全新版.xlsx",
                  sheet: str = "三维汇总表_按订单排序",
                  orig_col: str = "起运港",
                  dest_col: str = "目的港",
                  mode_col: str = "运输方式",
                  sea_modes=("VESSEL", "SEA")):

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}"); return

    df = pd.read_excel(file_path, sheet_name=sheet)
    print(f"读取: {len(df)} 行")
    is_sea = df[mode_col].isin(sea_modes)
    print(f"VESSEL/SEA: {is_sea.sum()} 行\n")

    dist_nm = [None] * len(df)
    dist_km = [None] * len(df)
    remarks = [""] * len(df)
    ok = skipped = 0

    for i, idx in enumerate(df[is_sea].index):
        orig_raw = str(df.at[idx, orig_col]).strip()
        dest_raw = str(df.at[idx, dest_col]).strip()
        label = f"[{i+1}/{is_sea.sum()}] {orig_raw} → {dest_raw}"

        r = distance(orig_raw, dest_raw)
        if r:
            dist_nm[idx] = r["distance_nm"]
            dist_km[idx] = r["distance_km"]
            print(f"{label}  {r['distance_nm']:,} nm")
            ok += 1
        else:
            op, _ = resolve_port(orig_raw)
            dp, _ = resolve_port(dest_raw)
            who = []
            if op is None: who.append(f"起运港'{orig_raw}'")
            if dp is None: who.append(f"目的港'{dest_raw}'")
            remarks[idx] = "未知: " + ", ".join(who) if who else "路线不通"
            print(f"{label}  ⚠ {remarks[idx]}")
            skipped += 1

    df["海运距离(海里)_PUB151"] = dist_nm
    df["海运距离(km)_PUB151"]  = dist_km
    df["备注_PUB151"]           = remarks

    out = file_path.replace(".xlsx", "_PUB151.xlsx")
    df.to_excel(out, index=False)
    print(f"\n完成: 成功 {ok} | 跳过 {skipped}  →  {out}")


if __name__ == "__main__":
    os.chdir(_DIR)
    if len(sys.argv) == 3:
        search(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "excel":
        process_excel()
    else:
        print("=" * 55)
        print("  PUB 151 航运距离查询  (美国海军权威数据)")
        print("  输入 'excel' 处理Excel，'quit' 退出")
        print("=" * 55)
        while True:
            orig = input("\n起运港: ").strip()
            if not orig or orig.lower() == "quit": break
            if orig.lower() == "excel":
                process_excel(); continue
            dest = input("目的港: ").strip()
            if not dest or dest.lower() == "quit": break
            search(orig, dest)
