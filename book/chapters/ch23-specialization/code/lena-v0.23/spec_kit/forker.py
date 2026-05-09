"""
forker.py：lena-spec fork 命令实现

功能：从现有 Lena agent 配置派生新专用 agent。
技术基础：forkSubagent.ts:60 继承父 agent 的 renderedSystemPrompt。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def fork_agent(
    name: str,
    source_dir: Path,
    tools: list[str] | None = None,
    extra_prompt: str = "",
    output_dir: Path | None = None,
) -> Path:
    """
    从现有 agent 派生新专用 agent。

    继承逻辑（对应 forkSubagent.ts:60）：
    - 继承父 agent 的 system prompt（安全规则、铁律自动继承）
    - 叠加 extra_prompt（角色差异）
    - 裁剪工具集（只保留 tools 里指定的）

    Args:
        name: 新 agent 名称
        source_dir: 源 agent 目录（如 ~/.openclaw/agents/main）
        tools: 保留的工具列表（None = 继承全部）
        extra_prompt: 追加到 system prompt 末尾的专用内容
        output_dir: 输出目录

    Returns:
        生成的 agent 目录路径
    """
    if output_dir is None:
        output_dir = Path(f"agents/{name}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 继承父 agent 的 system prompt
    parent_prompt = ""
    parent_prompt_path = source_dir / "system_prompt.md"
    if parent_prompt_path.exists():
        parent_prompt = parent_prompt_path.read_text(encoding="utf-8")

    # 叠加专用 prompt（对应 forkSubagent.ts:60 的 renderedSystemPrompt 继承）
    forked_prompt = parent_prompt
    if extra_prompt:
        forked_prompt += f"\n\n## 专用扩展（{name}）\n\n{extra_prompt}"

    (output_dir / "system_prompt.md").write_text(forked_prompt, encoding="utf-8")

    # 继承父 agent 的工具集，然后裁剪
    parent_tools_path = source_dir / "tool_profile.json"
    if parent_tools_path.exists():
        parent_config = json.loads(parent_tools_path.read_text(encoding="utf-8"))
        all_tools = parent_config.get("tools", [])
    else:
        all_tools = []

    if tools is not None:
        selected_tools = [t for t in tools if t in all_tools or not all_tools]
    else:
        selected_tools = all_tools

    (output_dir / "tool_profile.json").write_text(
        json.dumps({"forked_from": str(source_dir), "tools": selected_tools}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 继承 skills 目录
    parent_skills = source_dir / "skills"
    forked_skills = output_dir / "skills"
    if parent_skills.exists():
        if forked_skills.exists():
            shutil.rmtree(forked_skills)
        shutil.copytree(parent_skills, forked_skills)
    else:
        forked_skills.mkdir(exist_ok=True)

    # config
    config = {
        "agent_name": name,
        "forked_from": str(source_dir),
        "model": "us.anthropic.claude-sonnet-4-6",
        "max_tokens": 4096,
    }
    (output_dir / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_dir
