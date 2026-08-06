import { startObservation } from "@langfuse/tracing";

/**
 * Record one Langfuse generation per model call.
 *
 * Why by hand: **AI SDK v7 emits no OpenTelemetry spans.** `@opentelemetry` does not
 * appear anywhere in its bundle — v7 replaced the OTEL integration with an internal
 * telemetry dispatcher. So `experimental_telemetry: { isEnabled: true }` produces no
 * generations regardless of how the tracer is wired, and Langfuse's Vercel AI SDK
 * integration guide describes v5-era behaviour that no longer applies.
 *
 * Two earlier attempts chased that dead end (passing a `tracer` option v7 removed,
 * then binding a provider to the OTEL global). The tell was that a turn showed 15s
 * total with only ~1.7s inside child spans: the model calls were never instrumented,
 * they were simply absent.
 *
 * `onFinish` hands back a `steps` array — one entry per model call, each with its own
 * model, usage and finish reason — which is everything a generation needs.
 */
type Usage = {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  cachedInputTokens?: number;
};

type Step = {
  stepNumber?: number;
  modelId?: string;
  provider?: string;
  text?: string;
  usage?: Usage;
  finishReason?: string;
  toolCalls?: { toolName?: string }[];
  performance?: { effectiveOutputTokensPerSecond?: number };
};

export function recordGenerations(args: {
  steps?: unknown[];
  usage?: unknown;
  model: string;
  text: string;
  startedAt: number;
  /** ms from the first model call until the first streamed token reached the user. */
  ttftMs?: number | null;
}): void {
  const { steps, usage, model, text, startedAt, ttftMs } = args;
  try {
    const list = (steps as Step[] | undefined) ?? [];
    if (list.length === 0) {
      // No step detail (older SDK shape): one generation for the whole turn, so the
      // trace is never silently missing its most expensive observation.
      emit({
        name: "generate-answer",
        model,
        usage: usage as Usage | undefined,
        output: text.slice(0, 2000),
        startTime: new Date(startedAt),
        completionStartTime: ttftMs != null ? new Date(startedAt + ttftMs) : undefined,
      });
      return;
    }
    // Durations come from the SDK's own MEASURED throughput
    // (performance.effectiveOutputTokensPerSecond) — outputTokens / rate. An earlier
    // version apportioned elapsed time by output tokens instead, which made every
    // step report an identical tokens/sec: the figure was an artifact of the split,
    // not a measurement. Falls back to apportioning only when the SDK omits the rate.
    const totalOut = list.reduce((n, s) => n + (s.usage?.outputTokens ?? 0), 0) || 1;
    const elapsed = Date.now() - startedAt;
    let cursor = startedAt;
    list.forEach((s, i) => {
      const out = s.usage?.outputTokens ?? 0;
      const rate = s.performance?.effectiveOutputTokensPerSecond;
      const measured = rate && rate > 0 ? (out / rate) * 1000 : null;
      const share = measured ?? (out / totalOut) * elapsed;
      const start = new Date(cursor);
      cursor += share;
      const calls = (s.toolCalls ?? []).map((c) => c.toolName).filter(Boolean);
      emit({
        name: calls.length ? `model-call-${i + 1} → ${calls.join(",")}` : `model-call-${i + 1}`,
        model: s.modelId ?? model,
        usage: s.usage,
        output: s.text?.slice(0, 2000) || (calls.length ? { tool_calls: calls } : ""),
        startTime: start,
        endTime: new Date(cursor),
        // Time-to-first-token belongs to the step that actually streamed to the
        // user — the last one. Langfuse renders completionStartTime natively, which
        // is the field for this; a metadata attribute would not surface as TTFT.
        completionStartTime:
          i === list.length - 1 && ttftMs != null ? new Date(startedAt + ttftMs) : undefined,
        metadata: {
          step: s.stepNumber ?? i,
          finish_reason: s.finishReason,
          provider: s.provider,
          tokens_per_second: s.performance?.effectiveOutputTokensPerSecond,
          timing: s.performance?.effectiveOutputTokensPerSecond
            ? "measured: outputTokens / effectiveOutputTokensPerSecond"
            : "estimated: elapsed apportioned by output tokens (SDK gave no rate)",
        },
      });
    });
  } catch {
    // Telemetry must never break a chat turn.
  }
}

function emit(o: {
  name: string;
  model: string;
  usage?: Usage;
  output: unknown;
  startTime: Date;
  endTime?: Date;
  completionStartTime?: Date;
  costUsd?: number;
  metadata?: Record<string, unknown>;
}): void {
  const gen = startObservation(
    o.name,
    {
      model: o.model,
      output: o.output,
      ...(o.completionStartTime ? { completionStartTime: o.completionStartTime } : {}),
      metadata: o.metadata,
      // Langfuse has no price table for OpenRouter-namespaced model ids, so cost
      // stays 0 unless the provider hands one back. Recording a guessed cost would
      // be worse than recording none.
      ...(o.costUsd != null ? { costDetails: { total: o.costUsd } } : {}),
      usageDetails: o.usage
        ? {
            input: o.usage.inputTokens ?? 0,
            output: o.usage.outputTokens ?? 0,
            total: o.usage.totalTokens ?? 0,
            ...(o.usage.cachedInputTokens ? { cache_read_input_tokens: o.usage.cachedInputTokens } : {}),
          }
        : undefined,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    { asType: "generation", startTime: o.startTime } as any,
  );
  // end() takes the time DIRECTLY, not { endTime }. Passing an object silently
  // yields a zero-duration observation — which is how the first probe looked.
  gen.end(o.endTime);
}
