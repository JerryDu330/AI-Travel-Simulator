#!/usr/bin/env python3
"""
读取豆包生成的路线 JSON（travel_mode + railway_station），
用高德 API 填入所有段里程，输出带 legs 的完整 JSON。

输入格式（每条）:
  {"origin":"安吉县","destination":"贵溪市","count":2,
   "has_origin_station":"有","has_dest_station":"无",
   "travel_mode":"网约车→高铁→短途巴士→网约车",
   "railway_station":"安吉→鹰潭北"}

输出格式（每条）:
  {"origin":"...","destination":"...","count":N,
   "legs":[{"mode":"网约车","distance_km":30}, ...],
   "total_km":620}

规则:
  网约车   → 固定 30 km
  高铁     → Transit API（站坐标 → 站坐标），提取 railway.distance
  短途巴士 → Driving API（出发城市↔高铁站 / 高铁站↔目的城市）

用法:
  python fill_amap.py --input ai_routes.json --output filled.json
  python fill_amap.py --test 安吉县 贵溪市
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ── 环境变量 ──────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

AMAP_GEO_URL     = "https://restapi.amap.com/v3/geocode/geo"
AMAP_TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
GEO_CACHE_FILE   = Path("amap_geocache.json")

_geo_cache: dict[str, tuple[float, float] | None] = {}

TAXI_KM = 30

# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict) -> dict | None:
    full = url + "?" + urllib.parse.urlencode(params, encoding="utf-8")
    req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [HTTP] {e}", file=sys.stderr)
        return None

# ── 地理编码（磁盘缓存）──────────────────────────────────────────────────────

def _load_geo_cache() -> None:
    if GEO_CACHE_FILE.exists():
        raw = json.loads(GEO_CACHE_FILE.read_text("utf-8"))
        _geo_cache.update({k: tuple(v) if v else None for k, v in raw.items()})

def _save_geo_cache() -> None:
    GEO_CACHE_FILE.write_text(
        json.dumps({k: list(v) if v else None for k, v in _geo_cache.items()},
                   ensure_ascii=False, indent=2), "utf-8")

def geocode(name: str, key: str) -> tuple[float, float] | None:
    if name in _geo_cache:
        return _geo_cache[name]
    data = _get(AMAP_GEO_URL, {"address": name, "key": key, "output": "JSON"})
    result = None
    if data and data.get("status") == "1" and data.get("geocodes"):
        lng, lat = data["geocodes"][0]["location"].split(",")
        result = (float(lng), float(lat))
    _geo_cache[name] = result
    _save_geo_cache()
    return result

def loc_str(loc: tuple) -> str:
    return f"{loc[0]},{loc[1]}"

# ── 格式解析 ──────────────────────────────────────────────────────────────────

def parse_modes(travel_mode: str) -> list[str]:
    """'网约车→高铁→网约车' → ['网约车', '高铁', '网约车']"""
    return [m.strip() for m in travel_mode.replace("→", "→").split("→")]

def parse_stations(railway_station: str) -> tuple[str, str]:
    """从各种格式中提取出发站和到达站名（不含'站'字，供 geocode 追加）。"""
    s = railway_station.strip()
    if not s or s in ("无", "途经中转高铁站"):
        return "", ""

    # "出发站：安吉站，目的地站：合肥南站" / "出发高铁站:宝应站,目的地高铁站:扬州东站" 格式
    m = re.search(r'出发[^：:，,]*[：:]\s*(\S+?)[，,]\s*目的地[^：:，,]*[：:]\s*(\S+)', s)
    if m:
        dep, arr = m.group(1).strip(), m.group(2).strip()
    else:
        parts = re.split(r"[→\-\—\–、,，]", s)
        dep = parts[0].strip() if len(parts) >= 1 else ""
        arr = parts[1].strip() if len(parts) >= 2 else ""

    # 去掉末尾的"站"，避免 geocode 追加后变成"XX站站"
    dep = dep.removesuffix("站")
    arr = arr.removesuffix("站")
    return dep, arr

# ── Transit API → 铁路里程 ────────────────────────────────────────────────────

def query_rail_km(o_loc: tuple, d_loc: tuple,
                  o_city: str, d_city: str, key: str) -> int | None:
    data = _get(AMAP_TRANSIT_URL, {
        "origin":      loc_str(o_loc),
        "destination": loc_str(d_loc),
        "city":        o_city,
        "cityd":       d_city,
        "key":         key,
        "strategy":    0,
        "nightflag":   0,
        "date":        "2026-05-20",
        "time":        "08:00",
    })
    if not data or data.get("status") != "1":
        return None
    transits = data.get("route", {}).get("transits", [])
    for t in transits:
        rail_m = 0
        for seg in t.get("segments", []):
            rw = seg.get("railway", {})
            if rw.get("name"):
                try:
                    rail_m += int(float(rw.get("distance", 0) or 0))
                except (ValueError, TypeError):
                    pass
        if rail_m > 0:
            return round(rail_m / 1000)
    return None

# ── Driving API → 公路里程 ───────────────────────────────────────────────────

def query_driving_km(o_loc: tuple, d_loc: tuple, key: str) -> int | None:
    data = _get(AMAP_DRIVING_URL, {
        "origin":      loc_str(o_loc),
        "destination": loc_str(d_loc),
        "key":         key,
        "strategy":    0,
        "extensions":  "base",
    })
    if not data or data.get("status") != "1":
        return None
    paths = data.get("route", {}).get("paths", [])
    if not paths:
        return None
    try:
        return round(int(paths[0].get("distance", 0)) / 1000)
    except (ValueError, TypeError):
        return None

# ── 核心填充 ──────────────────────────────────────────────────────────────────

def fill_record(rec: dict, key: str) -> dict:
    origin  = rec["origin"]
    dest    = rec["destination"]
    count   = rec.get("count", 1)
    modes   = parse_modes(rec.get("travel_mode", "网约车"))
    dep_st, arr_st = parse_stations(rec.get("railway_station", "无"))

    legs: list[dict] = []
    log_parts: list[str] = []

    has_hsr = "高铁" in modes
    hsr_idx = modes.index("高铁") if has_hsr else -1

    # 只有在需要时才 geocode
    o_loc = d_loc = None
    dep_loc = arr_loc = None

    for idx, mode in enumerate(modes):

        if mode == "网约车":
            legs.append({"mode": "网约车", "distance_km": TAXI_KM})
            log_parts.append(f"网约车({TAXI_KM})")

        elif mode == "高铁":
            # 优先用站点坐标查 Transit，回退用城市坐标
            km = None
            if dep_st and arr_st:
                if dep_loc is None:
                    dep_loc = geocode(dep_st + "站", key)
                if arr_loc is None:
                    arr_loc = geocode(arr_st + "站", key)
                if dep_loc and arr_loc:
                    km = query_rail_km(dep_loc, arr_loc, origin, dest, key)
            if km is None:
                if o_loc is None:
                    o_loc = geocode(origin, key)
                if d_loc is None:
                    d_loc = geocode(dest, key)
                if o_loc and d_loc:
                    km = query_rail_km(o_loc, d_loc, origin, dest, key)
            if km is None:
                # Transit API 无结果，用驾车距离兜底
                if o_loc is None:
                    o_loc = geocode(origin, key)
                if d_loc is None:
                    d_loc = geocode(dest, key)
                if o_loc and d_loc:
                    km = query_driving_km(o_loc, d_loc, key)
            legs.append({"mode": "高铁", "distance_km": km or 0})
            log_parts.append(f"高铁({km or '?'})")

        elif mode == "短途巴士":
            km = None
            if has_hsr and idx < hsr_idx:
                # 出发城市 → 出发高铁站
                if o_loc is None:
                    o_loc = geocode(origin, key)
                if dep_st:
                    if dep_loc is None:
                        dep_loc = geocode(dep_st + "站", key)
                    end_loc = dep_loc
                else:
                    end_loc = d_loc or geocode(dest, key)
                if o_loc and end_loc:
                    km = query_driving_km(o_loc, end_loc, key)
            elif has_hsr and idx > hsr_idx:
                # 到达高铁站 → 目的城市
                if d_loc is None:
                    d_loc = geocode(dest, key)
                if arr_st:
                    if arr_loc is None:
                        arr_loc = geocode(arr_st + "站", key)
                    start_loc = arr_loc
                else:
                    start_loc = o_loc or geocode(origin, key)
                if start_loc and d_loc:
                    km = query_driving_km(start_loc, d_loc, key)
            else:
                # 无高铁，直接城市间驾车
                if o_loc is None:
                    o_loc = geocode(origin, key)
                if d_loc is None:
                    d_loc = geocode(dest, key)
                if o_loc and d_loc:
                    km = query_driving_km(o_loc, d_loc, key)
            legs.append({"mode": "短途巴士", "distance_km": km or 0})
            log_parts.append(f"短途巴士({km or '?'})")

        else:
            # 未知交通方式，原样保留
            legs.append({"mode": mode, "distance_km": 0})
            log_parts.append(mode)

    total_km = sum(l["distance_km"] for l in legs)
    print("  " + " → ".join(log_parts) + f"  合计{total_km}km")

    return {
        "origin":      origin,
        "destination": dest,
        "count":       count,
        "legs":        legs,
        "total_km":    total_km,
    }

# ── 主流程 ────────────────────────────────────────────────────────────────────

def _has_question_mark(filled: dict) -> bool:
    """判断已填充记录中是否有里程为0的非网约车段（即当时查询失败的?）。"""
    return any(
        leg["distance_km"] == 0 and leg["mode"] != "网约车"
        for leg in filled.get("legs", [])
    )

def run_fill(input_path: str, output_path: str, key: str, delay: float) -> None:
    _load_geo_cache()
    records: list[dict] = json.loads(Path(input_path).read_text("utf-8"))
    print(f"读入 {len(records)} 条")

    # 断点续跑：读取已有输出，跳过已完成且无?的记录
    out_path = Path(output_path)
    done: dict[tuple, dict] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text("utf-8"))
            done = {(r["origin"], r["destination"]): r for r in existing
                    if not _has_question_mark(r)}
            retry = sum(1 for r in existing if _has_question_mark(r))
            print(f"续跑：已完成 {len(done)} 条，含? {retry} 条将重试\n")
        except Exception:
            pass
    else:
        print()

    results: list[dict] = []
    for i, rec in enumerate(records, 1):
        key_pair = (rec["origin"], rec["destination"])
        if key_pair in done:
            print(f"[{i}/{len(records)}] {rec['origin']} → {rec['destination']}  跳过")
            results.append(done[key_pair])
            continue
        print(f"[{i}/{len(records)}] {rec['origin']} → {rec['destination']}")
        results.append(fill_record(rec, key))
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
        time.sleep(delay)

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n✓ 写出 {len(results)} 条 → {output_path}")

def run_test(origin: str, dest: str, key: str) -> None:
    _load_geo_cache()
    # 构造一条模拟记录用来测试
    from_excel = {
        "origin": origin, "destination": dest, "count": 1,
        "has_origin_station": "", "has_dest_station": "",
        "travel_mode": "", "railway_station": "",
    }
    # 用 Transit 自动判断链路
    o_loc = geocode(origin, key)
    d_loc = geocode(dest, key)
    if not o_loc or not d_loc:
        sys.exit("地理编码失败")
    km = query_rail_km(o_loc, d_loc, origin, dest, key)
    if km:
        from_excel["travel_mode"] = "网约车→高铁→网约车"
        from_excel["railway_station"] = "无"
    else:
        from_excel["travel_mode"] = "网约车→短途巴士→网约车"
        from_excel["railway_station"] = "无"
    print(f"测试模式，推断链路: {from_excel['travel_mode']}")
    result = fill_record(from_excel, key)
    print(json.dumps(result, ensure_ascii=False, indent=2))

# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="高德 API 全段里程填充器")
    parser.add_argument("--key",    default=os.environ.get("AMAP_KEY") or os.environ.get("AMAP_API_KEY"))
    parser.add_argument("--input",  default="ai_routes.json")
    parser.add_argument("--output", default="filled.json")
    parser.add_argument("--delay",  type=float, default=0.3)
    parser.add_argument("--test",   nargs=2, metavar=("出发地", "目的地"))
    args = parser.parse_args()

    if not args.key:
        sys.exit("错误：未找到 AMAP_KEY，请在 .env 中设置")

    if args.test:
        run_test(args.test[0], args.test[1], args.key)
    else:
        run_fill(args.input, args.output, args.key, args.delay)

if __name__ == "__main__":
    main()
