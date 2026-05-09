"""
content_hash_cache.py — 基于 sha256 content-hash 的缓存

从日报 TTS 断点续传设计中提炼（案例 14.2）：
- sha256(voice + text) → 缓存键
- 跨天有效，只要内容不变就命中
- 适用于任何"计算昂贵 + 结果确定性"的场景
"""

import hashlib
import json
from pathlib import Path
from datetime import datetime


class ContentHashCache:
    """通用 content-hash 缓存。value 可以是任意 JSON-serializable 对象。"""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, *parts: str) -> str:
        content = ":".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, *key_parts: str) -> dict | None:
        """查缓存，未命中返回 None"""
        path = self.cache_dir / (self._key(*key_parts) + ".json")
        if path.exists():
            return json.loads(path.read_text())
        return None

    def set(self, value: dict, *key_parts: str):
        """写缓存，附带时间戳"""
        path = self.cache_dir / (self._key(*key_parts) + ".json")
        path.write_text(json.dumps({
            "cached_at": datetime.now().isoformat(),
            "data": value
        }))

    def hit_rate_info(self) -> dict:
        """缓存统计（调试用）"""
        files = list(self.cache_dir.glob("*.json"))
        return {
            "cache_dir": str(self.cache_dir),
            "cached_items": len(files),
        }
