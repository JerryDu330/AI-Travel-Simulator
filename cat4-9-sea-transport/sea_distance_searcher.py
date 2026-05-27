#!/usr/bin/env python3
"""
Sea Distance Searcher - 航运距离查询
离线 Dijkstra（7 462 节点），自动经苏伊士/巴拿马/好望角，不走北极航道。
内置完整港口表 + 拼写规范化字典，支持 Excel 批量处理。

数据来源: boatcalculators.com/wp-content/uploads/boat-calc/data/nav-data.min.js

Usage:
    python3 sea_distance_searcher.py                          # interactive
    python3 sea_distance_searcher.py "SHANGHAI" "ROTTERDAM"   # single query
    python3 sea_distance_searcher.py excel                    # process Excel
    python3 sea_distance_searcher.py list                     # list ports
"""

import os
import re
import sys
import math
import heapq
import time
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# 航线图加载
# ─────────────────────────────────────────────────────────────────────────────
_NAV_DATA_URL  = "https://boatcalculators.com/wp-content/uploads/boat-calc/data/nav-data.min.js"
_NAV_DATA_FILE = os.path.join(os.path.dirname(__file__), "nav-data.min.js")
_MAX_LAT = 70.0


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _load_nav_graph():
    if not os.path.exists(_NAV_DATA_FILE):
        print("正在下载航线图数据（仅首次需要）...")
        import requests
        r = requests.get(_NAV_DATA_URL,
                         headers={"User-Agent": "Mozilla/5.0"},
                         timeout=30)
        with open(_NAV_DATA_FILE, "w") as f:
            f.write(r.text)
        print("下载完成。")
    text = open(_NAV_DATA_FILE).read()
    nodes: dict[str, tuple[float, float]] = {}
    for m in re.finditer(r'"(n\d+)":\s*\{lat:\s*([-\d.]+),\s*lng:\s*([-\d.]+)\}', text):
        lat, lon = float(m.group(2)), float(m.group(3))
        if abs(lat) <= _MAX_LAT:
            nodes[m.group(1)] = (lat, lon)
    conns = re.findall(r'\["(n\d+)",\s*"(n\d+)"\]', text)
    graph: dict[str, list] = {nid: [] for nid in nodes}
    for a, b in conns:
        if a in graph and b in graph:
            d = _haversine_nm(*nodes[a], *nodes[b])
            graph[a].append((d, b))
            graph[b].append((d, a))
    return nodes, graph


print("加载航线图...", end=" ", flush=True)
_NODES, _GRAPH = _load_nav_graph()
print(f"✓ ({len(_NODES)} 节点)")

_node_cache: dict[tuple, tuple] = {}


def _nearest_node(lat: float, lon: float) -> tuple[str, float]:
    key = (round(lat, 4), round(lon, 4))
    if key in _node_cache:
        return _node_cache[key]
    best_id, best_d = None, float("inf")
    for nid, (nlat, nlon) in _NODES.items():
        d = _haversine_nm(lat, lon, nlat, nlon)
        if d < best_d:
            best_d, best_id = d, nid
    _node_cache[key] = (best_id, best_d)
    return best_id, best_d


def _dijkstra(start: str, end: str) -> float | None:
    dist = {start: 0.0}
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == end:
            return d
        if d > dist.get(u, float("inf")):
            continue
        for w, v in _GRAPH[u]:
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 强制途经关键节点（解决稀疏图在开阔海域切角问题）
# ─────────────────────────────────────────────────────────────────────────────
_WP_SINGAPORE  = (1.27,  103.82)
_WP_MID_IO     = (4.0,    68.0)
_WP_ADEN       = (12.02,  44.94)
_WP_SUEZ       = (30.97,  32.55)
_WP_GIBRALTAR  = (35.98,  -5.47)
_WP_PANAMA     = (9.36,  -79.92)

_wp_node_cache: dict[tuple, str] = {}


def _wp_node(lat: float, lon: float) -> str:
    key = (lat, lon)
    if key not in _wp_node_cache:
        _wp_node_cache[key] = _nearest_node(lat, lon)[0]
    return _wp_node_cache[key]


def _route_waypoints(orig_lat: float, orig_lon: float,
                     dest_lat: float, dest_lon: float) -> list[tuple]:
    def east_asia(lat, lon):    return lon > 100 and 0 < lat < 50
    def south_asia(lat, lon):   return 60 < lon < 100 and 0 < lat < 30
    def europe_med(lat, lon):   return -25 < lon < 42 and lat > 25
    def us_east_gulf(lat, lon): return -100 < lon < -55 and lat > 5

    from_ea = east_asia(orig_lat, orig_lon)
    from_sa = south_asia(orig_lat, orig_lon)
    to_ea   = east_asia(dest_lat, dest_lon)
    to_sa   = south_asia(dest_lat, dest_lon)

    if (from_ea and europe_med(dest_lat, dest_lon)) or \
       (to_ea   and europe_med(orig_lat, orig_lon)):
        if from_ea:
            return [_WP_SINGAPORE, _WP_MID_IO, _WP_ADEN, _WP_SUEZ, _WP_GIBRALTAR]
        else:
            return [_WP_GIBRALTAR, _WP_SUEZ, _WP_ADEN, _WP_MID_IO, _WP_SINGAPORE]

    if (from_sa and europe_med(dest_lat, dest_lon)) or \
       (to_sa   and europe_med(orig_lat, orig_lon)):
        if from_sa:
            return [_WP_ADEN, _WP_SUEZ, _WP_GIBRALTAR]
        else:
            return [_WP_GIBRALTAR, _WP_SUEZ, _WP_ADEN]

    from_asia = from_ea or from_sa
    to_asia   = to_ea   or to_sa
    if (from_asia and us_east_gulf(dest_lat, dest_lon)) or \
       (to_asia   and us_east_gulf(orig_lat, orig_lon)):
        return [_WP_PANAMA]

    return []


