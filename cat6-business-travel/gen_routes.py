#!/usr/bin/env python3
"""
读取 Excel 城市对，100行一批丢给豆包，返回路线结构 JSON 并保存。

用法:
  python gen_routes.py
  python gen_routes.py --excel 出发地目的地路线统计报告.xlsx --output ai_routes.json --batch 100
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
from openai import OpenAI


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

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
PROMPT_FILE  = Path("prompt_fin")


def load_prompt() -> str:
    if not PROMPT_FILE.exists():
        sys.exit(f"找不到 {PROMPT_FILE}")
    return PROMPT_FILE.read_text("utf-8").strip()


def extract_json(text: str) -> list[dict]:
    """从模型响应中提取 JSON 数组，容忍前后有多余文字。"""
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return []


def call_doubao(client: OpenAI, model: str, system: str, rows: list[dict]) -> list[dict]:
    lines = ["出发地,目的地,数量"]
    for r in rows:
        lines.append(f"{r['origin']},{r['destination']},{r['count']}")
    user_msg = "\n".join(lines)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"  [API错误] {e}", file=sys.stderr)
        return []

    parsed = extract_json(raw)
    if not parsed:
        print(f"  [警告] JSON解析失败，原始:\n{raw[:400]}", file=sys.stderr)
        return []
    filtered = [r for r in parsed if r.get("has_origin_station")]
    if len(filtered) < len(parsed):
        print(f"  [过滤] 丢弃 {len(parsed) - len(filtered)} 条空字段记录", file=sys.stderr)
    return filtered


def run(excel_path: str, output_path: str, batch_size: int, delay: float) -> None:
    api_key = os.environ.get("ARK_API_KEY")
    model   = os.environ.get("ARK_MODEL")
    if not api_key or not model:
        sys.exit("错误：.env 缺少 ARK_API_KEY 或 ARK_MODEL")

    client = OpenAI(api_key=api_key, base_url=ARK_BASE_URL)
    system = load_prompt()

    df = pd.read_excel(excel_path)
    rows = [
        {"origin":      str(r["出发地"]).strip(),
         "destination": str(r["目的地"]).strip(),
         "count":       int(r.get("数量", 1))}
        for _, r in df.iterrows()
    ]
    total = len(rows)
    print(f"读入 {total} 行，每批 {batch_size}，共 {-(-total // batch_size)} 批\n")

    # 断点续跑
    out_path = Path(output_path)
    results: list[dict] = []
    done_keys: set[tuple] = set()
    if out_path.exists():
        try:
            results = json.loads(out_path.read_text("utf-8"))
            done_keys = {(r.get("origin",""), r.get("destination","")) for r in results}
            print(f"续跑：已有 {len(results)} 条，跳过已完成\n")
        except Exception:
            results = []

    batches = [rows[i:i + batch_size] for i in range(0, total, batch_size)]

    for bi, batch in enumerate(batches, 1):
        todo = [r for r in batch if (r["origin"], r["destination"]) not in done_keys]
        if not todo:
            print(f"[批次 {bi}/{len(batches)}] 已完成，跳过")
            continue

        print(f"[批次 {bi}/{len(batches)}] {len(todo)} 条  "
              f"{todo[0]['origin']}…{todo[-1]['origin']}", end="  ", flush=True)

        parsed = call_doubao(client, model, system, todo)

        # 补充 count（AI 可能未带）
        count_map = {(r["origin"], r["destination"]): r["count"] for r in todo}
        for item in parsed:
            key = (item.get("origin",""), item.get("destination",""))
            item.setdefault("count", count_map.get(key, 1))

        if parsed:
            results.extend(parsed)
            done_keys.update((r.get("origin",""), r.get("destination","")) for r in parsed)
            print(f"✓ {len(parsed)} 条")
        else:
            print("✗ 本批失败")

        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), "utf-8")

        if bi < len(batches):
            time.sleep(delay)

    print(f"\n✓ 完成，共 {len(results)} 条 → {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="豆包批量路线结构生成器")
    parser.add_argument("--excel",  default="出发地目的地路线统计报告.xlsx")
    parser.add_argument("--output", default="ai_routes.json")
    parser.add_argument("--batch",  type=int,   default=20)
    parser.add_argument("--delay",  type=float, default=1.0)
    args = parser.parse_args()
    run(args.excel, args.output, args.batch, args.delay)


if __name__ == "__main__":
    main()
