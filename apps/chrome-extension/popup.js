const SURGEFLOW_ERROR_MESSAGE = "SurgeFlow data could not be loaded. Try again later.";
const SURGEFLOW_MARKETS = ["us", "cn", "jp", "hk"];
const SURGEFLOW_SNAPSHOT_ORIGIN = "https://surgeflows.capital";

function snapshotUrl(datasetId, market) {
  const suffix = market ? `?market=${encodeURIComponent(market)}` : "";
  return `${SURGEFLOW_SNAPSHOT_ORIGIN}/api/public/snapshots/${datasetId}.json${suffix}`;
}

async function fetchSnapshot(datasetId, market) {
  const response = await fetch(snapshotUrl(datasetId, market), {
    method: "GET",
    credentials: "omit",
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (response.status !== 200) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return response.json();
}

function requiredString(value) {
  if (typeof value !== "string" || !value) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return value;
}

function requiredNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return value;
}

function requiredScalar(value) {
  if (typeof value !== "string" && typeof value !== "number") throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return value;
}

function requiredBoolean(value) {
  if (typeof value !== "boolean") throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return value;
}

function sourcePrefix(row) {
  return String(row && row.source).split(":")[0];
}

function parseHotlist(payload, market) {
  const policy = ADDIN_DATA_POLICY["momentum-hotlist"];
  if (!policy.enabled || !["link_only", "ticker_rank"].includes(policy.mode) ||
      !SURGEFLOW_MARKETS.includes(market) || !policy.markets[market].enabled) {
    throw new Error(SURGEFLOW_ERROR_MESSAGE);
  }
  const data = payload && payload.data;
  if (!data) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  const hotlist = {
    mode: policy.mode,
    market,
    phase: requiredString(data.market_phase),
    status: requiredString(data.display_status),
    asOf: requiredString(data.as_of),
    totalCount: requiredNumber(data.total_count),
    truncated: requiredBoolean(data.truncated),
    rows: [],
    link: `${SURGEFLOW_SNAPSHOT_ORIGIN}/momentum/${market}`,
  };
  if (policy.mode === "link_only") {
    hotlist.count = requiredNumber(data.count);
    return hotlist;
  }
  // An empty board is honest only when SurgeFlow says it holds zero names.
  if (!Array.isArray(data.rows) || (!data.rows.length && hotlist.totalCount !== 0)) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  hotlist.rows = data.rows.map(row => {
    const stockLink = requiredString(row && row.stock_link);
    if (!stockLink.startsWith("/stock/")) throw new Error(SURGEFLOW_ERROR_MESSAGE);
    return {
      ticker: requiredString(row && row.ticker),
      selectionRank: requiredNumber(row && row.selection_rank),
      link: `${SURGEFLOW_SNAPSHOT_ORIGIN}${stockLink}`,
    };
  });
  return hotlist;
}

function parseFreshness(payload, market) {
  if (!ADDIN_DATA_POLICY["data-freshness"].enabled || !ADDIN_DATA_POLICY["data-freshness"].markets.all.enabled) {
    throw new Error(SURGEFLOW_ERROR_MESSAGE);
  }
  const rows = payload && payload.data && payload.data.rows;
  if (!Array.isArray(rows)) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  const row = rows.find(candidate => candidate && candidate.market === market);
  if (!row) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  return {
    market,
    latestDate: requiredString(row.latest_date),
    expectedLatest: requiredString(row.expected_latest),
    tradingDaysStale: requiredNumber(row.trading_days_stale),
    status: requiredString(row.status),
  };
}

function parseMacro(payload) {
  const policy = ADDIN_DATA_POLICY["macro-indicators"].markets.all;
  if (!ADDIN_DATA_POLICY["macro-indicators"].enabled || !policy.enabled) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  const sourceRows = payload && payload.data && payload.data.rows;
  if (!Array.isArray(sourceRows)) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  const rows = sourceRows.filter(row => policy.allow_source_prefixes.includes(sourcePrefix(row))).map(row => ({
    indicator: requiredString(row.indicator),
    country: requiredString(row.country),
    value: requiredScalar(row.value),
    unit: row.unit === "" ? "" : requiredString(row.unit),
    date: requiredString(row.date),
    source: requiredString(row.source),
  }));
  if (!rows.length) throw new Error(SURGEFLOW_ERROR_MESSAGE);
  const credits = [];
  for (const row of rows) {
    const credit = policy.credits[sourcePrefix(row)];
    if (!credit) throw new Error(SURGEFLOW_ERROR_MESSAGE);
    if (!credits.includes(credit)) credits.push(credit);
  }
  return { rows, credits };
}

async function loadPopupData(market) {
  const [hotlistPayload, macroPayload, freshnessPayload] = await Promise.all([
    fetchSnapshot("momentum-hotlist", market),
    fetchSnapshot("macro-indicators", ""),
    fetchSnapshot("data-freshness", ""),
  ]);
  return {
    hotlist: parseHotlist(hotlistPayload, market),
    macro: parseMacro(macroPayload),
    freshness: parseFreshness(freshnessPayload, market),
  };
}

function appendCell(doc, row, value, header = false) {
  const cell = doc.createElement(header ? "th" : "td");
  cell.textContent = String(value);
  row.appendChild(cell);
}

function renderHotlist(doc, hotlist) {
  doc.getElementById("hotlist-market").textContent = hotlist.market.toUpperCase();
  doc.getElementById("hotlist-phase").textContent = hotlist.phase;
  doc.getElementById("hotlist-status").textContent = hotlist.status;
  doc.getElementById("hotlist-count").textContent = hotlist.mode === "ticker_rank"
    ? `Board size: ${hotlist.totalCount}`
    : `${hotlist.count} of ${hotlist.totalCount} on the board`;
  doc.getElementById("hotlist-truncated").textContent = hotlist.mode === "ticker_rank"
    ? `Truncated: ${hotlist.truncated}`
    : "";
  doc.getElementById("hotlist-preview").textContent = hotlist.mode !== "ticker_rank" ? ""
    : hotlist.totalCount === 0 ? "No names on the board right now"
    : hotlist.truncated ? `Showing the top ${hotlist.rows.length} of ${hotlist.totalCount} on the board`
    : "";
  const asOf = doc.getElementById("hotlist-as-of");
  asOf.textContent = hotlist.asOf;
  asOf.setAttribute("datetime", hotlist.asOf);
  const rows = hotlist.rows.map(entry => {
    const item = doc.createElement("li");
    const link = doc.createElement("a");
    link.textContent = `${entry.ticker} · Rank ${entry.selectionRank}`;
    link.setAttribute("href", entry.link);
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer");
    item.appendChild(link);
    return item;
  });
  doc.getElementById("hotlist-rows").replaceChildren(...rows);
  doc.getElementById("hotlist-footer").textContent = hotlist.mode === "ticker_rank"
    ? "Open SurgeFlow for the full board. Ranks are SurgeFlow's own."
    : "Open SurgeFlow for the current names.";
  doc.getElementById("open-hotlist").setAttribute("href", hotlist.link);
}

function renderFreshness(doc, freshness) {
  const staleLabel = freshness.tradingDaysStale === 1 ? "trading day" : "trading days";
  doc.getElementById("data-freshness").textContent = `${freshness.status}. Latest: ${freshness.latestDate}. Expected: ${freshness.expectedLatest}. ${freshness.tradingDaysStale} ${staleLabel} stale.`;
}

// Display only: the parsed rows keep the published value.
function displayValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return value;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: Math.abs(value) < 1000 ? 2 : 0 }).format(value);
}

