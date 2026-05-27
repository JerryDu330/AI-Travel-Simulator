# Scope 3 Transport Calculator

Tools for computing transport distances across multiple modes for Scope 3 GHG emissions accounting (GHG Protocol categories 4, 6, and 9).

## Structure

```
scope3-calculator/
├── cat6-business-travel/       # Category 6 — Employee Business Travel
├── cat4-upstream-transport/    # Category 4 — Upstream Transportation & Distribution
└── cat4-9-sea-transport/       # Category 4 & 9 — Sea Freight
```

---

## cat6-business-travel — Inter-city Employee Travel (China)

Automates distance calculation for domestic business trips using an LLM to infer travel modes and AMap to fetch distances.

**Step 1 — Infer routes (`gen_routes.py`)**

Reads an Excel file with origin/destination city pairs and calls the Volcengine Doubao LLM to determine the travel mode (taxi, high-speed rail, short-distance bus) and station names.

```bash
python gen_routes.py --excel 出发地目的地路线统计报告.xlsx
```

Output: `ai_routes.json`

**Step 2 — Fill distances (`fill_amap.py`)**

Takes `ai_routes.json` and queries the AMap API for actual distances per leg.

```bash
python fill_amap.py
```

Output: `filled.json`

**Required environment variables:**
```
ARK_API_KEY=...
ARK_MODEL=...
AMAP_KEY=...
```

---

## cat4-upstream-transport — Truck Road Distances

Calculates road distances from origin cities to departure ports for upstream freight using the AMap driving API.

```bash
python distance_searcher.py
```

Reads `上游运输_处理后.xlsx` (columns: 货源地, 起运港), outputs `*_距离.xlsx`.

**Required environment variables:**
```
AMAP_KEY=...
```

---

## cat4-9-sea-transport — Sea Freight Distances

Two complementary tools for maritime routing:

### `sea_distance_searcher.py` — Offline Dijkstra routing

Uses a 7,462-node maritime graph (from boatcalculators.com `nav-data.min.js`) with forced waypoints for major chokepoints (Suez Canal, Panama Canal, Cape of Good Hope, Strait of Malacca, etc.).

Includes a comprehensive port alias table (~850 entries) to handle messy/abbreviated port names from real-world data.

```bash
# Interactive mode
python sea_distance_searcher.py

# Process Excel
python sea_distance_searcher.py --excel 运输数据_三维汇总表_全新版.xlsx
```

Place `nav-data.min.js` in the same directory (not tracked in git due to size).

### `pub151_distance.py` — US Navy PUB 151 distances

Uses authoritative US Defense Mapping Agency distances via 25 junction-point routing. Requires `PUB151_distances.json` and `junction_points.json` (included in repo).

```bash
python pub151_distance.py
```

Reads `运输数据_三维汇总表_全新版.xlsx` (sheet: 三维汇总表_按订单排序), filters VESSEL/SEA rows, outputs `*_PUB151.xlsx`.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
```

Create a `.env` file:
```
ARK_API_KEY=your_volcengine_ark_key
ARK_MODEL=your_doubao_model_id
AMAP_KEY=your_amap_web_service_key
```

## Scope 3 Category Reference

| Category | Description | Tools used |
|----------|-------------|------------|
| Cat 4 | Upstream Transportation & Distribution | `distance_searcher.py`, `sea_distance_searcher.py`, `pub151_distance.py` |
| Cat 6 | Business Travel | `gen_routes.py` + `fill_amap.py` |
| Cat 9 | Downstream Transportation & Distribution | `sea_distance_searcher.py`, `pub151_distance.py` |
