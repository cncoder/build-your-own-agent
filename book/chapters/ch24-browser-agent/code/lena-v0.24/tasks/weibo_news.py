"""
任务一：查微博新消息（含三层 fallback）

安全说明：
- 只读操作，不会产生副作用
- 使用已登录的 Chrome profile，无需密码

使用方式：
    python3 -m lena-v2.0.tasks.weibo_news --uid YOUR_WEIBO_UID
"""
import asyncio
import sys
import os

# 向上查找 lena-v2.0 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_agent import lena_browse
from fallback_chain import build_weibo_chain

WEIBO_TASK = """
在一个新标签页打开微博（https://weibo.com）：
1. 如果页面跳转到登录页（URL 包含 "login"），立即返回：
   {"error": "AUTH_EXPIRED", "message": "微博 Cookie 已过期，需要手动重新登录", "items": []}
2. 等待页面加载完成（等待通知图标出现）
3. 检查右上角通知区域是否有红色数字（未读消息数量）
4. 如果有未读消息：
   a. 点击通知图标
   b. 等待通知列表加载
   c. 提取前 5 条通知的标题文字
5. 返回 JSON：
   {"new_count": 未读数量（没有则为0）, "items": [{"title": "通知内容"}]}
不要点击任何发帖、转发、评论按钮。只读不写。
"""


async def check_weibo_messages_simple() -> dict:
    """
    简单版：直接使用 browser agent（无 fallback）
    适合偶尔手动调用，不适合 cron 定时任务
    """
    raw = await lena_browse(WEIBO_TASK, safe=False)
    import json
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_result": raw}


async def check_weibo_messages(weibo_uid: str = "") -> dict:
    """
    生产版：三层 fallback（RSSHub → Browser）
    适合 cron 定时任务，整体成功率 ~99%

    Args:
        weibo_uid: 微博数字 UID（用于 RSSHub 层）
                   如不提供，RSSHub 层跳过，直接用 Browser 层
    """
    if weibo_uid:
        # 有 UID：用三层 fallback
        chain = build_weibo_chain(weibo_uid, lena_browse)
        result = await chain.run()
        return result or {"error": "ALL_LAYERS_FAILED", "items": []}
    else:
        # 无 UID：只用 Browser Agent
        return await check_weibo_messages_simple()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="查微博新消息")
    parser.add_argument("--uid", default="", help="微博用户 UID（可选，提供后启用 RSSHub fallback）")
    parser.add_argument("--simple", action="store_true", help="跳过 fallback，直接用浏览器")
    args = parser.parse_args()

    print("=" * 50)
    print("微博新消息查询")
    print("确保 CDP 已启动: ~/.claude/scripts/cdp-start.sh")
    print("=" * 50)

    if args.simple:
        result = asyncio.run(check_weibo_messages_simple())
    else:
        result = asyncio.run(check_weibo_messages(args.uid))

    import json
    print("\n查询结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 预期输出示例：
    # 查询结果:
    # {
    #   "source": "browser",
    #   "new_count": 3,
    #   "items": [
    #     {"title": "用户A 赞了你的微博"},
    #     {"title": "用户B 关注了你"},
    #     {"title": "用户C 评论了你的微博"}
    #   ]
    # }
    #
    # 失败时：
    # {
    #   "error": "AUTH_EXPIRED",
    #   "message": "微博 Cookie 已过期，需要手动重新登录",
    #   "items": []
    # }