def _sea_distance_segmented(orig_lat: float, orig_lon: float,
                             dest_lat: float, dest_lon: float) -> float | None:
    waypoints = _route_waypoints(orig_lat, orig_lon, dest_lat, dest_lon)
    o_node, o_off = _nearest_node(orig_lat, orig_lon)
    d_node, d_off = _nearest_node(dest_lat, dest_lon)
    if not waypoints:
        route_nm = _dijkstra(o_node, d_node)
        return None if route_nm is None else route_nm + o_off + d_off
    wp_nodes = [_wp_node(lat, lon) for lat, lon in waypoints]
    all_nodes = [o_node] + wp_nodes + [d_node]
    total = o_off + d_off
    for i in range(len(all_nodes) - 1):
        seg = _dijkstra(all_nodes[i], all_nodes[i + 1])
        if seg is None:
            return None
        total += seg
    return total


# ─────────────────────────────────────────────────────────────────────────────
# 港口坐标表  {名称: (经度, 纬度)}
# ─────────────────────────────────────────────────────────────────────────────
PORTS: dict[str, tuple[float, float]] = {
    # ── 中国起运港 ──────────────────────────────────────────────────────────────
    "Ningbo, China":      (121.55,  29.87),
    "Qingdao, China":     (120.33,  36.07),
    "Shanghai, China":    (121.47,  31.23),
    "Yantian, China":     (114.27,  22.57),
    "Xiamen, China":      (118.08,  24.48),
    "Tianjin, China":     (117.72,  38.99),
    "Fuzhou, China":      (119.30,  26.08),
    "Shenzhen, China":    (114.05,  22.52),
    "Shekou, China":      (113.91,  22.48),
    "Dalian, China":      (121.65,  38.91),
    "Taicang, China":     (121.10,  31.45),
    "Lianyungang, China": (119.16,  34.73),
    "Shantou, China":     (116.68,  23.35),
    "Guangzhou, China":   (113.26,  23.13),
    "Yangzhou, China":    (121.47,  31.23),
    "Nanjing, China":     (121.47,  31.23),
    "Suzhou, China":      (121.47,  31.23),
    "Hangzhou, China":    (121.55,  29.87),
    "Yiwu, China":        (121.55,  29.87),
    "Xian, China":        (121.47,  31.23),
    # ── 欧洲 ────────────────────────────────────────────────────────────────────
    "Rotterdam":          (4.29,   51.89),
    "Le Havre":           (0.11,   49.49),
    "Fos Sur Mer":        (4.86,   43.43),
    "Hamburg":            (9.98,   53.55),
    "Bremerhaven":        (8.58,   53.54),
    "Dunkerque":          (2.36,   51.04),
    "Antwerp":            (4.40,   51.23),
    "Felixstowe":         (1.35,   51.95),
    "Gothenburg":         (11.96,  57.71),
    "Aarhus":             (10.21,  56.15),
    "Kalundborg":         (11.09,  55.68),
    "Gdansk":             (18.66,  54.35),
    "Gdynia":             (18.54,  54.53),
    "Szczecin":           (14.55,  53.43),
    "Barcelona":          (2.18,   41.38),
    "Valencia":           (-0.32,  39.45),
    "Bilbao":             (-3.02,  43.33),
    "Algeciras":          (-5.45,  36.13),
    "Las Palmas":         (-15.41, 27.98),
    "Tenerife":           (-16.24, 28.46),
    "Southampton":        (-1.40,  50.90),
    "Liverpool":          (-3.00,  53.45),
    "Tilbury":            (0.37,   51.46),
    "Glasgow":            (-4.77,  55.86),
    "Belfast":            (-5.93,  54.60),
    "Genoa":              (8.93,   44.41),
    "La Spezia":          (9.82,   44.10),
    "Livorno":            (10.30,  43.55),
    "Naples":             (14.27,  40.84),
    "Trieste":            (13.76,  45.65),
    "Venice":             (12.33,  45.43),
    "Catania":            (15.09,  37.50),
    "Koper":              (13.73,  45.55),
    "Rijeka":             (14.44,  45.33),
    "Piraeus":            (23.62,  37.94),
    "Thessaloniki":       (22.93,  40.63),
    "Constanta":          (28.65,  44.18),
    "Burgas":             (27.47,  42.50),
    "Varna":              (27.91,  43.20),
    "Marseille":          (5.36,   43.30),
    "Rouen":              (1.10,   49.44),
    "Nantes":             (-1.55,  47.22),
    "Zeebrugge":          (3.20,   51.33),
    "Ghent":              (3.72,   51.10),
    "Amsterdam":          (4.91,   52.37),
    "Wilhelmshaven":      (8.15,   53.51),
    "Bremen":             (8.81,   53.08),
    "Lübeck":             (10.69,  53.87),
    "Kiel":               (10.15,  54.33),
    "Copenhagen":         (12.59,  55.68),
    "Fredericia":         (9.76,   55.56),
    "Oslo":               (10.74,  59.91),
    "Stavanger":          (5.73,   58.97),
    "Trondheim":          (10.39,  63.43),
    "Bergen":             (5.32,   60.39),
    "Helsingborg":        (12.69,  56.04),
    "Stockholm":          (18.08,  59.35),
    "Helsinki":           (25.00,  60.17),
    "Riga":               (24.10,  56.95),
    "Lisbon":             (-9.14,  38.71),
    "Leixoes":            (-8.70,  41.18),
    "Sines":              (-8.88,  37.96),
    "Bobadela":           (-9.14,  38.71),
    "Casablanca":         (-7.61,  33.61),
    # ── 中东 ────────────────────────────────────────────────────────────────────
    "Ashdod":             (34.65,  31.82),
    "Haifa":              (35.00,  32.82),
    "Jeddah":             (39.17,  21.50),
    "Dubai":              (55.27,  25.26),
    "Jebel Ali":          (55.02,  24.99),
    "Abu Dhabi":          (54.37,  24.47),
    "Dammam":             (50.10,  26.43),
    "Bandar Abbas":       (56.37,  27.18),
    "Umm Qasr":           (47.92,  30.03),
    "Doha":               (51.55,  25.29),
    # ── 非洲 ────────────────────────────────────────────────────────────────────
    "Durban":             (31.03, -29.87),
    "Cape Town":          (18.43, -33.92),
    "Mombasa":            (39.67,  -4.05),
    "Dakar":              (-17.44, 14.69),
    "Tema":               (-0.02,   5.63),
    "Abidjan":            (-4.01,   5.35),
    "Douala":             (9.70,    4.05),
    "Kinshasa":           (15.32,  -4.32),
    "Dar Es Salaam":      (39.28,  -6.82),
    "Maputo":             (32.57, -25.97),
    "Reunion":            (55.47, -20.87),
    "Noumea":             (166.46, -22.28),
    "Pointe Des Galets":  (55.29, -20.89),
    # ── 亚太 ────────────────────────────────────────────────────────────────────
    "Singapore":          (103.82,   1.27),
    "Port Klang":         (101.39,   3.00),
    "Tanjung Pelepas":    (103.55,   1.37),
    "Jakarta":            (106.88,  -6.10),
    "Laem Chabang":       (100.90,  13.08),
    "Ho Chi Minh":        (106.72,  10.73),
    "Haiphong":           (106.68,  20.87),
    "Manila":             (120.97,  14.60),
    "Colombo":            (79.87,    6.93),
    "Mumbai":             (72.84,   18.93),
    "Nhava Sheva":        (72.95,   18.95),
    "Chennai":            (80.29,   13.09),
    "Karachi":            (66.99,   24.84),
    "Busan":              (129.04,  35.10),
    "Incheon":            (126.62,  37.45),
    "Tokyo":              (139.77,  35.65),
    "Yokohama":           (139.63,  35.45),
    "Osaka":              (135.44,  34.65),
    "Nagoya":             (136.88,  35.06),
    "Kobe":               (135.18,  34.69),
    "Hakata":             (130.41,  33.61),
    "Moji":               (130.96,  33.95),
    "Kanazawa":           (136.63,  36.58),
    "Takamatsu":          (134.05,  34.35),
    "Matsuyama":          (132.76,  33.84),
    "Kawasaki":           (139.72,  35.52),
    "Hibiki":             (130.90,  33.88),
    "Fukui":              (136.21,  36.06),
    "Kaohsiung":          (120.30,  22.63),
    "Keelung":            (121.74,  25.13),
    "Hong Kong":          (114.17,  22.30),
    "Sydney":             (151.21, -33.87),
    "Melbourne":          (144.95, -37.82),
    "Brisbane":           (153.03, -27.47),
    "Fremantle":          (115.74, -32.05),
    "Adelaide":           (138.51, -34.92),
    "Bell Bay":           (146.87, -41.07),
    "Auckland":           (174.76, -36.84),
    "Lyttelton":          (172.72, -43.60),
    # ── 北美 ────────────────────────────────────────────────────────────────────
    "Long Beach":         (-118.22, 33.77),
    "Los Angeles":        (-118.27, 33.73),
    "Seattle":            (-122.34, 47.60),
    "Tacoma":             (-122.42, 47.27),
    "Vancouver":          (-123.12, 49.29),
    "Prince Rupert":      (-130.32, 54.31),
    "New York":           (-74.00,  40.70),
    "Savannah":           (-81.10,  32.08),
    "Charleston":         (-79.92,  32.78),
    "Norfolk":            (-76.30,  36.92),
    "Baltimore":          (-76.61,  39.27),
    "Houston":            (-95.27,  29.73),
    "New Orleans":        (-90.07,  29.95),
    "Miami":              (-80.13,  25.77),
    "Tampa":              (-82.46,  27.95),
    "Halifax":            (-63.57,  44.65),
    "Montreal":           (-73.55,  45.50),
    "Toronto":            (-79.38,  43.64),
    "Edmonton":           (-113.49, 53.55),
    "San Juan":           (-66.07,  18.47),
    "Ensenada":           (-116.63, 31.87),
    "Manzanillo":         (-104.32, 19.05),
    "Lazaro Cardenas":    (-102.20, 17.95),
    "Buenaventura":       (-77.08,   3.88),
    "Callao":             (-77.15, -12.05),
    "Valparaiso":         (-71.63, -33.04),
    "San Antonio":        (-71.63, -33.57),
    "Guayaquil":          (-79.90,  -2.25),
    "Colon":              (-79.90,   9.36),
    "Puerto Quetzal":     (-90.79,  13.92),
    "Santos":             (-46.33, -23.95),
    "Itajai":             (-48.65, -26.90),
    "Paranagua":          (-48.52, -25.52),
    "Salvador":           (-38.51, -12.97),
    "Vitoria":            (-40.34, -20.32),
    "Buenos Aires":       (-58.37, -34.61),
    "Montevideo":         (-56.22, -34.90),
    "Caucedo":            (-69.57,  18.44),
    # ── 其他 ────────────────────────────────────────────────────────────────────
    "Istanbul":           (28.98,  41.01),
    "Mersin":             (34.64,  36.79),
    "Izmir":              (27.14,  38.42),
    "Vostochny":          (132.87, 42.77),
}

