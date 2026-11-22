export type Market = "us" | "cn" | "jp" | "hk";
export type SnapshotId =
  | "momentum-hotlist"
  | "macro-indicators"
  | "news-sentiment"
  | "factor-overview"
  | "data-freshness";
export type ResponseFormat = "json" | "csv";
export type JsonObject = Record<string, unknown>;

export interface SurgeFlowOptions {
  baseUrl?: string;
  timeout?: number;
  fetch?: typeof globalThis.fetch;
}

export interface SnapshotOptions {
  responseFormat?: ResponseFormat;
}

export interface PublicSnapshotOptions extends SnapshotOptions {
  market?: Market;
  days?: number;
}

export class SurgeFlowError extends Error {
  constructor(message: string, options?: { cause?: unknown });
  cause?: unknown;
}

export class SurgeFlowNetworkError extends SurgeFlowError {}
export class SurgeFlowTimeoutError extends SurgeFlowNetworkError {}
export class SurgeFlowResponseError extends SurgeFlowError {}

export class SurgeFlowApiError extends SurgeFlowError {
  constructor(statusCode: number, message: string, payload?: JsonObject);
  statusCode: number;
  payload?: JsonObject;
}

export class SurgeFlow {
  constructor(options?: SurgeFlowOptions);
  baseUrl: string;
  timeout: number;

  publicSnapshot(snapshotId: SnapshotId, options?: PublicSnapshotOptions): Promise<JsonObject | string>;
  momentumHotlist(market: Market, options?: SnapshotOptions): Promise<JsonObject | string>;
  macroIndicators(options?: SnapshotOptions): Promise<JsonObject | string>;
  newsSentiment(days?: number, options?: SnapshotOptions): Promise<JsonObject | string>;
  /** Frozen baseline with data to 11 April 2026, not updated daily.
   * Current daily factor data: keyless GET https://surgeflows.capital/api/factor-reference/latest.
   */
  factorOverview(market: Market, options?: SnapshotOptions): Promise<JsonObject | string>;
  dataFreshness(options?: SnapshotOptions): Promise<JsonObject | string>;
  memberMe(apiKey: string): Promise<JsonObject>;
  memberHotlist(market: Market, apiKey: string): Promise<JsonObject>;
}
