"""
串行 vs 并发加速比基准测试。

运行：
    cd lena-v0.7
    python3 demo/benchmark.py

预期输出（具体数值随机，加速比应在 3-5x）：
    串行总耗时：~6s
    并发总耗时：~1.8s
    加速比：~3.4x
"""
import asyncio
import random
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def mock_web_search(query: str) -> str:
    """模拟 web_search：随机 0.5~2.0s 延迟，等价于真实网络请求。"""
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)
    return f"[结果] {query!r} → 耗时 {delay:.2f}s，找到 3 条相关内容"


QUERIES = [
    "今天北京天气",
    "最新 AI 新闻",
    "BTC 当前价格",
    "明天北京→上海航班",
    "Python 3.13 新特性",
]


async def serial_search() -> float:
    """串行执行：一个完成再发下一个。"""
    t0 = time.perf_counter()
    for q in QUERIES:
        result = await mock_web_search(q)
        print(f"  串行完成：{result}")
    elapsed = time.perf_counter() - t0
    print(f"串行总耗时：{elapsed:.2f}s\n")
    return elapsed


async def concurrent_search() -> float:
    """并发执行：asyncio.gather 同时发出全部请求。"""
    t0 = time.perf_counter()
    # asyncio.gather：所有协程并发运行，等最慢的那个
    results = await asyncio.gather(*[mock_web_search(q) for q in QUERIES])
    elapsed = time.perf_counter() - t0
    for r in results:
        print(f"  并发完成：{r}")
    print(f"并发总耗时：{elapsed:.2f}s")
    return elapsed


async def main():
    # 固定随机种子，让两次测试的"延迟"分布相同（便于对比）
    random.seed(42)

    print("=" * 50)
    print("=== 串行执行（v0.6 行为）===")
    print("=" * 50)
    serial_t = await serial_search()

    # 重置种子，保证并发测试用相同的延迟值
    random.seed(42)

    print("=" * 50)
    print("=== 并发执行（v0.7 新能力）===")
    print("=" * 50)
    concurrent_t = await concurrent_search()

    speedup = serial_t / concurrent_t
    saving_pct = (1 - concurrent_t / serial_t) * 100

    print()
    print("=" * 50)
    print(f"加速比：{speedup:.1f}×")
    print(f"节省时间：{serial_t - concurrent_t:.2f}s ({saving_pct:.0f}%)")
    print("=" * 50)

    if speedup < 2.0:
        print()
        print("[警告] 加速比 < 2x，可能原因：")
        print("  1. 使用了同步 requests 库（会阻塞事件循环）→ 改用 aiohttp")
        print("  2. 在 Jupyter 里运行了 asyncio.run() → 改用 await main()")


if __name__ == "__main__":
    asyncio.run(main())
