import {
  AllocatorReportCardResponse,
  AllocatorStatusResponse,
  BootstrapResponse,
  CandidateDetailResponse,
  DriftImpactResponse,
  DriftSensitivityRequest,
  DriftSensitivityResponse,
  MirrorChallengeRequest,
  MirrorChallengeResponse,
  MirrorConfirmRequest,
  MirrorConfirmResponse,
  MirrorIntentPreviewResponse,
  TriageIntentCreateRequest,
  TriageIntentCreateResponse
} from "./types";

const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8000";
const DEFAULT_GATEWAY_AUTH_HEADER = "X-Aeternus-Key";

let bootstrapCache: BootstrapResponse | null = null;
let bootstrapEtag = "";

function getGatewayBaseUrl(): string {
  const configured = process.env.EXPO_PUBLIC_OPERATOR_GATEWAY_URL;
  return (configured && configured.trim()) || DEFAULT_GATEWAY_URL;
}

function getGatewayAuthHeaderName(): string {
  const configured = process.env.EXPO_PUBLIC_OPERATOR_GATEWAY_AUTH_HEADER;
  return (configured && configured.trim()) || DEFAULT_GATEWAY_AUTH_HEADER;
}

function getGatewayApiKey(): string {
  return (process.env.EXPO_PUBLIC_OPERATOR_GATEWAY_API_KEY || "").trim();
}

function buildAuthHeaders(): Record<string, string> {
  const apiKey = getGatewayApiKey();
  if (!apiKey) {
    return {};
  }
  return { [getGatewayAuthHeaderName()]: apiKey };
}

async function fetchJson<T>(path: string): Promise<T> {
  const baseUrl = getGatewayBaseUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    headers: buildAuthHeaders()
  });
  if (!response.ok) {
    throw new Error(`Gateway request failed (${response.status}) for ${path}`);
  }
  return (await response.json()) as T;
}

async function postJson<TResponse, TBody extends object>(
  path: string,
  body: TBody
): Promise<TResponse> {
  const baseUrl = getGatewayBaseUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeaders()
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const maybeJson = await response.json().catch(() => null);
    const detail = maybeJson && typeof maybeJson.detail === "string"
      ? maybeJson.detail
      : `Gateway request failed (${response.status}) for ${path}`;
    throw new Error(detail);
  }
  return (await response.json()) as TResponse;
}

export async function fetchBootstrap(): Promise<BootstrapResponse> {
  const baseUrl = getGatewayBaseUrl();
  const headers: Record<string, string> = buildAuthHeaders();
  if (bootstrapEtag) {
    headers["If-None-Match"] = bootstrapEtag;
  }
  const response = await fetch(`${baseUrl}/ops/bootstrap`, { headers });
  if (response.status === 304 && bootstrapCache) {
    return bootstrapCache;
  }
  if (!response.ok) {
    throw new Error(`Gateway request failed (${response.status}) for /ops/bootstrap`);
  }
  const payload = (await response.json()) as BootstrapResponse;
  const etag = response.headers.get("etag");
  if (etag) {
    bootstrapEtag = etag;
  }
  bootstrapCache = payload;
  return payload;
}

export async function createTriageIntent(
  payload: TriageIntentCreateRequest
): Promise<TriageIntentCreateResponse> {
  return postJson<TriageIntentCreateResponse, TriageIntentCreateRequest>(
    "/ops/triage-intent",
    payload
  );
}

export async function fetchCandidateDetail(symbol: string): Promise<CandidateDetailResponse> {
  const safeSymbol = encodeURIComponent(symbol.trim().toUpperCase());
  return fetchJson<CandidateDetailResponse>(`/ops/candidates/${safeSymbol}`);
}

export async function fetchAllocatorStatus(
  sinceMinutes = 120
): Promise<AllocatorStatusResponse> {
  return fetchJson<AllocatorStatusResponse>(
    `/ops/allocator-intents/status?since_minutes=${Math.max(1, Math.floor(sinceMinutes))}`
  );
}

export async function fetchAllocatorReportCard(
  lookbackDays = 7
): Promise<AllocatorReportCardResponse> {
  return fetchJson<AllocatorReportCardResponse>(
    `/ops/allocator/report-card?lookback_days=${Math.max(1, Math.floor(lookbackDays))}`
  );
}

export async function createMirrorChallenge(
  intentId: string,
  payload: MirrorChallengeRequest = {}
): Promise<MirrorChallengeResponse> {
  const safeIntentId = encodeURIComponent(intentId.trim());
  return postJson<MirrorChallengeResponse, MirrorChallengeRequest>(
    `/ops/mirror-intents/${safeIntentId}/challenge`,
    payload
  );
}

export async function confirmMirrorIntent(
  intentId: string,
  payload: MirrorConfirmRequest
): Promise<MirrorConfirmResponse> {
  const safeIntentId = encodeURIComponent(intentId.trim());
  return postJson<MirrorConfirmResponse, MirrorConfirmRequest>(
    `/ops/mirror-intents/${safeIntentId}/confirm`,
    payload
  );
}

export async function fetchMirrorIntentPreview(
  intentId: string
): Promise<MirrorIntentPreviewResponse> {
  const safeIntentId = encodeURIComponent(intentId.trim());
  return fetchJson<MirrorIntentPreviewResponse>(`/ops/mirror-intents/${safeIntentId}`);
}

export async function fetchDriftSensitivity(): Promise<DriftSensitivityResponse> {
  return fetchJson<DriftSensitivityResponse>("/ops/settings/drift-sensitivity");
}

export async function updateDriftSensitivity(
  payload: DriftSensitivityRequest
): Promise<DriftSensitivityResponse> {
  return postJson<DriftSensitivityResponse, DriftSensitivityRequest>(
    "/ops/settings/drift-sensitivity",
    payload
  );
}

export async function fetchDriftImpact(maxItems = 8): Promise<DriftImpactResponse> {
  return fetchJson<DriftImpactResponse>(`/ops/drift-impact?max_items=${Math.max(1, Math.floor(maxItems))}`);
}