function renderMacro(doc, macro) {
  const body = doc.getElementById("macro-rows");
  const rows = macro.rows.map(indicator => {
    const row = doc.createElement("tr");
    appendCell(doc, row, indicator.unit ? `${indicator.indicator} (${indicator.unit})` : indicator.indicator);
    appendCell(doc, row, indicator.country);
    appendCell(doc, row, displayValue(indicator.value));
    appendCell(doc, row, indicator.date.slice(0, 10));
    appendCell(doc, row, indicator.source);
    return row;
  });
  body.replaceChildren(...rows);
  const credits = macro.credits.map(credit => {
    const line = doc.createElement("p");
    line.textContent = credit;
    return line;
  });
  doc.getElementById("macro-credits").replaceChildren(...credits);
}

function clearRenderedData(doc) {
  for (const id of [
    "hotlist-market", "hotlist-phase", "hotlist-status", "hotlist-count", "hotlist-truncated",
    "hotlist-preview", "hotlist-as-of", "hotlist-footer", "data-freshness",
  ]) {
    doc.getElementById(id).textContent = "";
  }
  doc.getElementById("hotlist-as-of").removeAttribute("datetime");
  doc.getElementById("open-hotlist").removeAttribute("href");
  doc.getElementById("hotlist-rows").replaceChildren();
  doc.getElementById("macro-rows").replaceChildren();
  doc.getElementById("macro-credits").replaceChildren();
  doc.getElementById("freshness-section").hidden = true;
}

async function refreshPopup(market, doc = document) {
  const status = doc.getElementById("status");
  clearRenderedData(doc);
  status.hidden = false;
  status.textContent = "Loading SurgeFlow data…";
  try {
    const data = await loadPopupData(market);
    renderHotlist(doc, data.hotlist);
    renderFreshness(doc, data.freshness);
    doc.getElementById("freshness-section").hidden = false;
    renderMacro(doc, data.macro);
    status.textContent = "";
    status.hidden = true;
  } catch {
    clearRenderedData(doc);
    status.textContent = SURGEFLOW_ERROR_MESSAGE;
    status.hidden = false;
  }
}

function initializePopup(doc = document) {
  let activeMarket = "us";
  let loading = null;
  const marketButtons = [...doc.querySelectorAll("[data-market]")];
  const tabs = [...doc.querySelectorAll('[role="tab"]')];

  // Ignore clicks while loading instead of disabling the buttons, so keyboard focus stays on the pressed market.
  function refresh() {
    loading = refreshPopup(activeMarket, doc).finally(() => { loading = null; });
    return loading;
  }

  for (const button of marketButtons) {
    button.addEventListener("click", () => {
      if (loading) return;
      activeMarket = button.getAttribute("data-market");
      for (const candidate of marketButtons) candidate.setAttribute("aria-pressed", String(candidate === button));
      refresh();
    });
  }

  function selectTab(selected) {
    for (const tab of tabs) {
      const isSelected = tab === selected;
      tab.setAttribute("aria-selected", String(isSelected));
      tab.tabIndex = isSelected ? 0 : -1;
      doc.getElementById(tab.getAttribute("aria-controls")).hidden = !isSelected;
    }
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", event => {
      let nextIndex;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index + tabs.length - 1) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === undefined) return;
      event.preventDefault();
      selectTab(tabs[nextIndex]);
      tabs[nextIndex].focus();
    });
  });

  return refresh();
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", () => initializePopup());
