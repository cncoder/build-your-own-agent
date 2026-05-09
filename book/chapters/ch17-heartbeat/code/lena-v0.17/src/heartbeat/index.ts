/**
 * lena-v0.17 · Heartbeat 核心
 *
 * 最简实现：setTimeout + EventEmitter
 * 对应 Ch17 Beat 4-5 的渐进组装过程
 *
 * 参考：nano-claw/src/heartbeat/index.ts（178 行甜点级实现）
 */

import { EventEmitter } from "events";

// ─── 类型定义 ────────────────────────────────────────────────────────────────

export interface ActiveHoursConfig {
  /** IANA 时区，如 "Asia/Shanghai" / "Asia/Hong_Kong" */
  timezone: string;
  /** 工作日活跃区间（0-23 小时整数） */
  weekdays: { start: number; end: number };
  /** 可选：周末单独配置，不填则复用 weekdays */
  weekend?: { start: number; end: number };
}

export interface HeartbeatConfig {
  /**
   * 节拍间隔毫秒
   * 测试用 60_000（1 分钟），生产用 3_600_000（1 小时）
   */
  intervalMs: number;
  activeHours: ActiveHoursConfig;
  agentId: string;
  channelId: string;
}

/** Heartbeat 触发后向外推送的消息结构 */
export interface OutboundPayload {
  agentId:   string;
  channelId: string;
  content:   string;
  timestamp: number;
  /** 触发原因，方便日志追踪（如 "tick#3"） */
  reason: string;
}

/** 调用方注入的内容生成器
 * 返回 null 表示本次节拍无内容，静默跳过
 */
type PayloadGenerator = () => Promise<string | null>;

// ─── Active Hours 判断 ───────────────────────────────────────────────────────

/**
 * 判断当前时刻是否在 active hours 内
 *
 * 使用 Intl.DateTimeFormat 做时区换算，避免手动处理 UTC offset。
 * 工作日和周末可分别配置不同时段。
 */
export function isActiveHours(config: ActiveHoursConfig): boolean {
  const now   = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: config.timezone,
    hour:     "numeric",
    weekday:  "short",
    hour12:   false,
  }).formatToParts(now);

  const hourStr    = parts.find(p => p.type === "hour")?.value    ?? "0";
  const weekdayStr = parts.find(p => p.type === "weekday")?.value ?? "Mon";

  const hour      = parseInt(hourStr, 10);
  const isWeekend = weekdayStr === "Sat" || weekdayStr === "Sun";
  const schedule  = isWeekend ? (config.weekend ?? config.weekdays) : config.weekdays;

  return hour >= schedule.start && hour < schedule.end;
}

// ─── HeartbeatRunner ─────────────────────────────────────────────────────────

/**
 * Heartbeat 主控制器
 *
 * 事件：
 *   "outbound" (payload: OutboundPayload) — 有内容需要推送时触发
 *   "tick"     (skipped: boolean)         — 每次节拍（skipped=true 表示在 active hours 之外）
 *
 * 用法：
 *   const runner = new HeartbeatRunner(config, myGenerator);
 *   runner.on("outbound", payload => channel.send(payload.content));
 *   runner.start();
 *   // Ctrl+C 时：runner.stop();
 */
export class HeartbeatRunner extends EventEmitter {
  private config:          HeartbeatConfig;
  private timer:           ReturnType<typeof setTimeout> | null = null;
  private generatePayload: PayloadGenerator;
  private tickCount = 0;

  constructor(config: HeartbeatConfig, generatePayload: PayloadGenerator) {
    super();
    this.config          = config;
    this.generatePayload = generatePayload;
  }

  start(): void {
    console.log(
      `[Heartbeat] started — interval=${this.config.intervalMs}ms` +
      ` tz=${this.config.activeHours.timezone}` +
      ` hours=${this.config.activeHours.weekdays.start}:00-${this.config.activeHours.weekdays.end}:00`
    );
    this.scheduleNext();
  }

  stop(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    console.log("[Heartbeat] stopped");
  }

  /**
   * 递归 setTimeout 而非 setInterval
   *
   * setInterval 的问题：如果 onTick 耗时 30s（LLM 调用），
   * 下一个 interval 触发时上一次还没完成，导致节拍重叠。
   * 递归 setTimeout 保证：上一次执行完 → 再等 intervalMs → 才触发下一次。
   */
  private scheduleNext(): void {
    this.timer = setTimeout(() => {
      void this.onTick().finally(() => this.scheduleNext());
    }, this.config.intervalMs);
  }

  private async onTick(): Promise<void> {
    this.tickCount += 1;
    const id = `tick#${this.tickCount}`;

    // Active hours 门控：不在时间窗口内就静默跳过
    if (!isActiveHours(this.config.activeHours)) {
      console.log(`[Heartbeat] ${id} — outside active hours, skipping`);
      this.emit("tick", true);
      return;
    }

    console.log(`[Heartbeat] ${id} — active, generating payload...`);

    let content: string | null = null;
    try {
      content = await this.generatePayload();
    } catch (err) {
      console.error(`[Heartbeat] ${id} — generator failed:`, err);
    }

    if (!content) {
      console.log(`[Heartbeat] ${id} — no content, skipping`);
      this.emit("tick", false);
      return;
    }

    // 向外发布 outbound 事件，调用方决定通过哪个 channel 推送
    const payload: OutboundPayload = {
      agentId:   this.config.agentId,
      channelId: this.config.channelId,
      content,
      timestamp: Date.now(),
      reason:    id,
    };

    console.log(`[Heartbeat] ${id} — emitting outbound`);
    this.emit("outbound", payload);
    this.emit("tick", false);
  }
}
