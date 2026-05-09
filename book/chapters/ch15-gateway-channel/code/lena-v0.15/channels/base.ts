/**
 * BaseChannel 接口 — 所有 channel 必须实现
 *
 * AgentLoop 只知道这个接口，不知道 Telegram/Discord/Console 的存在。
 * 这是 "channel as plugin" 的契约。
 */
export interface BaseChannel {
  readonly id: string;

  /** 连接到消息源（Telegram polling / Discord gateway / stdin 等） */
  connect(): Promise<void>;

  /** 断开连接 */
  disconnect(): Promise<void>;

  /**
   * 注册消息处理函数。
   * Gateway 在 start() 时注入，channel 收到消息时调用，
   * handler 返回 Lena 的回复字符串。
   */
  onMessage(
    handler: (userId: string, content: string) => Promise<string>
  ): void;

  /** 主动向用户发消息（heartbeat / cron 结果推送等） */
  send(userId: string, content: string): Promise<void>;

  /** 运行时快照，供 /status 端点使用 */
  snapshot(): ChannelSnapshot;
}

export type ChannelSnapshot = {
  id:      string;
  status:  "running" | "stopped" | "reconnecting";
  retries: number;
};
