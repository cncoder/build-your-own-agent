/**
 * ConsoleChannel — 本地调试用的 stdin/stdout channel
 *
 * 零依赖，无需 token，直接在 terminal 里和 Lena 对话。
 * allowFrom = ["*"] 因为 stdin 本身就是本地可信环境。
 */
import * as readline from "readline";
import type { BaseChannel, ChannelSnapshot } from "./base";

export class ConsoleChannel implements BaseChannel {
  readonly id = "console";
  private handler?: (userId: string, content: string) => Promise<string>;
  private rl?: readline.Interface;
  private running = false;

  onMessage(handler: (userId: string, content: string) => Promise<string>) {
    this.handler = handler;
  }

  async connect() {
    this.running = true;
    this.rl = readline.createInterface({
      input:  process.stdin,
      output: process.stdout,
      prompt: "你: ",
    });

    this.rl.prompt();

    this.rl.on("line", async (line) => {
      const content = line.trim();
      if (!content || !this.handler) {
        this.rl?.prompt();
        return;
      }
      try {
        const reply = await this.handler("console-user", content);
        console.log(`[Lena] ${reply}`);
      } catch (err) {
        console.error(`[Console] 处理失败: ${String(err)}`);
      }
      this.rl?.prompt();
    });

    this.rl.on("close", () => {
      this.running = false;
    });

    console.log("[Console] 已连接，直接输入消息");
  }

  async disconnect() {
    this.running = false;
    this.rl?.close();
  }

  async send(userId: string, content: string) {
    console.log(`[Lena → ${userId}] ${content}`);
  }

  snapshot(): ChannelSnapshot {
    return { id: this.id, status: this.running ? "running" : "stopped", retries: 0 };
  }
}
