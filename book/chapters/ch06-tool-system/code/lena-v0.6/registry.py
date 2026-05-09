"""
registry.py — ToolRegistry：加工具不改核心

核心设计：
  @tool 装饰器自动从 Pydantic 模型提取 JSON Schema
  ToolRegistry 存储所有注册工具，提供统一的 schema 列表和执行入口

三标志设计（对应 Claude Code Tool.ts:362）：
  is_read_only    — True 表示工具只读，不修改外部状态
  is_destructive  — True 表示执行后不可逆（如 shell rm 命令）
  is_concurrency_safe — True 表示可与其他工具并发执行

maxResultSizeChars 设计（对应 toolResultStorage.ts:30）：
  None = 不限制（等效 Infinity，用于 read_file 防 Read 循环）
  正整数 = 超出后截断并添加提示

参考：
  R1 §2 Tool System  ~/docs/research/R1-claude-code-architecture.md
  R2 §2 表格 ToolRegistry 行  ~/docs/research/R2-openclaw-nanoclaw-comparison.md
"""

import functools
import inspect
import typing
from dataclasses import dataclass
from typing import Any, Callable, Optional, Type, get_type_hints

from pydantic import BaseModel


@dataclass
class ToolMeta:
    """工具的元数据 + 三标志 + 结果限制。"""
    name: str
    description: str
    input_model: Type[BaseModel]           # Pydantic 模型 → 自动生成 JSON Schema
    handler: Callable
    is_read_only: bool = True
    is_destructive: bool = False
    is_concurrency_safe: bool = True
    max_result_size_chars: Optional[int] = 8000  # None = Infinity（read_file 用）

    @property
    def json_schema(self) -> dict:
        """Pydantic v2 → JSON Schema（Anthropic tool_use 格式）。"""
        schema = self.input_model.model_json_schema()
        # Pydantic v2 生成的 schema 有 'title'，Anthropic 不需要
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    def truncate_result(self, result: str) -> str:
        """超过 max_result_size_chars 时截断并附加说明。"""
        if self.max_result_size_chars is None:
            return result  # read_file: Infinity，永不截断
        if len(result) <= self.max_result_size_chars:
            return result
        kept = result[: self.max_result_size_chars]
        dropped = len(result) - self.max_result_size_chars
        return (
            kept
            + f"\n\n[结果过长，已截断 {dropped} 字符。"
            + "完整内容已持久化到磁盘，请使用 read_file 工具分段读取。]"
        )


class ToolRegistry:
    """
    工具注册表：加工具不改核心代码。

    用法：
        registry = ToolRegistry()

        @registry.tool(description="读取文件内容", is_read_only=True)
        def read_file(input: ReadFileInput) -> str:
            ...

        # 之后核心代码只用这两个方法：
        schemas = registry.get_schemas()      # → 传给 LLM
        result = registry.execute("read_file", {"path": "a.txt"})
    """

    def __init__(self):
        self._tools: dict[str, ToolMeta] = {}

    def tool(
        self,
        description: str,
        is_read_only: bool = True,
        is_destructive: bool = False,
        is_concurrency_safe: bool = True,
        max_result_size_chars: Optional[int] = 8000,
    ):
        """
        @tool 装饰器工厂。

        装饰的函数必须接收一个 Pydantic BaseModel 参数（或 **kwargs）。
        装饰器自动：
          1. 从 Pydantic 模型生成 JSON Schema
          2. 注册到 self._tools
          3. 透传函数本身（不改变调用接口）
        """
        def decorator(fn: Callable) -> Callable:
            # 找到第一个 Pydantic 参数
            # 用 get_type_hints 解析 'from __future__ import annotations' 的字符串注解
            try:
                hints = get_type_hints(fn)
            except Exception:
                hints = {}
            sig = inspect.signature(fn)
            input_model: Optional[Type[BaseModel]] = None
            for param_name in sig.parameters:
                ann = hints.get(param_name, sig.parameters[param_name].annotation)
                if inspect.isclass(ann) and issubclass(ann, BaseModel):
                    input_model = ann
                    break

            if input_model is None:
                raise TypeError(
                    f"@tool 装饰的函数 '{fn.__name__}' "
                    "必须有一个 Pydantic BaseModel 参数"
                )

            meta = ToolMeta(
                name=fn.__name__,
                description=description,
                input_model=input_model,
                handler=fn,
                is_read_only=is_read_only,
                is_destructive=is_destructive,
                is_concurrency_safe=is_concurrency_safe,
                max_result_size_chars=max_result_size_chars,
            )
            self._tools[fn.__name__] = meta

            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)

            return wrapper

        return decorator

    def get_schemas(self) -> list[dict]:
        """返回所有工具的 JSON Schema 列表（传给 LLM）。"""
        return [meta.json_schema for meta in self._tools.values()]

    def execute(self, name: str, inputs: dict) -> str:
        """按名称执行工具，返回结果字符串（已应用 truncate_result）。"""
        meta = self._tools.get(name)
        if meta is None:
            return f"未知工具：{name}"
        try:
            # 用 Pydantic 模型验证输入（类型校验 + 默认值填充）
            validated = meta.input_model(**inputs)
            result = meta.handler(validated)
            return meta.truncate_result(str(result))
        except Exception as e:
            return f"工具执行出错：{e}"

    def list_tools(self) -> list[dict]:
        """返回工具的调试信息（名称 + 三标志）。"""
        return [
            {
                "name": meta.name,
                "description": meta.description,
                "is_read_only": meta.is_read_only,
                "is_destructive": meta.is_destructive,
                "is_concurrency_safe": meta.is_concurrency_safe,
                "max_result_size_chars": meta.max_result_size_chars,
            }
            for meta in self._tools.values()
        ]


# 全局注册表（tools.py 导入并使用）
registry = ToolRegistry()
