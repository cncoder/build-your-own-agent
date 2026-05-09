"""
core/agent.py — Lena v0.12

新增能力（相比 v0.11）：
- 启动时加载 skills/ 目录（load_skills_dir）
- 识别 /skill_name 命令（parse_slash_command）
- $ARGUMENTS 替换后注入 system prompt（Skill.expand）
- /skills 命令列出所有可用 skill

核心设计：Skills 的 SOP 正文只在触发时注入，不常驻 context（渐进式披露）。

运行时：AWS Bedrock Converse API（boto3）
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""
from __future__ import annotations

import os
from pathlib import Path

import boto3

from .skills import Skill, load_skills_dir, parse_slash_command


# ── 配置 ─────────────────────────────────────────────────────────────────────

BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")
MODEL_ID = os.getenv("BEDROCK_MODEL", "us.anthropic.claude-haiku-4-5")  # Skill 执行用 Haiku

# ── Mock 工具（无需真实服务即可演示）──────────────────────────────────

_TOOLS = {
    "get_weather": {
        "name": "get_weather",
        "description": "查询城市天气（演示版，返回 mock 数据）",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名"}},
            "required": ["city"],
        },
    },
    "generate_pdf": {
        "name": "generate_pdf",
        "description": "将内容转换为 PDF 文件（演示版，保存为 .md）",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["content", "filename"],
        },
    },
}


def _call_tool(name: str, inputs: dict) -> str:
    if name == "get_weather":
        city = inputs.get("city", "未知")
        return (
            f'{{"city":"{city}","temperature":22,"feels_like":20,'
            f'"description":"多云转晴","humidity":65,"wind":"3级东北风",'
            f'"forecast":"明日最高26°C，午后有阵雨可能"}}'
        )
    if name == "generate_pdf":
        out = Path("/tmp") / inputs.get("filename", "report.pdf").replace(".pdf", ".md")
        out.write_text(inputs.get("content", ""), encoding="utf-8")
        return f'{{"success":true,"path":"{out}","note":"演示：已保存为 Markdown"}}'
    return f'{{"error":"未知工具：{name}"}}'


# ── LenaAgent ──────────────────────────────────────────────────────

class LenaAgent:
    """
    Lena v0.12：支持动态 Skills 加载的 Agent。

    Skill 触发流程：
      用户输入 /weather 上海
        → parse_slash_command → ("weather", "上海")
        → skills["weather"].expand("上海")  ← $ARGUMENTS 替换
        → 注入 system prompt → LLM 调用
    """

    BASE_SYSTEM = "你是 Lena，一个友好的 AI 助手。简洁直接，结论先行。"

    def __init__(self, skills_dir: str | Path | None = None):
        self._client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

        if skills_dir is None:
            skills_dir = Path(__file__).parent.parent / "skills"
        self.skills: dict[str, Skill] = load_skills_dir(skills_dir)
        print(f"[skills] 已加载 {len(self.skills)} 个: {', '.join(f'/{k}' for k in self.skills)}")

        self._messages: list[dict] = []

    # ── 公共接口 ────────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        """处理用户输入，返回 Lena 的回复。"""
        cmd = parse_slash_command(user_input)
        if cmd:
            name, args = cmd
            if name == "skills":
                return self._format_skills_list()
            return self._run_skill(name, args)
        return self._llm_turn(user_input, system=self.BASE_SYSTEM)

    # ── Skill 执行 ──────────────────────────────────────────────────

    def _run_skill(self, skill_name: str, arguments: str) -> str:
        skill = self.skills.get(skill_name)
        if not skill:
            available = ", ".join(f"/{k}" for k in self.skills)
            return f"未找到 Skill: /{skill_name}\n可用: {available or '（暂无）'}"

        # SOP 正文注入（渐进式披露：仅触发时才加入 context）
        sop = skill.expand(arguments)
        system = f"{self.BASE_SYSTEM}\n\n---\n\n{sop}"
        print(f"[DEBUG] 触发 Skill: {skill_name} | 参数: {arguments!r}")
        print(f"[DEBUG] 注入 system prompt 追加 {len(sop.split())} 词")

        tools = [_TOOLS[t] for t in skill.allowed_tools if t in _TOOLS] or None
        return self._llm_turn(
            user_input=arguments or f"请执行 /{skill_name}",
            system=system,
            tools=tools,
        )

    def _format_skills_list(self) -> str:
        if not self.skills:
            return "当前没有可用 Skill。"
        lines = ["当前已加载的 Skill："]
        for skill in self.skills.values():
            hint = f" {skill.argument_hint}" if skill.argument_hint else ""
            lines.append(f"  /{skill.name}{hint}  — {skill.description}")
        return "\n".join(lines)

    # ── LLM 调用 ────────────────────────────────────────────────────

    def _llm_turn(self, user_input: str, system: str, tools: list[dict] | None = None) -> str:
        self._messages.append({"role": "user", "content": [{"text": user_input}]})
        return self._real_turn(system, tools)

    def _real_turn(self, system: str, tools: list[dict] | None) -> str:
        """真实 LLM 调用循环（含工具使用）。"""
        kwargs: dict = {
            "modelId": MODEL_ID,
            "system": [{"text": system}],
            "messages": self._messages,
            "inferenceConfig": {"maxTokens": 1024},
        }
        if tools:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": {"json": t["input_schema"]},
                        }
                    }
                    for t in tools
                ]
            }

        while True:
            resp = self._client.converse(**kwargs)
            stop_reason = resp.get("stopReason", "end_turn")
            msg = resp["output"]["message"]

            if stop_reason == "end_turn":
                text = " ".join(b["text"] for b in msg.get("content", []) if "text" in b)
                self._messages.append({"role": "assistant", "content": [{"text": text}]})
                return text or "（空响应）"

            if stop_reason == "tool_use":
                results = []
                for b in msg.get("content", []):
                    if "toolUse" in b:
                        tu = b["toolUse"]
                        result = _call_tool(tu["name"], tu["input"])
                        results.append({
                            "toolResult": {
                                "toolUseId": tu["toolUseId"],
                                "content": [{"text": result}],
                            }
                        })
                self._messages.append({"role": "assistant", "content": msg["content"]})
                self._messages.append({"role": "user", "content": results})
                kwargs["messages"] = self._messages
                continue

            break
        return "（LLM 未返回有效响应）"
