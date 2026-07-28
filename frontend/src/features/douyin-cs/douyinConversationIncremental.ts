/** 抖音会话增量同步纯函数模块——不依赖 React/axios，只依赖 TypeScript 标准类型。 */

export interface EventMessageLike {
  id: string | number;
  raw_event_id?: number;
  created_at: string;
}

export interface ConversationSummaryLike {
  id: string | number;
  conversation_key?: string;
  last_message_at: string;
}

function eventId(item: EventMessageLike): number {
  return Number(item.raw_event_id ?? item.id) || 0;
}

function timeValue(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function mergeMessagesByEventId<T extends EventMessageLike>(current: T[], incoming: T[]): T[] {
  const merged = new Map<string, T>();
  for (const item of [...current, ...incoming]) merged.set(String(eventId(item)), item);
  return [...merged.values()].sort(
    (left, right) => timeValue(left.created_at) - timeValue(right.created_at) || eventId(left) - eventId(right),
  );
}

export function mergeConversationSummaries<T extends ConversationSummaryLike>(current: T[], incoming: T[]): T[] {
  const merged = new Map(current.map((item) => [String(item.conversation_key ?? item.id), item]));
  for (const item of incoming) merged.set(String(item.conversation_key ?? item.id), item);
  return [...merged.values()].sort(
    (left, right) => timeValue(right.last_message_at) - timeValue(left.last_message_at),
  );
}

export function advanceEventCursor(current: number, candidate: number | null | undefined): number {
  return Math.max(current, Number(candidate) || 0);
}

export function retryDelayMs(failureCount: number, jitterMs = Math.floor(Math.random() * 1001) - 500): number {
  const delays = [8000, 16000, 32000, 60000];
  const base = delays[Math.min(Math.max(failureCount, 1), delays.length) - 1];
  return Math.max(0, base + Math.max(-1000, Math.min(1000, jitterMs)));
}

export async function runWithConcurrency<T>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(Math.max(1, limit), queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      if (item !== undefined) await worker(item);
    }
  });
  await Promise.all(workers);
}

export function createCoalescedRunner(run: () => Promise<void>): () => Promise<void> {
  let active: Promise<void> | null = null;
  let pending = false;
  return async () => {
    if (active) {
      pending = true;
      return active;
    }
    active = (async () => {
      do {
        pending = false;
        await run();
      } while (pending);
    })();
    try {
      await active;
    } finally {
      active = null;
    }
  };
}
