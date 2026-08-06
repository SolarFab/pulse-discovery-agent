// Langfuse tracing (observability spec 1.1). Next runs register() per server/lambda start.
// The processor lives on globalThis: in production, route bundles and the instrumentation
// bundle each get their own module copy — without the global, routes would flush an empty
// duplicate while real spans die in the registered instance's batch queue.
//
// NOTE: this provider serves @langfuse/tracing only. Vercel AI SDK v7 emits NO
// OpenTelemetry spans at all (see lib/ai/generations.ts), so nothing here reaches the
// model calls — those are recorded explicitly.
import { LangfuseSpanProcessor } from "@langfuse/otel";
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";

type G = typeof globalThis & {
  __lfProcessor?: LangfuseSpanProcessor | null;
  __lfRegistered?: boolean;
};
const g = globalThis as G;

export function getLangfuseProcessor(): LangfuseSpanProcessor | null {
  if (g.__lfProcessor === undefined) {
    g.__lfProcessor = process.env.LANGFUSE_PUBLIC_KEY ? new LangfuseSpanProcessor() : null;
  }
  return g.__lfProcessor;
}

export function register() {
  const processor = getLangfuseProcessor();
  if (!processor || g.__lfRegistered) return;
  const provider = new NodeTracerProvider({ spanProcessors: [processor] });
  provider.register();
  g.__lfRegistered = true;
}
