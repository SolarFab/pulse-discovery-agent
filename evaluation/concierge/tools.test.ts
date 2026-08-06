import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// Schema-level tests (semantic-search 2.4): validation rules, no network/DB.
process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "test-anon";

const rpcMock = vi.fn();
vi.mock("./anonClient", () => ({ supabaseAnon: { rpc: (...a: unknown[]) => rpcMock(...a) } }));
vi.mock("./embedQuery", () => ({ embedQuery: async () => "[0.1,0.2]" }));

let searchSchema: { safeParse: (v: unknown) => { success: boolean } };

beforeAll(async () => {
  const { buildTools } = await import("./tools");
  const tools = buildTools({
    categories: ["music", "nightlife", "markets"],
    subcategories: ["jazz-blues", "flea-market"],
    log: [],
  });
  searchSchema = tools.search_events.inputSchema as typeof searchSchema;
});

describe("search_events schema", () => {
  it("accepts an empty call (all params optional)", () => {
    expect(searchSchema.safeParse({}).success).toBe(true);
  });

  it("accepts a full hybrid call", () => {
    expect(
      searchSchema.safeParse({
        query: "jazz",
        subcategory: "jazz-blues",
        date_from: "2026-07-30T17:00:00+02:00",
        date_to: "2026-07-31T05:00:00+02:00",
        family_friendly: true,
        lat: 52.474,
        lng: 13.428,
        radius_km: 1,
        limit: 10,
      }).success
    ).toBe(true);
  });

  it("rejects lat without lng (geo pair rule)", () => {
    expect(searchSchema.safeParse({ lat: 52.5 }).success).toBe(false);
  });

  it("rejects unknown category (enum generated from taxonomy)", () => {
    expect(searchSchema.safeParse({ category: "sportsball" }).success).toBe(false);
    expect(searchSchema.safeParse({ category: "markets" }).success).toBe(true);
  });

  it("rejects out-of-range radius and limit", () => {
    expect(searchSchema.safeParse({ lat: 52.5, lng: 13.4, radius_km: 50 }).success).toBe(false);
    expect(searchSchema.safeParse({ limit: 100 }).success).toBe(false);
  });

  it("rejects coordinates outside Berlin", () => {
    expect(searchSchema.safeParse({ lat: 48.13, lng: 11.58 }).success).toBe(false); // Munich
  });
});

// Sparse-taxonomy degrade (hip-hop incident): an empty filtered result with a
// text query retries once without category/subcategory instead of dead-ending.
describe("search_events relax-on-empty", () => {
  const row = {
    id: "e1",
    title: "Best Mistake @ Kitty Cheng",
    venue_name: "Kitty Cheng Bar",
    start_time: "2026-08-06T20:00:00Z",
    category: "nightlife",
    subcategory: "party",
    price: "Free",
    neighborhood: "Mitte",
  };

  type Exec = (args: Record<string, unknown>) => Promise<{
    events?: unknown[];
    note?: string;
    error?: string;
  }>;
  let exec: Exec;
  let log: import("./tools").ToolLog;

  beforeEach(async () => {
    rpcMock.mockReset();
    log = [];
    const { buildTools } = await import("./tools");
    const tools = buildTools({
      categories: ["music", "nightlife"],
      subcategories: ["jazz-blues", "hip-hop"],
      log,
    });
    exec = tools.search_events.execute as unknown as Exec;
  });

  it("retries without category/subcategory when the filtered search is empty", async () => {
    rpcMock
      .mockResolvedValueOnce({ data: [], error: null }) // strict: subcategory bucket empty
      .mockResolvedValueOnce({ data: [row], error: null }); // relaxed: vector finds it

    const out = await exec({ query: "hip hop", subcategory: "hip-hop" });

    expect(rpcMock).toHaveBeenCalledTimes(2);
    expect(rpcMock.mock.calls[0][1]).toMatchObject({ p_subcategory: "hip-hop" });
    expect(rpcMock.mock.calls[1][1]).toMatchObject({ p_category: null, p_subcategory: null });
    expect(out.events).toHaveLength(1);
    expect(out.note).toMatch(/across all categories/);
    expect(log[0]).toMatchObject({ relaxed: true, results: 1 });
  });

  it("does not retry without a text query (pure filter browse may honestly be empty)", async () => {
    rpcMock.mockResolvedValueOnce({ data: [], error: null });

    const out = await exec({ subcategory: "hip-hop" });

    expect(rpcMock).toHaveBeenCalledTimes(1);
    expect(out.events).toHaveLength(0);
  });

  it("does not retry when the filtered search already has results", async () => {
    rpcMock.mockResolvedValueOnce({ data: [row], error: null });

    const out = await exec({ query: "party", category: "nightlife" });

    expect(rpcMock).toHaveBeenCalledTimes(1);
    expect(out.note).toBeUndefined();
    expect(out.events).toHaveLength(1);
  });

  it("logs a discovery miss only when the relaxed retry is also empty", async () => {
    rpcMock
      .mockResolvedValueOnce({ data: [], error: null })
      .mockResolvedValueOnce({ data: [], error: null }) // relax also empty
      .mockResolvedValueOnce({ data: null, error: null }); // log_discovery_miss

    await exec({ query: "zydeco", category: "music" });

    const missCalls = rpcMock.mock.calls.filter((c) => c[0] === "log_discovery_miss");
    expect(missCalls).toHaveLength(1);
  });

  it("suppresses the discovery miss when the relax recovers results (no false demand)", async () => {
    rpcMock
      .mockResolvedValueOnce({ data: [], error: null })
      .mockResolvedValueOnce({ data: [row], error: null });

    await exec({ query: "hip hop", subcategory: "hip-hop" });

    const missCalls = rpcMock.mock.calls.filter((c) => c[0] === "log_discovery_miss");
    expect(missCalls).toHaveLength(0);
  });
});
