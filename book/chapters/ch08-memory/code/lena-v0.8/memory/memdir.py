"""
memory/memdir.py — File-system long-term memory for lena-v0.8

Design inspired by Claude Code's memdir/memdir.ts:
  - ENTRYPOINT_NAME = 'MEMORY.md'  (memdir.ts:34)
  - MAX_ENTRYPOINT_LINES = 200      (memdir.ts:35)
  - Memory types: user/feedback/project/reference (memoryTypes.ts:14-21)
  - MAX_MEMORY_FILES = 200          (memoryScan.ts:22)

One .md file per memory item, YAML frontmatter + body.
MEMORY.md is a table-of-contents index (fast scan at session startup).
"""
import yaml
import uuid
from datetime import datetime
from pathlib import Path

MEMORY_TYPES = ("user", "feedback", "project", "reference")


class MemDir:
    """
    File-system long-term memory.

    Layout:
      ~/.lena/projects/<slug>/
        MEMORY.md                    ← index (MAX_ENTRYPOINT_LINES lines)
        memory/
          mem_<timestamp>_<hex>.md   ← individual memory files
    """

    ENTRYPOINT_NAME = "MEMORY.md"
    MAX_ENTRYPOINT_LINES = 200   # matches CC memdir.ts:35
    MAX_MEMORY_FILES = 200       # matches CC memoryScan.ts:22

    def __init__(self, project_slug: str = "lena"):
        self.base = (
            Path("~/.lena/projects").expanduser() / project_slug / "memory"
        )
        self.base.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base.parent / self.ENTRYPOINT_NAME

    def save(
        self,
        content: str,
        subject: str,
        mem_type: str = "user",
        confidence: float = 0.9,
        max_chars: int = 2000,   # truncation guard against context pollution
    ) -> str:
        """Save a memory. Returns the memory ID."""
        assert mem_type in MEMORY_TYPES, f"mem_type must be one of {MEMORY_TYPES}"

        # Truncation guard (matches CC memdir.ts content size protection)
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...[truncated]"

        mem_id = (
            f"mem_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        frontmatter = {
            "id": mem_id,
            "type": mem_type,
            "subject": subject,
            "description": subject,  # CC memdir uses `description` in manifest
            "created": datetime.utcnow().isoformat(),
            "confidence": confidence,
        }
        mem_file = self.base / f"{mem_id}.md"
        mem_file.write_text(
            f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n\n{content}",
            encoding="utf-8",
        )
        self._update_index(mem_id, subject, mem_type)
        return mem_id

    def _update_index(self, mem_id: str, subject: str, mem_type: str) -> None:
        """Append a row to MEMORY.md. Enforces MAX_ENTRYPOINT_LINES."""
        line = f"| `{mem_id}.md` | {mem_type} | {subject} |\n"

        if not self.index_path.exists():
            header = (
                "# MEMORY.md — Long-term Memory Index\n\n"
                "| 文件 | 类型 | 主题 |\n"
                "|------|------|------|\n"
            )
            self.index_path.write_text(header + line, encoding="utf-8")
        else:
            lines = self.index_path.read_text(encoding="utf-8").splitlines()
            if len(lines) < self.MAX_ENTRYPOINT_LINES:
                with open(self.index_path, "a", encoding="utf-8") as f:
                    f.write(line)
            # If at cap: silently drop new index entry (content file still saved)

    def load_all(self) -> list[dict]:
        """Load all memory files. Skips malformed files gracefully."""
        memories = []
        files = sorted(self.base.glob("mem_*.md"))[: self.MAX_MEMORY_FILES]
        for md_file in files:
            try:
                text = md_file.read_text(encoding="utf-8")
                parts = text.split("---", 2)
                fm = yaml.safe_load(parts[1])
                memories.append({**fm, "content": parts[2].strip()})
            except Exception:
                continue  # corrupt file — skip, don't crash
        return memories

    def load_index(self) -> str:
        """Read MEMORY.md index (fast scan for session startup)."""
        if not self.index_path.exists():
            return "（还没有长期记忆）"
        raw = self.index_path.read_text(encoding="utf-8")
        # Enforce byte cap similar to CC MAX_ENTRYPOINT_BYTES = 25_000
        if len(raw.encode("utf-8")) > 25_000:
            raw = raw[:25_000] + "\n> WARNING: MEMORY.md truncated at 25KB"
        return raw

    def format_for_prompt(self) -> str:
        """Render memories as a text block for system prompt injection."""
        memories = self.load_all()
        if not memories:
            return ""
        lines = ["## 已知信息（长期记忆）\n"]
        for m in memories:
            tag = f"[{m.get('type', '?')}]"
            subj = m.get("subject", "?")
            body = m.get("content", "")
            lines.append(f"- {tag} **{subj}**: {body}")
        return "\n".join(lines)

    def delete(self, mem_id: str) -> bool:
        """Delete a memory file. Returns True if deleted."""
        mem_file = self.base / f"{mem_id}.md"
        if mem_file.exists():
            mem_file.unlink()
            return True
        return False
