const MARKETS = ["us", "cn", "jp", "hk"];
const SNAPSHOTS = [
  "momentum-hotlist",
  "macro-indicators",
  "news-sentiment",
  "factor-overview",
  "data-freshness",
];

export class SurgeFlowError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = new.target.name;
    if (options.cause !== undefined) this.cause = options.cause;
  }
}

export class SurgeFlowNetworkError extends SurgeFlowError {}

export class SurgeFlowTimeoutError extends SurgeFlowNetworkError {}

export class SurgeFlowResponseError extends SurgeFlowError {}

export class SurgeFlowApiError extends SurgeFlowError {
  constructor(statusCode, message, payload = undefined) {
    super(message);
    this.statusCode = statusCode;
    this.payload = payload;
  }
}

export class SurgeFlow {
  constructor({ baseUrl = "https://surgeflows.capital", timeout = 30000, fetch: fetchImpl = globalThis.fetch } = {}) {
    if (!Number.isFinite(timeout) || timeout <= 0) throw new TypeError("timeout must be greater than zero");
    if (typeof fetchImpl !== "function") throw new TypeError("Node 18 or later provides fetch");
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.timeout = timeout;
    this._fetch = (...args) => fetchImpl(...args);
  }

  async publicSnapshot(snapshotId, { market, days, responseFormat = "json" } = {}) {
    if (!SNAPSHOTS.includes(snapshotId)) throw new TypeError(`Unknown snapshot: ${snapshotId}`);
    this._validateResponseFormat(responseFormat);
    const params = {};
    if (market !== undefined) {
      this._validateMarket(market);
      params.market = market;
    }
    if (days !== undefined) {
      this._validateDays(days);
      params.days = days;
    }
    return this._request(`/api/public/snapshots/${snapshotId}.${responseFormat}`, { params, responseFormat });
  }

  async momentumHotlist(market, options = {}) {
    this._validateMarket(market);
    return this.publicSnapshot("momentum-hotlist", { market, responseFormat: options.responseFormat });
  }

  macroIndicators(options = {}) {
    return this.publicSnapshot("macro-indicators", { responseFormat: options.responseFormat });
  }

  async newsSentiment(days = 30, options = {}) {
    this._validateDays(days);
    return this.publicSnapshot("news-sentiment", { days, responseFormat: options.responseFormat });
  }

  /** Read the frozen baseline with data to 11 April 2026, not updated daily.
   * For current daily factor data, use keyless GET https://surgeflows.capital/api/factor-reference/latest.
   */
  async factorOverview(market, options = {}) {
    this._validateMarket(market);
    return this.publicSnapshot("factor-overview", { market, responseFormat: options.responseFormat });
  }

  dataFreshness(options = {}) {
    return this.publicSnapshot("data-freshness", { responseFormat: options.responseFormat });
  }

  memberMe(apiKey) {
    return this._request("/api/v1/me", { apiKey });
  }

  async memberHotlist(market, apiKey) {
    this._validateMarket(market);
    return this._request(`/api/v1/markets/${market}/hotlist`, { apiKey });
  }

  async _request(path, { apiKey, params = {}, responseFormat = "json" } = {}) {
    this._validateResponseFormat(responseFormat);
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
    const headers = {
      Accept: responseFormat === "json" ? "application/json" : "text/csv",
      "User-Agent": "surgeflow-javascript/0.1.0",
    };
    if (apiKey !== undefined) {
      if (typeof apiKey !== "string" || !apiKey.trim()) throw new TypeError("apiKey must be a non-empty string");
      // Reject before fetch, whose header errors would echo the key.
      if (/[\x00-\x1f\x7f]/.test(apiKey)) throw new TypeError("apiKey contains a control character; paste the key again");
      headers.Authorization = `Bearer ${apiKey}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let response;
    let text;
    try {
      response = await this._fetch(url, {
        method: "GET",
        headers,
        signal: controller.signal,
      });
      text = await response.text();
    } catch (error) {
      if (controller.signal.aborted) {
        throw new SurgeFlowTimeoutError("The SurgeFlow request timed out", { cause: error });
      }
      throw new SurgeFlowNetworkError("The SurgeFlow request failed", { cause: error });
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      const payload = parseObject(text);
      const message = errorText(payload) || `SurgeFlow returned HTTP ${response.status}`;
      throw new SurgeFlowApiError(response.status, message, payload);
    }
    if (responseFormat === "csv") return text;

    const payload = parseObject(text);
    if (!payload) throw new SurgeFlowResponseError("SurgeFlow returned an invalid JSON object");
    if (payload.ok === false) {
      const detail = errorText(payload);
      throw new SurgeFlowResponseError(`The SurgeFlow response contains ok=false${detail ? `: ${detail}` : ""}`);
    }
    return payload;
  }

  _validateMarket(market) {
    if (!MARKETS.includes(market)) throw new TypeError("market must be us, cn, jp, or hk");
  }

  _validateDays(days) {
    if (!Number.isInteger(days) || days < 1 || days > 365) {
      throw new TypeError("days must be an integer from 1 through 365");
    }
  }

  _validateResponseFormat(responseFormat) {
    if (!["json", "csv"].includes(responseFormat)) throw new TypeError("responseFormat must be json or csv");
  }
}

function errorText(payload) {
  let detail = payload?.error || payload?.message;
  if (detail && typeof detail === "object") {
    detail = [detail.code, detail.message].filter(Boolean).join(": ") || undefined;
  }
  return typeof detail === "string" ? detail : undefined;
}

function parseObject(text) {
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value) ? value : undefined;
  } catch {
    return undefined;
  }
}
