import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  SurgeFlow,
  SurgeFlowApiError,
  SurgeFlowNetworkError,
  SurgeFlowResponseError,
  SurgeFlowTimeoutError,
} from "../src/index.js";

const KEY = "sf_live_REPLACE_WITH_YOUR_KEY";

function fixture(name) {
  return readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8");
}

function response(body, status = 200) {
  return new Response(body, { status });
}

function recordingClient(body) {
  const calls = [];
  const client = new SurgeFlow({
    fetch: async (url, options) => {
      calls.push({ url: String(url), options });
      return response(body);
    },
  });
  return { calls, client };
}

test("momentumHotlist uses the recorded fixture and client user agent", async () => {
  const body = fixture("momentum-hotlist-us.json");
  const { calls, client } = recordingClient(body);

  const result = await client.momentumHotlist("us");

  assert.deepEqual(result, JSON.parse(body));
  assert.equal(calls.length, 1);
  const [call] = calls;
  assert.equal(new URL(call.url).pathname, "/api/public/snapshots/momentum-hotlist.json");
  assert.equal(new URL(call.url).searchParams.get("market"), "us");
  assert.equal(call.options.method, "GET");
  assert.deepEqual(call.options.headers, {
    Accept: "application/json",
    "User-Agent": "surgeflow-javascript/0.1.0",
  });
});

test("CSV snapshots return recorded text", async () => {
  const body = fixture("momentum-hotlist-us.csv");
  const { calls, client } = recordingClient(body);

  const result = await client.momentumHotlist("us", { responseFormat: "csv" });

  assert.equal(result, body);
  assert.equal(new URL(calls[0].url).pathname, "/api/public/snapshots/momentum-hotlist.csv");
  assert.equal(calls[0].options.headers.Accept, "text/csv");
});

test("other public methods use the documented paths and parameters", async () => {
  const calls = [];
  const client = new SurgeFlow({
    fetch: async (url, options) => {
      calls.push({ url: new URL(String(url)), options });
      return response(fixture("data-freshness.json"));
    },
  });

  await client.macroIndicators();
  await client.newsSentiment(30);
  await client.factorOverview("jp");
  await client.dataFreshness();

  assert.deepEqual(calls.map(call => call.url.pathname), [
    "/api/public/snapshots/macro-indicators.json",
    "/api/public/snapshots/news-sentiment.json",
    "/api/public/snapshots/factor-overview.json",
    "/api/public/snapshots/data-freshness.json",
  ]);
  assert.equal(calls[1].url.searchParams.get("days"), "30");
  assert.equal(calls[2].url.searchParams.get("market"), "jp");
});

test("memberMe sends the bearer key", async () => {
  const { calls, client } = recordingClient('{"ok":true,"data":{}}');

  const result = await client.memberMe(KEY);

  assert.equal(result.ok, true);
  assert.equal(new URL(calls[0].url).pathname, "/api/v1/me");
  assert.equal(calls[0].options.headers.Authorization, `Bearer ${KEY}`);
});

test("memberHotlist validates the market and sends the key", async () => {
  const { calls, client } = recordingClient(fixture("momentum-hotlist-us.json"));

  const result = await client.memberHotlist("hk", KEY);

  assert.ok(result.data.rows.length > 0);
  assert.equal(new URL(calls[0].url).pathname, "/api/v1/markets/hk/hotlist");
  assert.equal(calls[0].options.headers.Authorization, `Bearer ${KEY}`);
});

test("invalid markets fail before fetch", async () => {
  let called = false;
  const client = new SurgeFlow({ fetch: async () => { called = true; } });

  for (const market of ["xx", "US", "", null]) {
    await assert.rejects(client.momentumHotlist(market), TypeError);
  }
  assert.equal(called, false);
});

test("invalid days fail before fetch", async () => {
  let called = false;
  const client = new SurgeFlow({ fetch: async () => { called = true; } });

  for (const days of [0, 366, true, 1.5]) {
    await assert.rejects(client.newsSentiment(days), TypeError);
  }
  assert.equal(called, false);
});

test("unknown snapshots and formats fail before fetch", async () => {
  let called = false;
  const client = new SurgeFlow({ fetch: async () => { called = true; } });

  await assert.rejects(client.publicSnapshot("unknown"), TypeError);
  await assert.rejects(client.dataFreshness({ responseFormat: "xml" }), TypeError);
  assert.equal(called, false);
});

test("HTTP errors expose typed status and payload", async () => {
  const client = new SurgeFlow({ fetch: async () => response('{"error":"Invalid key"}', 401) });

  await assert.rejects(client.memberMe(KEY), error => {
    assert.ok(error instanceof SurgeFlowApiError);
    assert.equal(error.statusCode, 401);
    assert.deepEqual(error.payload, { error: "Invalid key" });
    assert.equal(error.message, "Invalid key");
    return true;
  });
});

test("timeouts expose a typed error", async () => {
  const client = new SurgeFlow({
    timeout: 5,
    fetch: (url, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }),
  });

  await assert.rejects(client.dataFreshness(), SurgeFlowTimeoutError);
});

test("transport failures expose a typed error", async () => {
  const client = new SurgeFlow({ fetch: async () => { throw new Error("offline"); } });

  await assert.rejects(client.dataFreshness(), SurgeFlowNetworkError);
});

test("invalid JSON exposes a typed error", async () => {
  const { client } = recordingClient("not-json");

  await assert.rejects(client.dataFreshness(), SurgeFlowResponseError);
});

test("ok=false exposes a typed error", async () => {
  const { client } = recordingClient('{"ok":false}');

  await assert.rejects(client.dataFreshness(), SurgeFlowResponseError);
});
