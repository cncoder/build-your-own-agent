/**
 * TelegramChannel — Telegram Bot API polling 模式
 *
 * 依赖：npm install node-telegram-bot-api @types/node-telegram-bot-api
 *
 * 关键设计：
 * 1. allowFrom 白名单在 channel 层过滤，AgentLoop 永远只见授权消息
 * 2. 指数退避重连：5s → 10s → 20s → ... → 300s（上限），最多 10 次
 * 3. AbortController 风格的 aborted 标志，确保 disconnect() 后不再重连
 */
import TelegramBot from "node-telegram-bot-api";
import { ExponentialBackoff } from "../backoff";
import type { BaseChannel, ChannelSnapshot } from "./base";

export class TelegramChannel implements BaseChannel {
  readonly id = "telegram";

  private bot?: TelegramBot;
  private handler?: (userId: string, content: string) => Promise<string>;
  private backoff = new ExponentialBackoff();
  private aborted = false;
  private _status: ChannelSnapshot["status"] = "stopped";

  constructor(
    private readonly token:     string,
    /** 白名单 userId 数组，"*" 表示允许所有人 */
    private readonly allowFrom: string[] = ["*"],
  ) {}

  onMessage(handler: (userId: string, content: string) => Promise<string>) {
    this.handler = handler;
  }

  async connect(): Promise<void> {
    this.aborted = false;
    this.backoff.reset();

    while (!this.aborted) {
      try {
        this._status = "reconnecting";
        await this.tryConnect();
        // tryConnect 正常 resolve = polling 被外部停止（disconnect 调用）
        this._status = "stopped";
        return;
      } catch (err) {
        if (this.aborted) { this._status = "stopped"; return; }
        if (this.backoff.exhausted()) {
          console.error(`[Telegram] 放弃重连，已尝试 ${this.backoff.count} 次`);
          this._status = "stopped";
          return;
        }
        const delay = this.backoff.nextDelay();
        console.log(
          `[Telegram] 连接失败，${Math.round(delay / 1000)}s 后重试` +
          `（第 ${this.backoff.count} 次 / 最多 10 次）: ${String(err)}`
        );
        this._status = "reconnecting";
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(resolve, delay);
          // 如果在等待期间调用了 disconnect()，立即取消等待
          const check = setInterval(() => {
            if (this.aborted) { clearTimeout(timer); clearInterval(check); resolve(); }
          }, 100);
          void timer; // suppress unused warning
        });
      }
    }
  }

  private async tryConnect(): Promise<void> {
    this.bot = new TelegramBot(this.token, { polling: true });

    // 注册消息处理
    this.bot.on("message", async (msg) => {
      const userId  = msg.from?.id?.toString() ?? "";
      const content = msg.text ?? "";
      if (!content) return;

      // allowFrom 白名单检查
      const allowed =
        this.allowFrom.includes("*") ||
        this.allowFrom.includes(userId);
      if (!allowed) {
        console.log(`[Telegram] 忽略未授权用户 ${userId}`);
        return;
      }

      try {
        const reply = await this.handler?.(userId, content) ?? "";
        await this.bot!.sendMessage(msg.chat.id, reply);
      } catch (err) {
        console.error(`[Telegram] 处理消息失败: ${String(err)}`);
      }
    });

    this._status = "running";
    this.backoff.reset();
    console.log("[Telegram] 已连接，polling 中");

    // 等待 polling_error 触发（= 需要重连）或外部 disconnect 调用
    await new Promise<void>((resolve, reject) => {
      this.bot!.on("polling_error", (err) => {
        console.error(`[Telegram] polling_error: ${err.message}`);
        reject(err);
      });
      // disconnect 时 stopPolling 会让 polling 正常结束
      this.bot!.on("webhook_error", (err) => reject(err));
    });
  }

  async disconnect() {
    this.aborted = true;
    await this.bot?.stopPolling();
    this._status = "stopped";
  }

  async send(userId: string, content: string) {
    if (!this.bot) throw new Error("[Telegram] not connected");
    await this.bot.sendMessage(userId, content);
  }

  snapshot(): ChannelSnapshot {
    return { id: this.id, status: this._status, retries: this.backoff.count };
  }
}
