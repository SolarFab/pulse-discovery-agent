import { startActiveObservation } from "@langfuse/tracing";

type StepType = "span" | "retriever" | "embedding" | "tool";

/**
 * Wrap one step of a concierge turn in its own observation.
 *
 * Uses `@langfuse/tracing` directly — the SAME machinery that produces the root
 * `concierge-request` span via `observe()`. An earlier attempt created these spans
 * from a hand-rolled NodeTracerProvider, which is a *parallel* tracing stack that
 * Langfuse's own API never reads: the spans went nowhere and the trace stayed
 * stubbornly one observation deep. If the root span works, its children have to be
 * created the same way.
 *
 * Why this layer exists at all: the AI SDK traces the model call and the tool call,
 * but a tool call is one opaque box, and most of a slow turn hides inside it.
 * `search_events` alone makes two network round-trips — embed the query, then the
 * vector search — so without these spans a 34-second turn is a single number with
 * nowhere to look.
 *
 * Never changes the result or the error: instrumentation that can alter behaviour is
 * worse than none.
 */
export async function step<T>(
  name: string,
  opts: { type?: StepType; input?: unknown },
  fn: () => PromiseLike<T>,
): Promise<{ value: T; ms: number }> {
  const t0 = Date.now();
  try {
    return (await startActiveObservation(
      name,
      async (span: { update: (a: Record<string, unknown>) => void }) => {
        try {
          const value = await fn();
          const ms = Date.now() - t0;
          span.update({ output: summarise(value), metadata: { duration_ms: ms } });
          return { value, ms };
        } catch (err) {
          span.update({ level: "ERROR", statusMessage: String(err).slice(0, 300) });
          throw err;
        }
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { asType: opts.type ?? "span", input: opts.input } as any,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    )) as any;
  } catch (err) {
    // Only a tracing fault falls through to an untraced run — a real error from `fn`
    // has already been rethrown above and must keep propagating.
    if (err instanceof Error && /langfuse|tracer|otel/i.test(err.message)) {
      const value = await fn();
      return { value, ms: Date.now() - t0 };
    }
    throw err;
  }
}

/** Row payloads are large and mostly noise in a trace — record shape, not contents. */
function summarise(v: unknown): unknown {
  if (Array.isArray(v)) return { count: v.length };
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (Array.isArray(o.data)) return { rows: (o.data as unknown[]).length, error: o.error ?? null };
    if (typeof o.length === "number") return { length: o.length };
  }
  return v;
}
