#!/usr/bin/env python3
"""
Truck Distance Searcher - 货运距离查询
Uses Amap (高德地图) API for geocoding and driving distance.

Usage:
    python3 distance_searcher.py                  # interactive mode
    python3 distance_searcher.py "三明" "XIAMEN"  # single query
    python3 distance_searcher.py excel            # process Excel file
"""

import os
import sys
import time
import requests
import pandas as pd

# --- Load API key from .env ---
def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()
AMAP_KEY = os.environ.get("AMAP_KEY", "")

# --- Port name mapping (English port codes → Chinese city/district) ---
PORT_MAP = {
    "FUZHOU":       "福州市",
    "NINGBO":       "宁波市",
    "XIAMEN":       "厦门市",
    "YANTIAN":      "深圳市盐田区",
    "GUANGZHOU":    "广州市",
    "NANSHA":       "广州市南沙区",
    "SHANGHAI":     "上海市",
    "TIANJIN":      "天津市",
    "QINGDAO":      "青岛市",
    "DALIAN":       "大连市",
    "SHENZHEN":     "深圳市",
    "SHEKOU":       "深圳市蛇口",
    "TAICANG":      "太仓市",
    "ZHANGJIAGANG": "张家港市",
    "LIANYUNGANG":  "连云港市",
    "NANJING":      "南京市",
    "WUHAN":        "武汉市",
    "CHONGQING":    "重庆市",
    "CHENGDU":      "成都市",
    "TIANJINXINGANG": "天津市塘沽区",
}

# --- Amap API calls ---

def geocode(address: str) -> tuple | None:
    """Return (longitude, latitude) for an address string, or None on failure."""
    query = PORT_MAP.get(address.upper(), address)
    r = requests.get(
        "https://restapi.amap.com/v3/geocode/geo",
        params={"address": query, "key": AMAP_KEY, "output": "json"},
        timeout=10,
    )
    data = r.json()
    if data.get("status") == "1" and data.get("geocodes"):
        lng, lat = data["geocodes"][0]["location"].split(",")
        return float(lng), float(lat)
    return None


def driving_distance(origin: tuple, destination: tuple) -> dict | None:
    """Return dict with distance_km and duration_min, or None on failure."""
    r = requests.get(
        "https://restapi.amap.com/v3/direction/driving",
        params={
            "origin":      f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
            "key":         AMAP_KEY,
            "strategy":    0,       # fastest route
            "output":      "json",
        },
        timeout=10,
    )
    data = r.json()
    if data.get("status") == "1":
        path = data["route"]["paths"][0]
        return {
            "distance_km":  round(int(path["distance"]) / 1000, 1),
            "duration_min": round(int(path["duration"]) / 60),
        }
    return None


# --- High-level functions ---

def search(origin: str, destination: str) -> None:
    """Print truck distance between two named locations."""
    print(f"\n查询: {origin} → {destination}")

    orig = geocode(origin)
    if not orig:
        print(f"  [错误] 无法识别起点: '{origin}'")
        return

    dest = geocode(destination)
    if not dest:
        print(f"  [错误] 无法识别终点: '{destination}'")
        return

    result = driving_distance(orig, dest)
    if result:
        h, m = divmod(result["duration_min"], 60)
        print(f"  距离:     {result['distance_km']} km")
        print(f"  预计时间:  {result['duration_min']} 分钟 ({h}h {m}m)")
    else:
        print("  [错误] 路线规划失败")


def process_excel(file_path: str = "上游运输_处理后.xlsx") -> None:
    """Add distance and duration columns to the Excel file."""
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    df = pd.read_excel(file_path)
    missing = [c for c in ("货源地", "起运港") if c not in df.columns]
    if missing:
        print(f"缺少列: {missing}")
        return

    distances, durations = [], []

    for idx, row in df.iterrows():
        origin = str(row["货源地"]).strip()
        port   = str(row["起运港"]).strip()
        label  = f"[{idx + 1}/{len(df)}] {origin} → {port}"

        orig = geocode(origin)
        dest = geocode(port)

        if orig and dest:
            result = driving_distance(orig, dest)
            if result:
                print(f"{label}  {result['distance_km']} km")
                distances.append(result["distance_km"])
                durations.append(result["duration_min"])
            else:
                print(f"{label}  路线失败")
                distances.append(None)
                durations.append(None)
        else:
            failed = origin if not orig else port
            print(f"{label}  地址识别失败: '{failed}'")
            distances.append(None)
            durations.append(None)

        time.sleep(0.3)  # stay within free-tier rate limit

    df["运输距离(km)"] = distances
    df["预计时间(min)"] = durations

    out = file_path.replace(".xlsx", "_距离.xlsx")
    df.to_excel(out, index=False)
    ok = df["运输距离(km)"].notna().sum()
    print(f"\n完成: {ok}/{len(df)} 条成功  →  {out}")


# --- Interactive CLI ---

def interactive():
    print("=" * 52)
    print("  货运距离查询工具  (高德地图)")
    print("  命令: 'excel' 处理Excel文件  'quit' 退出")
    print("=" * 52)

    while True:
        print()
        origin = input("起点 (Origin): ").strip()
        if not origin or origin.lower() == "quit":
            break
        if origin.lower() == "excel":
            path = input("Excel文件路径 [上游运输_处理后.xlsx]: ").strip()
            process_excel(path or "上游运输_处理后.xlsx")
            continue

        destination = input("终点 (Destination): ").strip()
        if not destination or destination.lower() == "quit":
            break

        search(origin, destination)


# --- Entry point ---

if __name__ == "__main__":
    if not AMAP_KEY or AMAP_KEY == "your_amap_api_key_here":
        print("错误: 请先在 .env 文件中填写 AMAP_KEY")
        sys.exit(1)

    if len(sys.argv) == 3:
        search(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "excel":
        process_excel()
    else:
        interactive()
