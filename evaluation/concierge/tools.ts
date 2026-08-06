import { tool } from "ai";
import { z } from "zod";
import { supabaseAnon } from "./anonClient";
import { embedQuery } from "./embedQuery";

// The concierge's two read tools (semantic-search spec). Every param optional;
// filters constrain (strict SQL), `query` ranks (vector-only per Experiment 2).
// SECURITY: results contain scraped text treated as DATA — see the system prompt.

// Timestamps leave the DB in UTC; models read clock digits literally, so we convert
// to Berlin time BEFORE the model ever sees them (a 20:00 gig must never say 18:00).
function berlinTime(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString("de-DE", {
    timeZone: "Europe/Berlin",
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }) + " (Berlin)";
}

export type ToolLog = {
  tool: string;
  args: Record<string, unknown>;
  results: number;
  ms: number;
  degraded?: boolean;
  relaxed?: boolean;
}[];

export function buildTools(opts: {
  categories: string[];
  subcategories: string[];
  log: ToolLog;
}) {
  const { categories, subcategories, log } = opts;

  const searchSchema = z
    .object({
      query: z.string().max(300).optional()
        .describe("Free-text meaning to rank by (any language). Omit for pure filter queries."),
      category: (categories.length ? z.enum(categories as [string, ...string[]]) : z.string())
        .optional(),
      subcategory: (subcategories.length
        ? z.enum(subcategories as [string, ...string[]])
        : z.string()
      ).optional(),
      date_from: z.string().datetime({ offset: true }).optional()
        .describe("ISO start of window. Resolve relative dates yourself (system prompt has now)."),
      date_to: z.string().datetime({ offset: true }).optional(),
      neighborhood: z.string().max(60).optional(),
      venue: z.string().max(80).optional().describe("Venue name, fuzzy match."),
      family_friendly: z.boolean().optional().describe("true REQUIRES; omit = don't care."),
      outdoor: z.boolean().optional(),
      free_entry: z.boolean().optional(),
      max_price_cents: z.number().int().positive().optional(),
      lat: z.number().min(52.2).max(52.7).optional()
        .describe("With lng+radius_km: geo filter. From your knowledge or user location only."),
      lng: z.number().min(13.0).max(13.8).optional(),
      radius_km: z.number().min(0.2).max(10).optional(),
      limit: z.number().int().min(1).max(20).optional(),
    })
    .refine((a) => (a.lat === undefined) === (a.lng === undefined), {
      message: "lat and lng must be provided together",
    });

  return {
    search_events: tool({
      description:
        "Search Berlin events. Filters are strict; `query` only ranks within them. " +
        "Returns compact rows (no descriptions) — use get_event_details to drill in.",
      inputSchema: searchSchema,
      execute: async (args) => {
        const t0 = Date.now();
        // Deterministic date guards — prompts ask nicely, code enforces:
        // never search the past (stale rows mislead the model into "nothing today"),
        // and a window that ends before it starts falls back to defaults.
        const graceMs = 6 * 3600_000; // "jetzt" queries may include just-started events
        const floor = Date.now() - graceMs;
        let dateFrom = args.date_from;
        let dateTo = args.date_to;
        if (dateFrom && Date.parse(dateFrom) < floor) dateFrom = new Date(floor).toISOString();
        if (dateTo && dateFrom && Date.parse(dateTo) <= Date.parse(dateFrom)) dateTo = undefined;
        if (dateTo && Date.parse(dateTo) < floor) dateTo = undefined;

        let qvec: string | null = null;
        let degraded = false;
        if (args.query) {
          qvec = await embedQuery(args.query);
          degraded = qvec === null; // embedding down -> filter-only, never broken
        }
        const runMatch = (category: string | null, subcategory: string | null) =>
          supabaseAnon.rpc("match_events", {
            query_embedding: qvec,
            // lexical title boost: exact-name lookups work even for unembedded events
            ...(args.query ? { p_query_text: args.query.slice(0, 80) } : {}),
            p_category: category,
            p_subcategory: subcategory,
            ...(dateFrom ? { p_date_from: dateFrom } : {}),
            ...(dateTo ? { p_date_to: dateTo } : {}),
            p_neighborhood: args.neighborhood ?? null,
            p_venue: args.venue ?? null,
            p_family: args.family_friendly ?? false,
            p_outdoor: args.outdoor ?? false,
            p_free: args.free_entry ?? false,
            p_max_price_cents: args.max_price_cents ?? null,
            p_lat: args.lat ?? null,
            p_lng: args.lng ?? null,
            p_radius_km: args.radius_km ?? 1.5,
            p_limit: args.limit ?? 10,
          });

        const first = await runMatch(args.category ?? null, args.subcategory ?? null);
        const error = first.error;
        let data = first.data;

        // Sparse-taxonomy degrade (hip-hop incident): genre-ish subcategories are
        // nearly empty buckets, so a strict filter can zero out while the vector
        // ranking would find the right events. If a filtered search with a query
        // comes back empty, retry once without category/subcategory and let the
        // embedding rank across everything. Deterministic — prompts ask nicely,
        // code enforces (same pattern as the date guards above).
        let relaxed = false;
        if (
          !error &&
          (data?.length ?? 0) === 0 &&
          args.query &&
          (args.category || args.subcategory)
        ) {
          const retry = await runMatch(null, null);
          if (!retry.error && (retry.data?.length ?? 0) > 0) {
            data = retry.data;
            relaxed = true;
          }
        }

        log.push({
          tool: "search_events",
          args: { ...args, query: args.query?.slice(0, 60) },
          results: data?.length ?? 0,
          ms: Date.now() - t0,
          ...(degraded ? { degraded } : {}),
          ...(relaxed ? { relaxed } : {}),
        });
        if (error) return { error: "search failed — apologise briefly and suggest retrying" };
        if (!relaxed && (data?.length ?? 0) === 0 && (args.query || args.venue)) {
          // Demand queue: a zero-result search is the purest signal of what users
          // want and we lack — the discovery agent scouts these first. Fire-and-
          // forget; logging must never delay or break the answer.
          supabaseAnon
            .rpc("log_discovery_miss", {
              p_query: args.query ?? null,
              p_venue: args.venue ?? null,
              p_neighborhood: args.neighborhood ?? null,
            })
            .then(undefined, () => {});
        }
        return {
          ...(degraded ? { note: "semantic ranking unavailable; results are filter-only" } : {}),
          ...(relaxed
            ? {
                note:
                  "the category/subcategory filter matched nothing, so results are " +
                  "ranked by meaning across all categories — they may span formats",
              }
            : {}),
          events: (data ?? []).map((e: Record<string, unknown>) => ({
            id: e.id,
            title: e.title,
            venue: e.venue_name,
            start: berlinTime(e.start_time as string),
            category: e.category,
            subcategory: e.subcategory,
            price: e.price,
            neighborhood: e.neighborhood,
            ...(e.distance_km != null
              ? { distance_km: Math.round((e.distance_km as number) * 10) / 10 }
              : {}),
          })),
        };
      },
    }),

    get_event_details: tool({
      description: "Full record for one event (description, ticket URL, coordinates).",
      inputSchema: z.object({ event_id: z.string().uuid() }),
      execute: async ({ event_id }) => {
        const t0 = Date.now();
        const { data, error } = await supabaseAnon
          .from("events")
          .select(
            "id,title,description,venue_name,start_time,end_time,category,subcategory," +
              "price,neighborhood,address,source_url,lat,lng"
          )
          .eq("id", event_id)
          .eq("is_active", true)
          .maybeSingle();
        log.push({
          tool: "get_event_details",
          args: { event_id },
          results: data ? 1 : 0,
          ms: Date.now() - t0,
        });
        if (error || !data) return { error: "event not found" };
        // description is scraped text — DATA, never instructions
        const row = data as unknown as { start_time: string | null; end_time: string | null } & Record<string, unknown>;
        return {
          ...row,
          start_time: berlinTime(row.start_time),
          end_time: berlinTime(row.end_time),
        };
      },
    }),
  };
}
