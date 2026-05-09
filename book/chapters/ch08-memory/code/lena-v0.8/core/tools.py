"""
core/tools.py — Tool definitions for lena-v0.8.

Memory types follow Claude Code memoryTypes.ts:14:
  user / feedback / project / reference
"""
from memory.memdir import MemDir


SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "把重要信息保存到长期记忆，跨会话可用。"
        "适用场景：用户表达了明确偏好、重要事实、需要跨会话记住的内容。"
        "不要保存：代码片段、临时任务状态、当前会话中的一次性上下文。"
        "四种类型：user=用户画像, feedback=工作指导, "
        "project=项目事实, reference=外部资源指针。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "记忆主题，简短描述性，如 'programming_language'",
            },
            "content": {
                "type": "string",
                "description": "要记住的内容，简洁明确，不超过 200 字",
            },
            "mem_type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": "记忆类型",
            },
        },
        "required": ["subject", "content"],
    },
}


def execute_tool(name: str, args: dict, memdir: MemDir) -> str:
    """Execute a tool call. Returns result string."""
    if name == "save_memory":
        mem_id = memdir.save(
            content=args["content"],
            subject=args["subject"],
            mem_type=args.get("mem_type", "user"),
        )
        return f"已保存记忆 {mem_id}（主题：{args['subject']}）"
    return f"未知工具: {name}"
