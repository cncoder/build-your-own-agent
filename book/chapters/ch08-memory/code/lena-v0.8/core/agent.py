"""
core/agent.py — Lena v0.8 with two-layer memory.

Short-term: SQLite session history (MemoryStore)
Long-term:  file-system facts + preferences (MemDir)
Auto-load:  CLAUDE.md-like injection at session start (_build_system_prompt)
"""
import uuid
from memory.store import MemoryStore
from memory.memdir import MemDir
from core.llm import call_llm
from core.tools import SAVE_MEMORY_TOOL, execute_tool


class LenaAgent:
    """Lena v0.8 — cross-session memory via SQLite + file-system MemDir."""

    def __init__(self, session_id: str | None = None):
        self.store = MemoryStore()
        self.memdir = MemDir(project_slug="lena")
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self.store.create_session(self.session_id)

    def _build_system_prompt(self) -> str:
        """
        Build system prompt with long-term memory injected.

        CLAUDE.md-like pattern: read memory files at session start,
        inject into system prompt so the model 'knows' user preferences
        without being told again each turn.

        Recitation technique (Manus Context Engineering 2025):
        Append memory at the END of system prompt to counter
        lost-in-the-middle attention drift.
        """
        base = (
            "你是 Lena，一个通用 AI 助手。你能使用工具完成任务。\n"
            "当用户告诉你关于他们的偏好、身份或重要事实时，"
            "使用 save_memory 工具把它保存下来。"
        )
        long_term = self.memdir.format_for_prompt()
        if not long_term:
            return base

        # Recitation: append at end for stronger attention signal
        return f"{base}\n\n{long_term}\n\n<!-- 记忆重申 -->\n{long_term}"

    def chat(self, user_input: str) -> str:
        """One turn: load history → call LLM → handle tools → persist."""
        # 1. Load session history (short-term memory)
        messages = self.store.load_messages(self.session_id)
        messages.append({"role": "user", "content": [{"text": user_input}]})

        # 2. LLM call with save_memory tool available
        response = call_llm(
            messages=messages,
            system=self._build_system_prompt(),
            tools=[SAVE_MEMORY_TOOL],
        )

        # 3. Handle tool calls (agent may save a memory)
        final_text = self._handle_tool_use(response, messages)

        # 4. Persist this turn to SQLite
        self.store.append_message(self.session_id, "user", user_input)
        self.store.append_message(self.session_id, "assistant", final_text)

        return final_text

    def _handle_tool_use(self, response: dict, messages: list) -> str:
        """If LLM called a tool, execute it and get final text response."""
        if response.get("stop_reason") != "tool_use":
            # No tool call — extract text directly
            for block in response["content"]:
                if block["type"] == "text":
                    return block["text"]
            return ""

        # Execute each tool call
        # Reconstruct assistant message in Bedrock format before appending
        assistant_content: list[dict] = []
        tool_results: list[dict] = []
        for block in response["content"]:
            if block["type"] == "text":
                assistant_content.append({"text": block["text"]})
            elif block["type"] == "tool_use":
                assistant_content.append({
                    "toolUse": {
                        "toolUseId": block["id"],
                        "name": block["name"],
                        "input": block["input"],
                    }
                })
                result = execute_tool(block["name"], block["input"], self.memdir)
                tool_results.append({
                    "toolResult": {
                        "toolUseId": block["id"],
                        "content": [{"text": result}],
                    }
                })

        # Append assistant's tool-use turn + tool results, then get final reply
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})

        final = call_llm(
            messages=messages,
            system=self._build_system_prompt(),
        )
        for block in final["content"]:
            if block["type"] == "text":
                return block["text"]
        return ""
