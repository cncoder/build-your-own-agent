"""
任务三：查高铁票（只查询，不购买）

安全声明：
- 此模块只实现查询功能（query_trains）
- 购票功能（book_ticket）需要额外调用 confirm_booking()，
  且通过高风险审批门控保护

使用方式：
    python3 -m lena-v2.0.tasks.train_query --from 深圳北 --to 上海虹桥 --date 2026-05-06
"""
import asyncio
import json
import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_agent import LenaBrowserAgent

# 只查询，明确排除购买操作
QUERY_TASK = """
在新标签页打开 12306（https://kyfw.12306.cn/otn/leftTicket/init）：
1. 找到出发地输入框，输入"{origin}"，从下拉选项中选择"{origin}"
2. 找到目的地输入框，输入"{destination}"，从下拉选项中选择"{destination}"
3. 找到出发日期选择器，选择 {date}
4. 点击"查询"按钮
5. 等待查询结果加载（页面 URL 会变化，车次列表出现）
6. 从结果中筛选出所有 G 字头（高铁）车次
7. 每条车次提取：车次号、出发时间、到达时间、历时、二等座价格/票量状态
8. 返回 JSON 数组：
   [
     {{
       "train": "G820",
       "depart": "06:18",
       "arrive": "13:24",
       "duration": "7小时06分",
       "second_class_price": "¥894.5",
       "second_class_status": "有票"
     }}
   ]
重要约束：
- 不要点击"预订"按钮
- 不要填写乘客信息
- 不要进行任何支付操作
- 如果出现验证码，返回: {{"error": "CAPTCHA_REQUIRED"}}
- 如果查询结果为空，返回: []
"""


async def query_trains(
    origin: str,
    destination: str,
    date: str,
) -> list[dict]:
    """
    查询高铁票（只读操作）

    Args:
        origin: 出发站（如"深圳北"）
        destination: 到达站（如"上海虹桥"）
        date: 出发日期（格式 YYYY-MM-DD）

    Returns:
        车次列表，每条包含：train/depart/arrive/duration/second_class_price/second_class_status

    Raises:
        RuntimeError: CDP 未启动或 12306 访问失败
    """
    agent = LenaBrowserAgent(
        model="claude-sonnet-4-6",
        require_approval_for_risky=False,  # 查询操作不需要审批
    )

    task = QUERY_TASK.format(origin=origin, destination=destination, date=date)
    print(f"[高铁查询] {origin} → {destination}，日期：{date}")

    raw = await agent.run_task(task)

    # 解析结果
    try:
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        result = json.loads(raw)

        if isinstance(result, dict):
            if result.get("error") == "CAPTCHA_REQUIRED":
                print("[高铁查询] ⚠️  遇到验证码，无法自动处理")
                return []
            return [result]  # 单个对象包装为列表

        return result if isinstance(result, list) else []

    except json.JSONDecodeError:
        print(f"[高铁查询] 解析失败，原始输出: {raw[:300]}")
        return []


def format_train_result(trains: list[dict]) -> str:
    """格式化输出车次信息"""
    if not trains:
        return "未查到符合条件的车次"

    lines = [f"查到 {len(trains)} 个 G 字头车次：", ""]
    for t in trains:
        line = (
            f"  {t.get('train', '?'):6s}  "
            f"{t.get('depart', '?')} → {t.get('arrive', '?')}  "
            f"{t.get('duration', '?'):10s}  "
            f"二等座: {t.get('second_class_price', '?')}  "
            f"({t.get('second_class_status', '?')})"
        )
        lines.append(line)

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="查高铁票（只查询，不购买）")
    parser.add_argument("--from", dest="origin", default="深圳北", help="出发站")
    parser.add_argument("--to", dest="destination", default="上海虹桥", help="目的站")
    parser.add_argument(
        "--date",
        default=(datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
        help="出发日期（YYYY-MM-DD，默认明天）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f"高铁票查询（只读）")
    print(f"路线: {args.origin} → {args.destination}")
    print(f"日期: {args.date}")
    print("确保 CDP 已启动: ~/.claude/scripts/cdp-start.sh")
    print("=" * 60)

    trains = asyncio.run(query_trains(args.origin, args.destination, args.date))

    print()
    print(format_train_result(trains))

    if trains:
        print()
        print(f"完整数据（JSON）:")
        print(json.dumps(trains[:3], ensure_ascii=False, indent=2))

    # 预期输出示例（具体数字随日期变化）：
    # 查到 12 个 G 字头车次：
    #
    #   G820    06:18 → 13:24  7小时06分    二等座: ¥894.5  (有票)
    #   G100    08:00 → 15:12  7小时12分    二等座: ¥894.5  (有票)
    #   G98     09:30 → 16:38  7小时08分    二等座: ¥894.5  (候补)
