/**
 * AgentLoop — 复用自 v0.14，不因 channel 变化而修改
 *
 * 这是"channel as plugin"设计的核心证明：
 * Gateway 和 channel 可以完全重写，AgentLoop 一行不动。
 *
 * 注意：这是教学骨架。生产版请参考 lena-v0.14 的完整实现。
 */
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

// 内置工具：get_time
const tools: Anthropic.Tool[] = [
  {
    name: "get_time",
    description: "获取当前时间",
    input_schema: { type: "object" as const, properties: {}, required: [] },
  },
];

function executeTool(name: string, _input: unknown): string {
  if (name === "get_time") {
    return new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" });
  }
  return `[unknown tool: ${name}]`;
}

export class AgentLoop {
  private messages: Anthropic.MessageParam[] = [];

  /** 处理一条用户消息，返回 Lena 的回复 */
  async run(userInput: string): Promise<string> {
    this.messages.push({ role: "user", content: userInput });

    // ReAct 循环：最多 5 步防止无限循环
    for (let step = 0; step < 5; step++) {
      const resp = await client.messages.create({
        model:      "claude-haiku-4-5-20251001",  // 2026 Claude 4.X 系列（2024 版已 deprecated）
        max_tokens: 1024,
        system:     "你是 Lena，一个友好的助手。尽量用中文回复。",
        messages:   this.messages,
        tools,
      });

      if (resp.stop_reason === "end_turn") {
        const text = resp.content
          .filter((b): b is Anthropic.TextBlock => b.type === "text")
          .map((b) => b.text)
          .join("");
        this.messages.push({ role: "assistant", content: resp.content });
        return text;
      }

      if (resp.stop_reason === "tool_use") {
        this.messages.push({ role: "assistant", content: resp.content });
        const toolResults: Anthropic.ToolResultBlockParam[] = [];

        for (const block of resp.content) {
          if (block.type !== "tool_use") continue;
          const result = executeTool(block.name, block.input);
          toolResults.push({
            type:        "tool_result",
            tool_use_id: block.id,
            content:     result,
          });
        }

        this.messages.push({ role: "user", content: toolResults });
        continue;
      }

      break;
    }

    return "[Lena 没有给出回复，请重试]";
  }

  /** 清除对话历史（新会话时调用） */
  reset() { this.messages = []; }
}