# ─────────────────────────────────────────────────────────────────────────────
# 拼写/别名规范化字典  →  PORTS 的 key
# ─────────────────────────────────────────────────────────────────────────────
NORMALIZE: dict[str, str] = {
    # Rotterdam
    "Rotterdam, Netherlands":          "Rotterdam",
    "Rotterdam, Germany":              "Rotterdam",
    "Rotterdam, Natherlands":          "Rotterdam",
    "Rotterdam, Netherland":           "Rotterdam",
    "Rotterdam, The Netherlands":      "Rotterdam",
    "Rotterdam, The Netherlandsy":     "Rotterdam",
    "Rotterdam, Newtherlands":         "Rotterdam",
    "Rooterdam":                       "Rotterdam",
    "Rotterdan":                       "Rotterdam",
    "Rottredam":                       "Rotterdam",
    "Rtm":                             "Rotterdam",
    "Switzerland Via Rotterdam, Netherlands": "Rotterdam",
    # Le Havre
    "Le Havre, France":                "Le Havre",
    "Le Harve, France":                "Le Havre",
    "Le Harvre, France":               "Le Havre",
    "Le Haver":                        "Le Havre",
    "Le Haver, France":                "Le Havre",
    "Le Harve":                        "Le Havre",
    "Lehavre, France":                 "Le Havre",
    "Le Havre，France":                "Le Havre",
    "Fr-Le Havre":                     "Le Havre",
    "Leh":                             "Le Havre",
    "Le Harvre":                       "Le Havre",
    # Fos Sur Mer
    "Fos Sur Mer, France":             "Fos Sur Mer",
    "Fos S/Mer":                       "Fos Sur Mer",
    "Fos Ser Mer":                     "Fos Sur Mer",
    "Fos Ser Mer, France":             "Fos Sur Mer",
    "Fos Sur Mar, France":             "Fos Sur Mer",
    "Fos Sur Mer Port, France":        "Fos Sur Mer",
    "Fos Sur Mer, Bouches-Du-Rhone, France": "Fos Sur Mer",
    "Fos Sur Mer.":                    "Fos Sur Mer",
    "Fos Sur Mer，France":             "Fos Sur Mer",
    "Fos Sur Mur, France":             "Fos Sur Mer",
    "Fos, France":                     "Fos Sur Mer",
    "Fos-Sur-Mer (Frfos)":             "Fos Sur Mer",
    "Fr-Fos Sur Mer":                  "Fos Sur Mer",
    "For Sur Mer, France":             "Fos Sur Mer",
    "Fos":                             "Fos Sur Mer",
    # Dunkerque
    "Dunkerque, France":               "Dunkerque",
    "Dunkirk, France":                 "Dunkerque",
    "Dunkirk":                         "Dunkerque",
    "Dunqueker, France":               "Dunkerque",
    "Fr-Dunkerque":                    "Dunkerque",
    "Dunkerque (Frdkk)":               "Dunkerque",
    "Dkk":                             "Dunkerque",
    # Multi-port shortcuts
    "Fos/Dkk":                         "Fos Sur Mer",
    "Dkk.Fos":                         "Dunkerque",
    "Dkk/Fos":                         "Dunkerque",
    "Fos/Dkk/Leh/Bas":                 "Fos Sur Mer",
    "Bas/Fos/Dkk/Leh":                 "Fos Sur Mer",
    "Dkk/Fos/Leh/Bas":                 "Dunkerque",
    "Dkk.Fos/Leh":                     "Dunkerque",
    "Dkk/Fos/Leh":                     "Dunkerque",
    # Hamburg
    "Hamburg, Germany":                "Hamburg",
    "Hambrug":                         "Hamburg",
    "Hambugr":                         "Hamburg",
    "Hambugr, Germany":                "Hamburg",
    "Hambury, Germany":                "Hamburg",
    "Hamrburg":                        "Hamburg",
    "Hanburg":                         "Hamburg",
    "Hanburg, Germany":                "Hamburg",
    "Hambrug, Germany":                "Hamburg",
    # Bremerhaven
    "Bremerhaven, Germany":            "Bremerhaven",
    "Bermerhaven, Germany":            "Bremerhaven",
    "Bremerhaven, , Germany":          "Bremerhaven",
    "Bremerhaven, German":             "Bremerhaven",
    "Bermerhaven":                     "Bremerhaven",
    "Bremen, Germany":                 "Bremerhaven",
    # Antwerp
    "Antwerp, Belgium":                "Antwerp",
    "Antwerpen":                       "Antwerp",
    "Antwerpen, Belgium":              "Antwerp",
    "Antewerp":                        "Antwerp",
    "Antwerp，Belgium":                "Antwerp",
    # Gdansk
    "Gdansk, Poland":                  "Gdansk",
    "Gadansk, Poland":                 "Gdansk",
    "Gdanska, Poland":                 "Gdansk",
    "Gdansk, Pl":                      "Gdansk",
    "Gdansk , Poland":                 "Gdansk",
    "Gadansk":                         "Gdansk",
    # Gdynia
    "Gdynia, Poland":                  "Gdynia",
    "Gdynia/Gdansk":                   "Gdynia",
    # Felixstowe
    "Felixstowe, United Kingdom":      "Felixstowe",
    "Felixstonwe":                     "Felixstowe",
    "Felixstone, United Kingdom":      "Felixstowe",
    "Felixstowne":                     "Felixstowe",
    "Fleixstone, United Kingdom":      "Felixstowe",
    "Fxt":                             "Felixstowe",
    "Fxt, Uk":                         "Felixstowe",
    "Felixstone":                      "Felixstowe",
    "Felixstowe, Uk":                  "Felixstowe",
    "Jef":                             "Felixstowe",
    # Southampton
    "Southampton, United Kingdom":     "Southampton",
    "Southampton/Liverpool, United Kingdom": "Southampton",
    "Liverpool/Felixstowe, United Kingdom":  "Felixstowe",
    "Gbsou Southampton":               "Southampton",
    # Gothenburg
    "Gothenburg, Sweden":              "Gothenburg",
    "Goteborg, Sweden":                "Gothenburg",
    # Aarhus
    "Aarhus, Denmark":                 "Aarhus",
    "Arhus, Denmark":                  "Aarhus",
    "Arhus":                           "Aarhus",
    # Kalundborg
    "Kalundborg, Denmark":             "Kalundborg",
    "Kalundborg , Denmark":            "Kalundborg",
    "Kalundborg Denmark":              "Kalundborg",
    "Kalundborg, Denmark,":            "Kalundborg",
    # Copenhagen
    "Copenhagen, Denmark":             "Copenhagen",
    "Den":                             "Copenhagen",
    # Fredericia / Taulov
    "Fredericia, Denmark":             "Fredericia",
    "Taulov":                          "Fredericia",
    "Taulov, Denmark":                 "Fredericia",
    # Szczecin
    "Szczecin, Poland":                "Szczecin",
    # Barcelona
    "Barcelona, Spain":                "Barcelona",
    "Barcelona , Spain":               "Barcelona",
    # Valencia
    "Valencia, Spain":                 "Valencia",
    "Valencia Harbour Spain":          "Valencia",
    "Valencia Harbour, Spain":         "Valencia",
    "Valencia，Spain":                 "Valencia",
    # Genoa
    "Genova":                          "Genoa",
    "Genova, Italy":                   "Genoa",
    "Genoa, Italy":                    "Genoa",
    # Koper
    "Koper, Slovenia":                 "Koper",
    "Koper Slovenia":                  "Koper",
    "Koper, Italy":                    "Koper",
    "Koper, Slovennia":                "Koper",
    # Piraeus
    "Piraeus, Greece":                 "Piraeus",
    "Gre":                             "Piraeus",
    # Trieste
    "Trieste, Italy":                  "Trieste",
    # Rijeka
    "Rijeka, Croatia":                 "Rijeka",
    "Skrljevo, Croatia":               "Rijeka",
    "Durres":                          "Rijeka",
    # Naples
    "Naples, Italy":                   "Naples",
    # La Spezia
    "La Spezia, Italy":                "La Spezia",
    # Livorno
    "Livorno, Italy":                  "Livorno",
    # Catania
    "Catania, Italy":                  "Catania",
    # Venice
    "Venice, Italy":                   "Venice",
    # Bari / Ancona → approximate
    "Bari, Italy":                     "La Spezia",
    "Ancona (An) Italy":               "Trieste",
    "Ancona, Italy":                   "Trieste",
    # Marseille
    "Marseille, France":               "Marseille",
    # Rouen
    "Rouen, France":                   "Rouen",
    "Roune, France":                   "Rouen",
    # Bilbao
    "Bilbao, Spain":                   "Bilbao",
    # Las Palmas
    "Las Palmas De G.C, Spain":        "Las Palmas",
    "Las Palmas De Gran Canaria Port, Spain": "Las Palmas",
    "Las Palmas, Canary Islands":      "Las Palmas",
    # Tenerife
    "Tenerife , Spain":                "Tenerife",
    "Tenerife, Spain":                 "Tenerife",
    "Tenerife Harbour, Spain":         "Tenerife",
    "Tenerife, Harbour Spain":         "Tenerife",
    # Zeebrugge
    "Zeebrugge, Belgium":              "Zeebrugge",
    # Amsterdam
    "Amsterdam, Netherlands":          "Amsterdam",
    # Wilhelmshaven
    "Wilhelmshaven, Germany":          "Wilhelmshaven",
    # Constanta
    "Constanta, Romania":              "Constanta",
    "Constanta Port , Romania":        "Constanta",
    # Burgas
    "Burgas, Bulgaria":                "Burgas",
    # Thessaloniki
    "Thessaloniki Greece":             "Thessaloniki",
    # Algeciras
    "Algeciras, Spain":                "Algeciras",
    # Norway
    "Oslo, Norway":                    "Oslo",
    "Oslo，Norway":                    "Oslo",
    "Stavanger, Norway":               "Stavanger",
    "Trondheim, Norway":               "Trondheim",
    "Larvik, Norway":                  "Oslo",
    "Moss, Norway":                    "Oslo",
    "Fredrikstad，Norway":             "Oslo",
    "Ola":                             "Oslo",
    # Finland
    "Helsinki, Finland":               "Helsinki",
    "Kokkola, Finland":                "Helsinki",
    "Mantsala, Finland":               "Helsinki",
    # Riga
    "Riga, Latvia":                    "Riga",
    # Helsingborg / Stockholm
    "Helsingborg, Sweden":             "Helsingborg",
    "Stockholm, Sweden":               "Stockholm",
    # Lisbon / Portugal
    "Lisbon, Portugal":                "Lisbon",
    "Lisboa, Portugal":                "Lisbon",
    "Lisboa - Bobadela":               "Lisbon",
    "Bobadela":                        "Bobadela",
    "Bobadela, Portugal":              "Bobadela",
    "Leixoes Portugal":                "Leixoes",
    "Leixoes, Portugal":               "Leixoes",
    "Leixoes, France":                 "Leixoes",
    "Sines, Portugal":                 "Sines",
    # Casablanca
    "Casablanca, Morocco":             "Casablanca",
    # Inland Germany/Europe → Hamburg or Rotterdam
    "Dortmund":                        "Hamburg",
    "Frankfurt, Germany":              "Hamburg",
    "Nuremberg, Germany":              "Hamburg",
    "Nurnberg, Germany":               "Hamburg",
    "Oberhausen, Germany":             "Hamburg",
    "Landsberg, Germany":              "Hamburg",
    "Hochdorf":                        "Hamburg",
    # Netherlands inland → Rotterdam
    "Tiel":                            "Rotterdam",
    "Tiel, Netherlands":               "Rotterdam",
    "Tiel, Gelderland, Netherlands":   "Rotterdam",
    "Tiel, Gelderland,Netherlands":    "Rotterdam",
    "Tiel,Gelderland, Netherlands":    "Rotterdam",
    "Tilburg, Netherlands":            "Rotterdam",
    "Westzaan, Netherlands":           "Rotterdam",
    "Zaandam":                         "Rotterdam",
    "Duisburg":                        "Rotterdam",
    "Bassens":                         "Rotterdam",
    "Bassens, France":                 "Rotterdam",
    "Sxb":                             "Rotterdam",
    "Pet":                             "Rotterdam",
    # Belgium inland → Antwerp
    "Meerhout, Belgium":               "Antwerp",
    "Meerhout":                        "Antwerp",
    # Inland Switzerland → Rotterdam/Hamburg
    "Basel, Switzerland":              "Rotterdam",
    "Linz, Austria":                   "Hamburg",
    "Vienna, Austria":                 "Hamburg",
    "Wien, Austria":                   "Hamburg",
    "Enns, Austria":                   "Hamburg",
    # Poland inland → Gdansk
    "Prusicz Gdanski, Poland":         "Gdansk",
    "Warsaw, Poland":                  "Gdansk",
    # ── 中东 ────────────────────────────────────────────────────────────────────
    "Ashdod, Israel":                  "Ashdod",
    "Ashdod , Israel":                 "Ashdod",
    "Ashdod ，Israel":                 "Ashdod",
    "Haifa, Israel":                   "Haifa",
    "Haifa , Israel":                  "Haifa",
    "Hai":                             "Haifa",
    "Hin":                             "Haifa",
    "Jeddah, Saudi Arabia":            "Jeddah",
    "Jebel Ali":                       "Jebel Ali",
    "Doha":                            "Doha",
    "Umm Qasr North, , Iraq":          "Umm Qasr",
    "Korfezi, Turkey":                 "Istanbul",
    "Istanbul, Turkey":                "Istanbul",
    "Mersin, Turkey":                  "Mersin",
    # ── 非洲 ────────────────────────────────────────────────────────────────────
    "Durban, South Africa":            "Durban",
    "Durban Zaf":                      "Durban",
    "Dwt":                             "Durban",
    "Cape Town, South Africa":         "Cape Town",
    "Capetown, South Africa":          "Cape Town",
    "Capetown, South Africasouth Africa": "Cape Town",
    "Mombasa":                         "Mombasa",
    "Keniya":                          "Mombasa",
    "Kenya":                           "Mombasa",
    "Dakar, Senegal":                  "Dakar",
    "Tema, Ghana":                     "Tema",
    "Togo":                            "Tema",
    "Abidjan, Ivory Coast":            "Abidjan",
    "Douala, Cameroun":                "Douala",
    "Kinshasa, Congo":                 "Kinshasa",
    "Reunion":                         "Reunion",
    "Pointe Des Galets":               "Pointe Des Galets",
    "Pointe Des Galets - Reunion Island": "Pointe Des Galets",
    "Pointe Des Galets, France":       "Pointe Des Galets",
    "Pointe Des Galets, Reunion":      "Pointe Des Galets",
    "Port De Pointe Des Galets":       "Pointe Des Galets",
    "Port De Pointe Des Galets , France": "Pointe Des Galets",
    "Noumea, France":                  "Noumea",
    # ── 亚太 ────────────────────────────────────────────────────────────────────
    "Singapore, Singapore":            "Singapore",
    "Port Klang, Malaysia":            "Port Klang",
    "Kelang, Malaysia":                "Port Klang",
    "Klang, Malaysia":                 "Port Klang",
    "Tanjung Pelepas":                 "Tanjung Pelepas",
    "Laem Chabang, Thailand":          "Laem Chabang",
    "Busan, Korea":                    "Busan",
    "Busan, Korea Rep.":               "Busan",
    "Busan/Incheon/Pyeongtaek, Korea Rep.": "Busan",
    "Busan, South Korea":              "Busan",
    "Incheon, Korea":                  "Incheon",
    "Incheon，Korea":                  "Incheon",
    "Incheon, South Korea":            "Incheon",
    "Keelung, Taiwan":                 "Keelung",
    "Kaohsiung":                       "Kaohsiung",
    "Kch":                             "Kaohsiung",
    "Kch Poart":                       "Kaohsiung",
    "Kch Port":                        "Kaohsiung",
    "Lyt":                             "Lyttelton",
    "Hong Kong":                       "Hong Kong",
    "Tokyo, Japan":                    "Tokyo",
    "Tokyo Port, Japan":               "Tokyo",
    "Yokohama, Japan":                 "Yokohama",
    "Osaka, Japan":                    "Osaka",
    "Osaka South Port, Japan":         "Osaka",
    "Nagoya, Japan":                   "Nagoya",
    "Nagoya Port, Japan":              "Nagoya",
    "Kobe, Japan":                     "Kobe",
    "Kobe - Hyogo, Japan":             "Kobe",
    "Kobe, Hyogo":                     "Kobe",
    "Hakata, Japan":                   "Hakata",
    "Kanazawa, Japan":                 "Kanazawa",
    "Kanazawa Port, Japan":            "Kanazawa",
    "Takamatsu, Japan":                "Takamatsu",
    "Matsuyama, Japan":                "Matsuyama",
    "Kawasaki - Kanagawa, Japan":      "Kawasaki",
    "Kawasaki-Kanagawa, Japan":        "Kawasaki",
    "Wasaki-Kanagawa":                 "Kawasaki",
    "Hibiki, Japan":                   "Hibiki",
    "Fukui, Japan":                    "Fukui",
    "Colombo, Sri Lanka":              "Colombo",
    "Manila South":                    "Manila",
    "Jakarta, Indonesia":              "Jakarta",
    "Cikarang, Indonesia":             "Jakarta",
    "Cikarang Dry Port, Indonesia":    "Jakarta",
    # Australia
    "Melbourne, Australia":            "Melbourne",
    "Sydney, Australia":               "Sydney",
    "Brisbane, Australia":             "Brisbane",
    "Fremantle, Australia":            "Fremantle",
    "Adelaide, Australia":             "Adelaide",
    "Bell Bay, Australia":             "Bell Bay",
    "Aumel, Australia":                "Melbourne",
    "Aumel":                           "Melbourne",
    "Aubne":                           "Brisbane",
    "Aubne, Australia":                "Brisbane",
    "Aufre":                           "Fremantle",
    "Aufre, Australia":                "Fremantle",
    "Lyttelton":                       "Lyttelton",
    "Lyttelton, New Zeland":           "Lyttelton",
    "Auckland":                        "Auckland",
    "Auckland, New Zealand":           "Auckland",
    "Auckland, New Zeland":            "Auckland",
    "Akl":                             "Auckland",
    # ── 北美 ────────────────────────────────────────────────────────────────────
    "Long Beach, Ca, United States":   "Long Beach",
    "Long Beach, Ca, Usa":             "Long Beach",
    "Long Beach, Ca":                  "Long Beach",
    "Long Beach, United States":       "Long Beach",
    "Long Beach, Usa":                 "Long Beach",
    "Longbeach, Usa":                  "Long Beach",
    "Lox":                             "Long Beach",
    "Oak":                             "Long Beach",
    "Spr":                             "Long Beach",
    "Los Angeles, United States":      "Los Angeles",
    "Los Angeles/Long Beach, United States": "Long Beach",
    "L.A.Usa":                         "Los Angeles",
    "California, United States":       "Long Beach",
    "Seattle, United States":          "Seattle",
    "Tacoma, United States":           "Tacoma",
    "Vancouver, Canada":               "Vancouver",
    "Vancover, Canada":                "Vancouver",
    "Prince Rupert, Canada":           "Prince Rupert",
    "New York , Usa":                  "New York",
    "New York, United States":         "New York",
    "Savannah, United States":         "Savannah",
    "Charleston, United States":       "Charleston",
    "Norfolk, United States":          "Norfolk",
    "Baltimore, United States":        "Baltimore",
    "Houston, United States":          "Houston",
    "Miami, United States":            "Miami",
    "Halifax":                         "Halifax",
    "Halifax, Canada":                 "Halifax",
    "Montreal, Canada":                "Montreal",
    "Montreal Quebec, Canada":         "Montreal",
    "Toronto, Canada":                 "Montreal",
    "Edmonton, Canada":                "Vancouver",
    "San Juan, Puerto Rico":           "San Juan",
    "Manzanillo, Mexico":              "Manzanillo",
    "Manzanillo, Colima Or Lazaro Cardenas, Michoacan Mx": "Manzanillo",
    "Ensenada, Mexico":                "Ensenada",
    "Ensenda, Mexico":                 "Ensenada",
    "Lazaro Cardenas, Mexico":         "Lazaro Cardenas",
    "Lazaro Cardeas, Mexico":          "Lazaro Cardenas",
    "Lazaro Cardeas, Mexio":           "Lazaro Cardenas",
    "Lazaro Cardenas, Mexio":          "Lazaro Cardenas",
    "Lázaro Cardenas, Mexico":         "Lazaro Cardenas",
    "Lerma, Mexico":                   "Manzanillo",
    "Mexicali, Mexico":                "Los Angeles",
    "Colon Free Zone, Panama":         "Colon",
    "Buenaventura, Colombia":          "Buenaventura",
    "Callao, Peru":                    "Callao",
    "Callo, Peru":                     "Callao",
    "Valparaiso, Chile":               "Valparaiso",
    "San Antonio, Chile":              "San Antonio",
    "Guayaquil, Ecuador":              "Guayaquil",
    "Santos, Brazil":                  "Santos",
    "Navegantes, Brazil":              "Itajai",
    "Navegantes – Sc, Brazil":         "Itajai",
    "Itajai Or Navegantes, Brazil":    "Itajai",
    "Parangua, Brazil":                "Paranagua",
    "Salvador De Bahia, Brazil":       "Salvador",
    "Vitoria/Es, Brazil":              "Vitoria",
    "Buenos Aires, Argentina":         "Buenos Aires",
    "Montevide, Uruguay":              "Montevideo",
    "Montevide , Uruguay":             "Montevideo",
    "Montevideo, Uruguay":             "Montevideo",
    "Caucedo, Republica Dominicana":   "Caucedo",
    "Vostochny, Russia":               "Vostochny",
    "Moscow, Russia":                  "Vostochny",
    # Ireland → nearest UK port
    "Dub, Ireland":                    "Southampton",
    "Dublin":                          "Southampton",
    "Dublin, Ireland":                 "Southampton",
    "Belfast, Ireland":                "Southampton",
    "Manchester, United Kingdom":      "Felixstowe",
    "London, United Kingdom":          "Felixstowe",
    # Inland France/Belgium
    "Roissy, France":                  "Le Havre",
    # Misc LOCODE abbreviations
    "Ctv":                             "Montevideo",
    "Mtj":                             "Callao",
    "Tul":                             "Houston",
    "Far":                             "Lisbon",
    # Central America
    "Wca Hub El Salvador":             "Puerto Quetzal",
    "Guatemala, Guatemala":            "Puerto Quetzal",
    "Honduras, Honduras":              "Puerto Quetzal",
    "Nicaragua":                       "Puerto Quetzal",
    "Costa Rica":                      "Puerto Quetzal",
    # Pacific islands
    "Gf-Degrad Des Cannes":            "Callao",
    "Pf-Papeete":                      "Auckland",
    "Gp-Pointe A Pitre":               "Miami",
    # Other regions
    "Belarus":                         "Gdansk",
    # China domestic
    "Shanghai Yangshan Bonded Free Port":    "Shanghai, China",
    "Dap Shanghai Yangshan Bonded Free Por": "Shanghai, China",
    "Shanghai Yangshan Bonded Free Por":     "Shanghai, China",
    "厦门海沧港区，中国":                        "Xiamen, China",
    # Inline US cities → nearest port
    "Dallas, United States":           "Houston",
    "Aurora, Co,United States":        "Long Beach",
    "Alachua, Fl,United States":       "Miami",
    "Ardmore, Ok,United States":       "Houston",
    "Bessemer, Al,United States":      "Savannah",
    "Bethel, Pa, United States":       "Baltimore",
    "Blair, Ne,United States":         "Long Beach",
    "Fulton, Mo,United States":        "Houston",
    "Indianola, Ms,United States":     "Savannah",
    "Jackson, Ga,United States":       "Savannah",
    "Janesville, Wi,United States":    "Long Beach",
    "Jonesville, Sc,United States":    "Charleston",
    "Lebec, Ca,United States":         "Long Beach",
    "Longview, Tx,United States":      "Houston",
    "Marion, In,United States":        "Baltimore",
    "North Little Rock, Ar,United States": "Houston",
    "Rialto, Usa":                     "Long Beach",
    "San Antonio, Tx,United States":   "Houston",
    "Scottsville, Ky, United States":  "Savannah",
    "South Boston, Va,United States":  "Norfolk",
    "Walton, Ky,United States":        "Savannah",
    "Zanesville, Oh,United States":    "Baltimore",
}

