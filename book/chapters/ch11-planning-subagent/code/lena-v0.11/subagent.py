"""
Subagent Worker — 独立 ask() 调用链
对应 CC AgentTool.tsx:196 / forkSubagent.ts:60

核心设计：
- 每个 Worker 有独立 agent_id（对应 CC context.agentId）
- 继承父 system prompt（Fork 共享 prompt cache 的关键）
- 结果以 <task-notification> XML 回传
"""
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import boto3


@dataclass
class SubagentResult:
    agent_id: str          # 对应 CC context.agentId，全局唯一
    task: str
    content: str
    elapsed: float
    error: Optional[str] = None

    def to_xml(self) -> str:
        """
        模拟 CC <task-notification> XML 回传格式。
        CC 源码用 XML 而非 JSON 的原因：LLM 对 XML 标签的边界感知优于 JSON 块，
        在消息历史里更容易被 attention 机制正确归类。
        """
        status = "completed" if not self.error else "failed"
        body = self.content if not self.error else f"ERROR: {self.error}"
        return (
            f'<task-notification agent_id="{self.agent_id}" status="{status}">\n'
            f'{body}\n'
            f'</task-notification>'
        )


class SubagentWorker:
    """
    独立的子 agent 执行单元。

    Fork 继承设计（对应 forkSubagent.ts:60）：
    - 继承父 system_prompt（共享 Bedrock prompt cache）
    - 有独立 agent_id（TodoWrite 用此 key 隔离 todo 状态）
    - 独立的消息历史，不污染父 agent context
    """

    def __init__(
        self,
        task: str,
        prompt: str,
        parent_system_prompt: str,   # Fork 继承，共享 prompt cache
        model_id: str = "us.anthropic.claude-haiku-4-5",  # Worker 用轻量模型
        region: str = "us-west-2",
    ):
        # 全局唯一 ID，对应 CC context.agentId
        self.agent_id = f"sub-{uuid.uuid4().hex[:6]}"
        self.task = task
        self.prompt = prompt
        # 继承父 system prompt（byte-identical，触发 Bedrock prompt cache 命中）
        self.system_prompt = parent_system_prompt
        self.model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def run(self) -> SubagentResult:
        """独立 ask() 调用链——在独立 executor 里运行，不阻塞事件循环"""
        start = time.time()
        try:
            content = await asyncio.get_event_loop().run_in_executor(
                None, self._call_model
            )
            return SubagentResult(self.agent_id, self.task, content, time.time() - start)
        except Exception as e:
            return SubagentResult(
                self.agent_id, self.task, "", time.time() - start, error=str(e)
            )

    def _call_model(self) -> str:
        """同步 Bedrock Converse 调用（在 executor 线程里）"""
        response = self._client.converse(
            modelId=self.model_id,
            system=[{"text": self.system_prompt}],
            messages=[{"role": "user", "content": [{"text": self.prompt}]}],
            inferenceConfig={"maxTokens": 1500, "temperature": 0.3},
        )
        return response["output"]["message"]["content"][0]["text"]
