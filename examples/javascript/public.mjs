const baseUrl = "https://surgeflows.capital";
const headers = { "User-Agent": "surgeflow-starter-kit-javascript/0.1.0" };

async function get(path) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "GET",
    headers,
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${path}`);
  return response;
}

const freshnessResponse = await get("/api/public/snapshots/data-freshness.json");
const freshness = await freshnessResponse.json();
if (freshness.ok === false) throw new Error("The data-freshness response contains ok=false");
console.log(
  "Public snapshot:",
  freshness.snapshot,
  `status=${freshness.data.status}`,
  `markets=${freshness.data.rows.length}`,
  `generated_at=${freshness.generated_at}`,
);

const hotlistResponse = await get("/api/public/snapshots/momentum-hotlist.json?market=us");
const hotlist = await hotlistResponse.json();
if (hotlist.ok === false) throw new Error("The Hotlist response contains ok=false");
console.log(
  "Hotlist:",
  "market=us",
  `rows=${hotlist.data.rows.length}`,
  `total_count=${hotlist.data.total_count}`,
  `truncated=${hotlist.data.truncated}`,
  `as_of=${hotlist.data.as_of}`,
);

const csvResponse = await get("/api/public/snapshots/momentum-hotlist.csv?market=us");
const csvText = await csvResponse.text();
const csvLines = csvText.trim().split(/\r?\n/);
console.log("CSV:", `rows=${csvLines.length - 1}`, `columns=${csvLines[0]}`);