# 过于模糊、无法匹配具体港口的条目
SKIP_KEYWORDS = {
    "pls", "advise", "advice", "to be", "tba", "tbd", "any port",
    "pls adv.", "pls advice.", "pls. advise", "pls be advised",
    "france", "germany", "netherlands", "spain", "italy", "turkey",
    "russia", "ukraine", "brazil", "chile", "australia", "new zealand",
    "canada", "usa", "united states", "mexico", "switzerland", "austria",
    "poland", "denmark", "sweden", "norway", "finland", "belgium",
    "portugal", "greece", "romania", "bulgaria", "croatia", "ireland",
    "uk", "united kingdom", "saudi arabia", "united arab emirates",
    "taiwan", "thailand", "indonesia", "malaysia",
    "philippines", "vietnam", "india", "pakistan", "south africa",
    "ghana", "senegal", "cameroon", "kenya", "congo", "uruguay",
    "colombia", "ecuador", "peru", "argentina", "panama",
}


def _should_skip(name: str) -> bool:
    return name.lower().strip() in SKIP_KEYWORDS


# ─────────────────────────────────────────────────────────────────────────────
# 港口解析
# ─────────────────────────────────────────────────────────────────────────────

def resolve_port(name: str) -> tuple[float, float] | None:
    """Return (lon, lat) for a port name, or None if unknown."""
    raw = name.strip()
    if _should_skip(raw):
        return None
    # 1. Direct match
    if raw in PORTS:
        return PORTS[raw]
    # 2. Normalize table
    canonical = NORMALIZE.get(raw)
    if canonical and canonical in PORTS:
        return PORTS[canonical]
    # 3. Case-insensitive normalize
    raw_up = raw.upper()
    for k, v in NORMALIZE.items():
        if k.upper() == raw_up and v in PORTS:
            return PORTS[v]
    # 4. Case-insensitive ports
    for k, v in PORTS.items():
        if k.upper() == raw_up:
            return v
    return None


