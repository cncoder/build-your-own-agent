"""
core/skills.py — Skills 加载与执行（Lena v0.12）

对应 CC loadSkillsDir.ts 核心逻辑的 Python 实现：
1. 扫描 skills/ 目录下所有 .md 文件
2. 解析 YAML frontmatter → Skill 对象（元数据层）
3. $ARGUMENTS 替换 → 注入 system prompt（触发层）

渐进式披露原理：
  Skill 在 load 时只加载元数据（name + description），
  调用 expand() 时才将完整 SOP 正文注入 system prompt。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str           # slash 命令名，如 "weather" → /weather
    description: str    # 元数据：常驻 context，约 20-50 tokens
    content: str        # SOP 正文：仅 expand() 时注入，100-500 tokens
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    argument_hint: str = ""   # UI 提示，如 "<城市名>"

    def expand(self, arguments: str) -> str:
        """将 $ARGUMENTS 替换为用户实际输入，返回注入 system prompt 的文本。"""
        return self.content.replace("$ARGUMENTS", arguments)

    def slash_command(self) -> str:
        return f"/{self.name}"


# ── 解析单个 Skill 文件 ─────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)


def _parse_skill_file(path: Path) -> Skill | None:
    """读取并解析一个 .md 文件，返回 Skill 或 None（格式不符时静默跳过）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None   # 没有 frontmatter，不是 Skill 文件

    try:
        fm: dict = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None

    body = m.group(2).strip()
    # 文件名兜底：frontmatter 没写 name 就用文件名
    name = fm.get("name") or path.stem.replace(" ", "-").lower()

    return Skill(
        name=name,
        description=fm.get("description", ""),
        content=body,
        allowed_tools=tuple(fm.get("allowed-tools") or []),
        argument_hint=fm.get("argument-hint", ""),
    )


# ── 目录扫描 ────────────────────────────────────────────────────────

def load_skills_dir(skills_dir: str | Path) -> dict[str, Skill]:
    """
    扫描目录（含子目录）下所有 .md 文件，返回 {name: Skill} 映射。

    同名 Skill 后者覆盖前者（对应 CC 的"项目级优先于全局级"逻辑）。
    """
    skills: dict[str, Skill] = {}
    base = Path(skills_dir)
    if not base.is_dir():
        return skills

    for md_file in sorted(base.rglob("*.md")):
        skill = _parse_skill_file(md_file)
        if skill:
            skills[skill.name] = skill

    return skills


# ── Slash 命令解析 ───────────────────────────────────────────────────

def parse_slash_command(user_input: str) -> tuple[str, str] | None:
    """
    解析 /skill_name [arguments] 格式的用户输入。

    返回 (skill_name, arguments)，或 None（不是 slash 命令）。

    示例：
        "/weather 上海"  →  ("weather", "上海")
        "/pdf-report"    →  ("pdf-report", "")
        "普通对话"       →  None
    """
    s = user_input.strip()
    if not s.startswith("/"):
        return None
    parts = s[1:].split(maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")
