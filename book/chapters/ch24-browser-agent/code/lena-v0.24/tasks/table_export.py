"""
任务二：表格导出 CSV

Browser agent 找到页面上的数据表格，提取数据，写入 CSV 文件。

使用方式：
    python3 -m lena-v2.0.tasks.table_export --url URL --output /tmp/out.csv
"""
import asyncio
import csv
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_agent import LenaBrowserAgent

TASK_TEMPLATE = """
在新标签页打开 {url}：
1. 找到页面的主要数据表格（不是导航栏、不是边栏广告，是内容数据表格）
2. 读取表格的表头（列名）
3. 读取所有数据行的数据（最多 200 行）
4. 如果有多个表格，选数据量最大的那个
5. 以 JSON 格式返回，格式必须严格如下：
   {{
     "headers": ["列名1", "列名2", ...],
     "rows": [
       ["值1", "值2", ...],
       ["值1", "值2", ...]
     ],
     "total_rows": 总行数（含未显示的，如果分页的话估算）
   }}
注意：
- 如果某个单元格内容过长，截取前 200 字符
- 如果遇到合并单元格，展开为独立行
- 不要点击分页，只取当前可见的数据
"""


async def export_table_to_csv(
    url: str,
    output_path: str = "/tmp/table_export.csv",
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    从指定页面提取表格数据并导出为 CSV

    Args:
        url: 目标页面 URL
        output_path: CSV 输出路径
        model: 使用的 LLM 模型

    Returns:
        {"rows": 导出行数, "columns": 列数, "path": 文件路径}
    """
    agent = LenaBrowserAgent(model=model, require_approval_for_risky=False)

    print(f"[表格导出] 目标: {url}")
    print(f"[表格导出] 输出: {output_path}")

    raw = await agent.run_task(TASK_TEMPLATE.format(url=url))

    # 解析 LLM 返回的 JSON
    try:
        # LLM 有时会在 JSON 外面包一层 markdown 代码块
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[表格导出] JSON 解析失败: {e}")
        print(f"[表格导出] LLM 原始输出: {raw[:500]}")
        return {"error": "JSON_PARSE_FAILED", "raw": raw[:200]}

    headers = data.get("headers", [])
    rows = data.get("rows", [])

    if not headers:
        return {"error": "NO_HEADERS_FOUND"}

    # 写入 CSV
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig 兼容 Excel
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    result = {
        "rows": len(rows),
        "columns": len(headers),
        "path": output_path,
        "headers": headers[:5],  # 预览前 5 列
    }
    print(f"[表格导出] ✓ 导出完成: {len(rows)} 行 × {len(headers)} 列 → {output_path}")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="表格导出 CSV")
    parser.add_argument(
        "--url",
        default="https://datatables.net/examples/basic_init/",
        help="目标页面 URL",
    )
    parser.add_argument("--output", default="/tmp/table_export.csv", help="CSV 输出路径")
    args = parser.parse_args()

    result = asyncio.run(export_table_to_csv(args.url, args.output))
    print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

    # 展示前 3 行
    if "error" not in result:
        with open(result["path"]) as f:
            lines = f.readlines()
        print(f"\nCSV 预览（前 4 行）:")
        for line in lines[:4]:
            print(f"  {line.rstrip()}")