def list_similar(name: str, n: int = 5) -> list[str]:
    q = name.upper()
    return [k for k in PORTS if q in k.upper()][:n]


# ─────────────────────────────────────────────────────────────────────────────
# 核心距离计算
# ─────────────────────────────────────────────────────────────────────────────

def sea_distance(origin: str, destination: str) -> dict | None:
    """Return dict with distance_nm, distance_km, or None on failure."""
    orig = resolve_port(origin)
    dest = resolve_port(destination)
    if orig is None or dest is None:
        return None
    lon1, lat1 = orig
    lon2, lat2 = dest
    nm = _sea_distance_segmented(lat1, lon1, lat2, lon2)
    if nm is None:
        return None
    return {
        "distance_nm": round(nm),
        "distance_km": round(nm * 1.852),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 高级功能
# ─────────────────────────────────────────────────────────────────────────────

def search(origin: str, destination: str) -> None:
    print(f"\n航运查询: {origin} → {destination}")
    orig = resolve_port(origin)
    dest = resolve_port(destination)
    if orig is None:
        similar = list_similar(origin)
        msg = f"  [错误] 未知港口: '{origin}'"
        if similar:
            msg += f"\n  相似港口: {', '.join(similar)}"
        print(msg)
        return
    if dest is None:
        similar = list_similar(destination)
        msg = f"  [错误] 未知港口: '{destination}'"
        if similar:
            msg += f"\n  相似港口: {', '.join(similar)}"
        print(msg)
        return
    result = sea_distance(origin, destination)
    if result:
        print(f"  海上距离:  {result['distance_nm']:,} 海里  ({result['distance_km']:,} km)")
    else:
        print("  [错误] 航线计算失败")


def process_excel(
    file_path: str = "运输数据_三维汇总表_全新版.xlsx",
    sheet_name: str = "三维汇总表_按订单排序",
    origin_col: str = "起运港",
    dest_col: str = "目的港",
    mode_col: str | None = "运输方式",
    sea_modes: tuple = ("VESSEL", "SEA"),
) -> None:
    """
    Calculate sea distances for an Excel file.
    If mode_col is set, only rows where that column is in sea_modes are processed.
    """
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    except Exception:
        df = pd.read_excel(file_path)

    print(f"读取: {len(df)} 行")

    if mode_col and mode_col in df.columns:
        mask = df[mode_col].isin(sea_modes)
        print(f"海运行 ({'/'.join(sea_modes)}): {mask.sum()}\n")
    else:
        mask = pd.Series([True] * len(df), index=df.index)

    dist_nm   = [None] * len(df)
    dist_km   = [None] * len(df)
    remarks   = [""] * len(df)
    ok = skipped = failed = 0

    for i, idx in enumerate(df[mask].index):
        orig_raw = str(df.at[idx, origin_col]).strip()
        dest_raw = str(df.at[idx, dest_col]).strip()
        label = f"[{i+1}/{mask.sum()}] {orig_raw} → {dest_raw}"

        orig_coords = resolve_port(orig_raw)
        dest_coords = resolve_port(dest_raw)

        if orig_coords is None or dest_coords is None:
            who = []
            if orig_coords is None: who.append(f"起运港'{orig_raw}'")
            if dest_coords is None: who.append(f"目的港'{dest_raw}'")
            remarks[idx] = "未知港口: " + ", ".join(who)
            print(f"{label}  ⚠ 未知: {', '.join(who)}")
            skipped += 1
            continue

        if abs(orig_coords[0] - dest_coords[0]) < 0.01 and \
           abs(orig_coords[1] - dest_coords[1]) < 0.01:
            remarks[idx] = "同港口，跳过"
            print(f"{label}  — 同港口，跳过")
            skipped += 1
            continue

        result = sea_distance(orig_raw, dest_raw)
        if result:
            dist_nm[idx] = result["distance_nm"]
            dist_km[idx] = result["distance_km"]
            print(f"{label}  {result['distance_nm']:,} 海里")
            ok += 1
        else:
            remarks[idx] = "路线计算失败"
            print(f"{label}  ✗ 路线计算失败")
            failed += 1

        time.sleep(0.01)

    df["海运距离(海里)"] = dist_nm
    df["海运距离(km)"]  = dist_km
    df["备注"]          = remarks

    out = file_path.replace(".xlsx", "_海运距离.xlsx")
    df.to_excel(out, index=False)
    print(f"\n完成: 成功 {ok} | 跳过 {skipped} | 失败 {failed}  →  {out}")


def list_ports() -> None:
    chinese = sorted(k for k in PORTS if any('一' <= c <= '鿿' for c in k))
    english = sorted(k for k in PORTS if k not in chinese)
    print("\n英文港口名:")
    for i in range(0, len(english), 3):
        print("  " + "  ".join(f"{p:<28}" for p in english[i:i+3]))
    if chinese:
        print("\n中文港口名:")
        print("  " + "  ".join(chinese))


# ─────────────────────────────────────────────────────────────────────────────
# 交互式 CLI
# ─────────────────────────────────────────────────────────────────────────────

def interactive():
    print("=" * 58)
    print("  航运距离查询工具  (离线，无需 API Key)")
    print("  命令: 'list' 查看所有港口  'excel' 处理Excel  'quit' 退出")
    print("=" * 58)
    while True:
        print()
        origin = input("起运港 (Origin): ").strip()
        if not origin or origin.lower() == "quit":
            break
        if origin.lower() == "list":
            list_ports()
            continue
        if origin.lower() == "excel":
            path      = input("Excel文件路径 [运输数据_三维汇总表_全新版.xlsx]: ").strip() \
                        or "运输数据_三维汇总表_全新版.xlsx"
            orig_col  = input("起运港列名 [起运港]: ").strip() or "起运港"
            dest_col  = input("目的港列名 [目的港]: ").strip() or "目的港"
            process_excel(path, origin_col=orig_col, dest_col=dest_col)
            continue
        destination = input("目的港 (Destination): ").strip()
        if not destination or destination.lower() == "quit":
            break
        search(origin, destination)


# ─────────────────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if len(sys.argv) == 3:
        search(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "excel":
        process_excel()
    elif len(sys.argv) == 2 and sys.argv[1] == "list":
        list_ports()
    else:
        interactive()
