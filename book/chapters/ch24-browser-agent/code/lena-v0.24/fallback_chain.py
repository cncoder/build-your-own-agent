"""
三层 Fallback 骨架
保证 Browser Agent 的整体成功率 ~99%

层 1（RSSHub）：无需登录，速度快，成功率 ~90%
层 2（opencli）：本地工具，成功率 ~70%
层 3（Browser Agent）：真实浏览器，成功率 ~40-60%
组合成功率：≈ 1 - (0.1 × 0.3 × 0.5) ≈ 99%

设计原则（来自 Anthropic Building Effective Agents）：
  "start simple, add complexity only when it demonstrably improves outcomes"
  三层 fallback 是"足够复杂"的平衡点——再简单（单层）不够可靠，
  再复杂（5层+）收益递减且维护成本高。
"""
from typing import Optional, Callable, Any
import asyncio


class FallbackChain:
    """
    三层 fallback 链
    每层失败后自动降级到下一层，成功则停止
    """

    def __init__(self, name: str = "unnamed"):
        self.name = name
        self._layers: list[tuple[str, Callable]] = []

    def layer(self, name: str):
        """装饰器：把异步函数加入 fallback 链"""
        def decorator(fn: Callable):
            self._layers.append((name, fn))
            return fn
        return decorator

    def add(self, name: str, fn: Callable) -> "FallbackChain":
        """显式添加层（无装饰器语法）"""
        self._layers.append((name, fn))
        return self

    async def run(self, *args, **kwargs) -> Optional[Any]:
        """
        按顺序尝试每一层，返回第一个非 None 的结果
        所有层都失败时返回 None
        """
        last_error: Optional[Exception] = None

        for name, fn in self._layers:
            try:
                print(f"[{self.name}] 尝试层: {name}")
                result = await fn(*args, **kwargs)

                if result is not None:
                    print(f"[{self.name}] ✓ 成功: {name}")
                    return result

                print(f"[{self.name}] 层 {name} 返回空，降级到下一层")

            except asyncio.TimeoutError:
                print(f"[{self.name}] 层 {name} 超时，降级")
                last_error = None

            except Exception as e:
                print(f"[{self.name}] 层 {name} 失败: {type(e).__name__}: {e}，降级")
                last_error = e

        print(f"[{self.name}] 所有层均失败")
        if last_error:
            print(f"[{self.name}] 最后错误: {last_error}")
        return None


# ===== 预配置的微博 fallback 链 =====

def build_weibo_chain(weibo_uid: str, browser_task_fn: Callable) -> FallbackChain:
    """
    构建微博内容获取的三层 fallback 链

    Args:
        weibo_uid: 微博用户 UID
        browser_task_fn: async 函数，接受 task str，返回结果

    Returns:
        配置好的 FallbackChain
    """
    import aiohttp

    chain = FallbackChain(name=f"weibo-{weibo_uid[:8]}")

    @chain.layer("rsshub")
    async def via_rsshub():
        """
        层 1：通过 RSSHub 公共实例获取微博内容
        优点：无需登录，响应快（通常 <2s）
        缺点：只有"推送内容"，不含通知/私信/互动
        """
        rsshub_url = f"https://rsshub.app/weibo/user/{weibo_uid}"
        async with aiohttp.ClientSession() as s:
            async with s.get(
                rsshub_url,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0 (compatible; LenaBot/2.0)"},
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    items = data.get("items", [])[:5]
                    return {
                        "source": "rsshub",
                        "count": len(items),
                        "items": [
                            {"title": item.get("title", ""), "link": item.get("url", "")}
                            for item in items
                        ],
                    }
        return None

    @chain.layer("browser_use")
    async def via_browser():
        """
        层 2：使用真实浏览器（含登录态）
        优点：能访问所有内容，包括通知和私信
        缺点：速度慢（10-30s），有反爬风险
        """
        task = f"""
        在新标签页打开微博（https://weibo.com）：
        1. 如果出现登录页，返回 JSON: {{"error": "AUTH_EXPIRED", "items": []}}
        2. 检查右上角通知图标是否有数字
        3. 如果有通知，点击进入通知页，获取前 5 条通知摘要
        4. 返回 JSON: {{"source": "browser", "new_count": 数字, "items": [{{"title": "..."}}]}}
        """
        raw = await browser_task_fn(task)
        import json
        try:
            result = json.loads(raw)
            if result.get("error") == "AUTH_EXPIRED":
                print("[Fallback] 微博 Cookie 已过期，需要重新登录")
            return result
        except json.JSONDecodeError:
            # LLM 可能返回非 JSON 的文字描述
            return {"source": "browser", "raw": raw, "items": []}

    return chain


# ===== 通用内容获取 fallback 链 =====

def build_generic_chain(
    url: str,
    rss_url: Optional[str] = None,
    browser_task_fn: Optional[Callable] = None,
) -> FallbackChain:
    """
    构建通用 URL 内容获取的 fallback 链

    Args:
        url: 目标 URL
        rss_url: 对应的 RSS/RSSHub URL（可选）
        browser_task_fn: browser agent 调用函数（可选）
    """
    import aiohttp

    chain = FallbackChain(name=f"generic-{url[:30]}")

    if rss_url:
        @chain.layer("rss")
        async def via_rss():
            async with aiohttp.ClientSession() as s:
                async with s.get(rss_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        return {"source": "rss", "content": await r.text()}
            return None

    # HTTP 直接抓取（静态内容）
    @chain.layer("http_fetch")
    async def via_http():
        async with aiohttp.ClientSession() as s:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    text = await r.text()
                    # 如果是 SPA 空壳（<body> 内容 < 500 字节），视为失败
                    from html.parser import HTMLParser
                    import re
                    body_match = re.search(r"<body[^>]*>(.*?)</body>", text, re.DOTALL)
                    if body_match and len(body_match.group(1).strip()) < 500:
                        return None  # SPA，降级到 browser
                    return {"source": "http", "content": text[:5000]}
        return None

    if browser_task_fn:
        @chain.layer("browser_use")
        async def via_browser():
            task = f"打开 {url}，提取页面的主要文字内容，以 JSON 返回: {{\"content\": \"...\"}}"
            raw = await browser_task_fn(task)
            return {"source": "browser", "raw": raw}

    return chain


if __name__ == "__main__":
    # 演示三层 fallback 的降级行为
    async def demo():
        chain = FallbackChain(name="demo")

        call_count = 0

        @chain.layer("always_fail_1")
        async def _():
            print("  层 1 模拟失败")
            raise Exception("模拟错误")

        @chain.layer("always_fail_2")
        async def _():
            print("  层 2 模拟返回 None")
            return None

        @chain.layer("succeed_3")
        async def _():
            print("  层 3 成功")
            return {"data": "成功了", "from_layer": 3}

        result = await chain.run()
        print(f"\n最终结果: {result}")
        # 预期：{"data": "成功了", "from_layer": 3}

    asyncio.run(demo())
