"""
SupervisorAgent：agent-as-tools 模式

每个专用 agent 被包装成一个工具（tool）。
SupervisorAgent 通过 LLM 推理做意图分类 + 路由。
用户只需要跟 SupervisorAgent 交互，不需要知道有多少个专用 agent。

架构参考：Agent Squad (2FastLabs/agent-squad) SupervisorAgent 模式

运行时：AWS Bedrock Converse API（boto3）
本书代码默认 Bedrock。OpenAI/Anthropic 直连映射见附录 D。
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import boto3


BEDROCK_REGION = os.getenv("AWS_REGION", "us-west-2")


class AgentHandler(Protocol):
    """专用 agent 的接口协议。"""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def handle(self, task: str) -> str: ...


class SupervisorAgent:
    """
    agent-as-tools 模式：每个专用 agent 是一个 tool。
    SupervisorAgent 负责意图分类 + 路由 + 响应汇总。

    使用示例：
        supervisor = SupervisorAgent(agents=[TradingAgent(), NewsAgent()])
        result = supervisor.handle("BTC 现在该买吗？")
    """

    def __init__(
        self,
        agents: list[AgentHandler],
        model: str = "us.anthropic.claude-sonnet-4-6",
        system_prompt: str | None = None,
    ):
        self.client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        self.agents: dict[str, AgentHandler] = {a.name: a for a in agents}
        self.model = model
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.bedrock_tools = self._build_bedrock_tools()

    def _default_system_prompt(self) -> str:
        agent_list = "\n".join(
            f"- {name}: {agent.description}"
            for name, agent in self.agents.items()
        )
        return f"""你是一个智能任务路由 agent。

可用的专用 agent：
{agent_list}

你的职责：
1. 理解用户意图
2. 委托给最合适的专用 agent（使用对应的 delegate 工具）
3. 汇总 agent 的返回结果，用清晰的方式回复用户
4. 如果任务跨多个专用 agent，依次委托，最后综合汇总

注意：始终通过工具调用来委托，不要自己臆造专用 agent 的答案。"""

    def _build_bedrock_tools(self) -> list[dict]:
        """Build Bedrock toolSpec list for delegate tools."""
        tools = []
        for name, agent in self.agents.items():
            tools.append(
                {
                    "toolSpec": {
                        "name": f"delegate_to_{name}",
                        "description": f"委托给 {name} agent 执行任务。{agent.description}",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {
                                    "task": {
                                        "type": "string",
                                        "description": "要委托的具体任务描述（越详细越好）",
                                    }
                                },
                                "required": ["task"],
                            }
                        },
                    }
                }
            )
        return tools

    def _dispatch(self, agent_name: str, task: str) -> str:
        """路由到专用 agent 并返回结果。"""
        if agent_name not in self.agents:
            return f"错误：找不到 agent '{agent_name}'"
        try:
            return self.agents[agent_name].handle(task)
        except Exception as exc:
            return f"agent '{agent_name}' 执行失败：{exc}"

    def handle(self, user_message: str, max_rounds: int = 10) -> str:
        """
        处理用户请求，自动路由到专用 agent。

        Args:
            user_message: 用户输入
            max_rounds: 最大工具调用轮次（防止无限循环）

        Returns:
            最终回复文本
        """
        messages: list[dict] = [{"role": "user", "content": [{"text": user_message}]}]

        for _ in range(max_rounds):
            resp = self.client.converse(
                modelId=self.model,
                system=[{"text": self.system_prompt}],
                toolConfig={"tools": self.bedrock_tools},
                messages=messages,
                inferenceConfig={"maxTokens": 4096},
            )

            stop_reason = resp.get("stopReason", "end_turn")
            msg = resp["output"]["message"]

            if stop_reason == "end_turn":
                # 提取文本回复
                for block in msg.get("content", []):
                    if "text" in block:
                        return block["text"]
                return ""

            if stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": msg["content"]})
                tool_results = []
                for block in msg.get("content", []):
                    if "toolUse" in block:
                        tu = block["toolUse"]
                        agent_name = tu["name"].replace("delegate_to_", "")
                        result = self._dispatch(agent_name, tu["input"]["task"])
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tu["toolUseId"],
                                "content": [{"text": result}],
                            }
                        })
                messages.append({"role": "user", "content": tool_results})

        return "超出最大路由轮次，请简化请求后重试。"
