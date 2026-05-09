"""
PermissionGate: 权限门控与 Human-in-the-Loop
lena-v0.13 输入层安全组件

五种 Permission Mode 对应 Claude Code types/permissions.ts 的设计空间。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional


class PermissionMode(Enum):
    """五种 Permission Mode，覆盖安全 vs 自动化的核心权衡点。

    default      — 每次写操作弹框请求用户确认（推荐日常使用）
    accept_edits — 文件读写自动批准，其他操作仍需确认（适合编码密集场景）
    bypass       — 跳过所有权限检查（⚠ 极度危险，仅限受控测试）
    plan         — 只读自动批准，写操作全部拒绝（适合预览 / 审查阶段）
    auto         — AI 分类器动态判断（本章简化实现：等同 default）

    来源：CC types/permissions.ts EXTERNAL_PERMISSION_MODES
    """
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    BYPASS = "bypass"
    PLAN = "plan"
    AUTO = "auto"


@dataclass
class OperationRequest:
    """权限请求的载体，携带操作的全部上下文。"""
    tool_name: str          # 工具名称
    description: str        # 操作描述（展示给用户）
    is_write: bool          # 是否涉及写操作
    is_destructive: bool = False   # 是否不可逆（删除 / 发送 / 部署）
    from_external: bool = False    # 是否来自外部内容（prompt injection 触发点）


class PermissionGate:
    """权限门控：根据 Mode + 操作属性决定是否执行或请求确认。

    设计原则：
    - 来自外部内容的操作请求，无论 mode，都必须人工确认
    - 破坏性操作（is_destructive=True）即使在 accept_edits 下也需确认
    - 无 confirm_callback 时，默认拒绝（安全优先原则）
    """

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        confirm_callback: Optional[Callable[[OperationRequest], Awaitable[bool]]] = None,
    ):
        self.mode = mode
        self.confirm_callback = confirm_callback

    async def check(self, op: OperationRequest) -> bool:
        """权限决策入口。返回 True = 允许；False = 拒绝。"""

        # BYPASS：完全跳过所有检查（危险！仅测试用）
        if self.mode == PermissionMode.BYPASS:
            return True

        # PLAN：纯只读模式，任何写操作直接拒绝
        if self.mode == PermissionMode.PLAN:
            if op.is_write or op.is_destructive:
                print(f"[PLAN MODE] 拒绝写操作：{op.description}")
                return False
            return True

        # 来自外部内容的操作：无论 mode 如何，必须人工确认
        # 这是 prompt injection 防御的关键路径
        if op.from_external:
            return await self._ask(op)

        # ACCEPT_EDITS：非破坏性操作自动批准
        if self.mode == PermissionMode.ACCEPT_EDITS and not op.is_destructive:
            return True

        # DEFAULT / AUTO：写操作或破坏性操作需要确认
        if op.is_write or op.is_destructive:
            return await self._ask(op)

        # 只读操作：直接允许
        return True

    async def _ask(self, op: OperationRequest) -> bool:
        """调用外部确认回调；无回调时默认拒绝（安全优先）。"""
        if self.confirm_callback is None:
            print(f"[BLOCKED] 无确认回调，拒绝：{op.description}")
            return False
        return await self.confirm_callback(op)
