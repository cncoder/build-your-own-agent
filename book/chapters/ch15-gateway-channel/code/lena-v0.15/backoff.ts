/**
 * ExponentialBackoff — 指数退避策略
 *
 * 参数选择依据（与 openclaw server-channels.ts:12-17 一致）：
 *   initialMs = 5000   → 网络抖动通常 1-5s 内恢复
 *   maxMs     = 300000 → 超过 5min 需要人工干预
 *   maxRetries = 10    → 覆盖约 85min 的等待窗口
 *   jitter = 0.1       → ±10% 随机量，错开多个 channel 的重连时间
 */
export class ExponentialBackoff {
  private attempt = 0;

  constructor(
    private readonly initialMs  = 5_000,
    private readonly maxMs      = 300_000,
    private readonly maxRetries = 10,
    private readonly jitter     = 0.1,
  ) {}

  nextDelay(): number {
    const base      = Math.min(this.initialMs * 2 ** this.attempt, this.maxMs);
    const jitterMs  = base * this.jitter * (Math.random() * 2 - 1);
    this.attempt++;
    return Math.round(base + jitterMs);
  }

  reset()     { this.attempt = 0; }
  exhausted() { return this.attempt >= this.maxRetries; }
  get count() { return this.attempt; }
}
