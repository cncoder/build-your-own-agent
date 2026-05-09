"""
PromptGuard: 外部内容隔离与注入检测
lena-v0.13 输入层安全组件

来源参考：nanoClaw/security/prompt_guard.py（NFKC + 注入模式库）
         OpenClaw security/external-content.ts:56-58（随机边界 ID 设计）
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field


# ── 注入模式库（27 条）──────────────────────────────────────────────────────
# 覆盖主流攻击手法：指令覆盖、模式切换、标签注入、凭证窃取
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"forget\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?)",
    r"you\s+are\s+now\s+in\s+(admin|maintenance|debug|developer|god)\s+mode",
    r"new\s+(system\s+)?instruction[s]?\s*:",
    r"override\s+(system\s+)?(prompt|instruction|rule)",
    r"act\s+as\s+if\s+you\s+(are|were)",
    r"your\s+(true|real|actual|hidden)\s+(purpose|goal|instruction|directive)",
    r"(execute|run|perform)\s+(immediately|now|right\s+now)\s+without\s+(confirmation|asking)",
    r"do\s+not\s+(ask|tell|inform|notify)\s+the\s+user",
    r"the\s+user\s+(does\s+not\s+need\s+to\s+know|should\s+not\s+know)",
    r"this\s+is\s+(a\s+)?(test|drill|simulation)\s*[,;.]?\s*execute",
    r"maintenance\s+mode\s*(:|is\s+now\s+active)",
    r"<\s*/?system\s*>",           # 伪造 system 标签
    r"<\s*/?instruction[s]?\s*>",  # 伪造 instruction 标签
    r"\[\s*system\s*\]",           # 方括号变体
    r"\[\s*instruction[s]?\s*\]",
    r"###\s*(SYSTEM|INSTRUCTION)",  # Markdown 注入
    r"<\|im_start\|>",             # ChatML 注入
    r"<\|endofprompt\|>",          # GPT end-of-prompt token
    r"\[/INST\]",                  # Llama instruction boundary
    r"<\|im_end\|>",               # ChatML end token
    r"delete\s+all\s+(files?|emails?|records?|data|messages?)",
    r"send\s+(an?\s+)?email\s+.{0,50}(without|no)\s+(permission|confirmation)",
    r"(bypass|circumvent|evade)\s+(security|sandbox|restriction|filter|guard)",
    r"api\s+key\s*[=:]\s*['\"]?\w{10,}",   # 凭证窃取模式
    r"password\s*[=:]\s*['\"]?\S{4,}",
]

_compiled = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in INJECTION_PATTERNS]


@dataclass
class ScanResult:
    safe: bool
    matched_patterns: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    """NFKC 归一化：把 Unicode 变体字符折叠成标准形式。

    例：全角 'ｉｇｎｏｒｅ' → 'ignore'；西里尔 'і' → 'i'
    目的：让正则匹配不被 Unicode 同形字攻击绕过。
    """
    return unicodedata.normalize("NFKC", text)


def scan(text: str) -> ScanResult:
    """扫描文本，检测注入模式（先 NFKC 归一化）。

    返回 ScanResult，safe=False 表示检测到至少一个注入模式。
    """
    normalized = normalize(text)
    matched = []
    for i, pattern in enumerate(_compiled):
        if pattern.search(normalized):
            matched.append(INJECTION_PATTERNS[i])
    return ScanResult(safe=len(matched) == 0, matched_patterns=matched)


def wrap_external(content: str, source: str = "unknown") -> str:
    """用随机边界 ID 包裹不可信内容。

    每次调用生成一个新的 16 字符十六进制 ID（64-bit 熵）。
    攻击者无法预测 ID，因此无法构造有效的闭合标签逃逸。

    参数：
        content: 外部内容（网页 HTML、文件内容、API 返回等）
        source:  内容来源标注，便于调试
    """
    boundary_id = secrets.token_hex(8)
    return (
        f'<external id="{boundary_id}" trust="untrusted" source="{source}">\n'
        f"{content}\n"
        f'</external>\n'
        f'<!-- /boundary:{boundary_id} -->'
    )


def sanitize(content: str, source: str = "external") -> tuple[str, ScanResult]:
    """处理外部内容的标准入口。

    1. 扫描注入模式（NFKC + 正则）
    2. 用随机边界 ID 包裹（防边界伪造逃逸）

    返回 (wrapped_content, scan_result)
    调用方根据 scan_result.safe 决定是否触发 HITL 确认流程。
    """
    result = scan(content)
    wrapped = wrap_external(content, source=source)
    return wrapped, result
