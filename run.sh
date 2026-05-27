#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ── Python check ────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "错误: 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

# ── Virtual env ─────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "首次运行，正在创建虚拟环境..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# ── Dependencies ─────────────────────────────────────────────
pip install -r requirements.txt -q --disable-pip-version-check

# ── .env check ───────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  未找到 .env 文件。请复制 .env.example 并填写 API Key："
    echo "    cp .env.example .env"
    echo ""
fi

# ── Menu ─────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     Scope 3 Transport Calculator         ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Cat 6 — 商务出行                        ║"
echo "║    1. 推断出行路线  (gen_routes)          ║"
echo "║    2. 填充距离      (fill_amap)           ║"
echo "║                                          ║"
echo "║  Cat 4 — 上游运输                        ║"
echo "║    3. 卡车运输距离  (distance_searcher)   ║"
echo "║                                          ║"
echo "║  Cat 4/9 — 海运                          ║"
echo "║    4. 海运距离 — 离线图  (sea_dijkstra)  ║"
echo "║    5. 海运距离 — PUB 151 (pub151)        ║"
echo "║                                          ║"
echo "║    0. 退出                               ║"
echo "╚══════════════════════════════════════════╝"
echo ""
read -p "请选择 (0-5): " choice

case $choice in
    1)
        read -p "Excel 路径 [默认: 出发地目的地路线统计报告.xlsx]: " excel
        excel="${excel:-出发地目的地路线统计报告.xlsx}"
        python cat6-business-travel/gen_routes.py --excel "$excel"
        ;;
    2)
        python cat6-business-travel/fill_amap.py
        ;;
    3)
        python cat4-upstream-transport/distance_searcher.py
        ;;
    4)
        python cat4-9-sea-transport/sea_distance_searcher.py
        ;;
    5)
        python cat4-9-sea-transport/pub151_distance.py
        ;;
    0)
        echo "退出"
        exit 0
        ;;
    *)
        echo "无效选择，请输入 0-5"
        exit 1
        ;;
esac
