"""
Orchestrator — 任务规划 + 并发分发 + 汇总
对应 CC Orchestrator-Worker 模式（Anthropic engineering blog, 2026-04-08）

流程：
  plan()       — LLM 分析任务，决定拆几件、怎么拆
  dispatch()   — asyncio.gather 并发启动 N 个 Worker
  aggregate()  — 汇总所有 <task-notification> XML
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

import boto3

from subagent import SubagentWorker, SubagentResult
from prompts import make_research_prompt, ORCHESTRATOR_SYSTEM_PROMPT


@dataclass
class TaskPlan:
    original_task: str
    subtasks: list[dict]         # [{"id": "1", "task": "...", "target": "..."}]
    can_parallelize: bool
    reason: str = ""


class Orchestrator:
    """
    Orchestrator（大脑）：负责规划和调度，不直接执行任务内容。

    模型分层（对应 CC 内置 agent 设计）：
    - Orchestrator 用较强的模型（Sonnet）做规划决策
    - Worker 用轻量模型（Haiku）做执行，节省成本

    成本分析：
    - Sonnet 只跑一次规划 + 一次汇总（约 800 + 2000 token）
    - Haiku 跑 N 个 Worker（每个约 1500 token），但并发不叠加时间
    """

    def __init__(
        self,
        orchestrator_model: str = "us.anthropic.claude-sonnet-4-6",
        worker_model: str = "us.anthropic.claude-haiku-4-5",
        region: str = "us-west-2",
        on_worker_start: Optional[Callable[[str, str], None]] = None,
        on_worker_done: Optional[Callable[[str, float, Optional[str]], None]] = None,
    ):
        self.orchestrator_model = orchestrator_model
        self.worker_model = worker_model
        self.region = region
        self.on_worker_start = on_worker_start
        self.on_worker_done = on_worker_done
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def execute(self, user_task: str) -> str:
        """完整 Orchestrator 流程：plan → dispatch → aggregate"""
        plan = await self._plan(user_task)

        if not plan.can_parallelize or len(plan.subtasks) <= 1:
            # 简单任务不需要 Worker，Orchestrator 直接回答
            return await self._execute_single(user_task)

        results = await self._dispatch_workers(plan)
        return await self._aggregate(user_task, results)

    # ── Phase 1: Plan ────────────────────────────────────────────────────────

    async def _plan(self, task: str) -> TaskPlan:
        """让 LLM 分析任务，决定如何拆分"""
        raw = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.converse(
                modelId=self.orchestrator_model,
                system=[{"text": ORCHESTRATOR_SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": f"请分析并规划这个任务：{task}"}]}],
                inferenceConfig={"maxTokens": 600, "temperature": 0.1},
            )["output"]["message"]["content"][0]["text"]
        )

        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return TaskPlan(task, [{"id": "1", "task": task, "target": ""}], False)

        data = json.loads(m.group())
        return TaskPlan(
            original_task=task,
            subtasks=data.get("subtasks", []),
            can_parallelize=data.get("can_parallelize", False),
            reason=data.get("reason", ""),
        )

    # ── Phase 2: Dispatch ─────────────────────────────────────────────────────

    async def _dispatch_workers(self, plan: TaskPlan) -> list[SubagentResult]:
        """
        并发派发 Workers。
        asyncio.gather 是关键：N 个 Worker 同时启动，总耗时 ≈ 最慢 Worker 耗时。

        Fork 继承：每个 Worker 传入 ORCHESTRATOR_SYSTEM_PROMPT 作为 parent_system_prompt，
        对应 forkSubagent.ts:60 的 renderedSystemPrompt 继承——相同的 system prompt 字节
        让 Bedrock prompt cache 能命中，后两个 Worker 节省约 90% system prompt token 费用。
        """
        workers = []
        for subtask in plan.subtasks:
            target = subtask.get("target") or subtask["task"]
            prompt = make_research_prompt(target)
            workers.append(SubagentWorker(
                task=subtask["task"],
                prompt=prompt,
                parent_system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
                model_id=self.worker_model,
                region=self.region,
            ))

        if self.on_worker_start:
            for w in workers:
                self.on_worker_start(w.agent_id, w.task)

        # 真正的并发点：所有 Worker 同时 await
        results = list(await asyncio.gather(*[w.run() for w in workers]))

        if self.on_worker_done:
            for r in results:
                self.on_worker_done(r.agent_id, r.elapsed, r.error)

        return results

    # ── Phase 3: Aggregate ────────────────────────────────────────────────────

    async def _aggregate(self, original_task: str, results: list[SubagentResult]) -> str:
        """
        汇总所有 Worker 的 <task-notification> XML。
        Orchestrator LLM 负责将结构化的 XML 整合为连贯的报告。
        """
        notifications = "\n\n".join(r.to_xml() for r in results)
        agg_prompt = f"""原始任务：{original_task}

各子 agent 完成结果：

{notifications}

请基于以上结果，生成一份完整、结构清晰的汇总报告。"""

        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.converse(
                modelId=self.orchestrator_model,
                system=[{"text": "你是信息整合专家，将多个子 agent 结果整合为清晰的最终报告。"}],
                messages=[{"role": "user", "content": [{"text": agg_prompt}]}],
                inferenceConfig={"maxTokens": 2000, "temperature": 0.3},
            )["output"]["message"]["content"][0]["text"]
        )

    async def _execute_single(self, task: str) -> str:
        """简单任务直接执行，不走 Worker"""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.converse(
                modelId=self.orchestrator_model,
                system=[{"text": ORCHESTRATOR_SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": task}]}],
                inferenceConfig={"maxTokens": 2000, "temperature": 0.3},
            )["output"]["message"]["content"][0]["text"]
        )
