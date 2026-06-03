import { createHmac } from "node:crypto";

const SYMBOL = "BNBUSDT";

type Env = Record<string, string | undefined>;
type ServerTimeResponse = {
  serverTime: number;
};

const TIME_SYNC_INTERVAL_MS = 30_000;
let cachedTimeOffsetMs = 0;
let lastTimeSyncAt = 0;

type VercelRequest = {
  method?: string;
};

type VercelResponse = {
  status: (statusCode: number) => {
    json: (body: unknown) => void;
  };
};

type PositionRisk = {
  symbol?: string;
  positionAmt?: string;
  unRealizedProfit?: string;
};

function envValue(env: Env, key: string, fallback = "") {
  const rawValue = env[key] || fallback;
  return rawValue.trim().replace(/^['"]|['"]$/g, "").replace(new RegExp(`^${key}=`), "").trim();
}

async function fetchJson<T>(url: URL, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(url.toString(), init);
  } catch (error) {
    const maybeCause = error instanceof Error ? (error as Error & { cause?: unknown }).cause : null;
    const cause = maybeCause instanceof Error ? `: ${maybeCause.message}` : "";
    const message = error instanceof Error ? error.message : "request failed";
    throw new Error(`Network request failed for ${url.hostname}: ${message}${cause}`);
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      payload && typeof payload === "object" && "msg" in payload
        ? String(payload.msg)
        : `Binance request failed with ${response.status}`;
    throw new Error(message);
  }

  return payload as T;
}

function getBaseUrl(env: Env) {
  const rawBaseUrl = envValue(env, "BINANCE_BASE_URL", "https://fapi.binance.com");

  try {
    return new URL(rawBaseUrl);
  } catch {
    throw new Error(`Invalid BINANCE_BASE_URL: ${rawBaseUrl}`);
  }
}

async function resolveTimeOffset(baseUrl: URL) {
  if (Date.now() - lastTimeSyncAt < TIME_SYNC_INTERVAL_MS) {
    return cachedTimeOffsetMs;
  }

  try {
    const payload = await fetchJson<ServerTimeResponse>(new URL("/fapi/v1/time", baseUrl));
    cachedTimeOffsetMs = payload.serverTime - Date.now();
  } catch {
    // Keep the last offset to avoid failing requests if time sync is unavailable.
  } finally {
    lastTimeSyncAt = Date.now();
  }

  return cachedTimeOffsetMs;
}

function signedUrl(
  baseUrl: URL,
  path: string,
  secret: string,
  params: Record<string, string>,
  timeOffsetMs: number,
  recvWindow: string
) {
  const url = new URL(path, baseUrl);
  const searchParams = new URLSearchParams({
    ...params,
    recvWindow,
    timestamp: (Date.now() + timeOffsetMs).toString()
  });
  const signature = createHmac("sha256", secret).update(searchParams.toString()).digest("hex");
  searchParams.set("signature", signature);
  url.search = searchParams.toString();
  return url;
}

async function getPrivateAccountData(
  baseUrl: URL,
  apiKey: string,
  apiSecret: string,
  timeOffsetMs: number,
  recvWindow: string
) {
  const positionUrl = signedUrl(
    baseUrl,
    "/fapi/v2/positionRisk",
    apiSecret,
    {},
    timeOffsetMs,
    recvWindow
  );
  const accountUrl = signedUrl(baseUrl, "/fapi/v2/account", apiSecret, {}, timeOffsetMs, recvWindow);
  const headers = { "X-MBX-APIKEY": apiKey };

  const [positionRisk, account] = await Promise.all([
    fetchJson<PositionRisk[]>(positionUrl, { headers }),
    fetchJson(accountUrl, { headers })
  ]);
  const activePositions = positionRisk.filter((position) => Number(position.positionAmt ?? 0) !== 0);
  const bnbPosition = positionRisk.find((position) => position.symbol === SYMBOL) ?? null;

  return {
    configured: true,
    position: bnbPosition,
    positions: positionRisk,
    activePositions,
    account
  };
}

async function getDashboardData(env: Env) {
  const baseUrl = getBaseUrl(env);

  const [ticker, premiumIndex, openInterest, klines] = await Promise.all([
    fetchJson(new URL(`/fapi/v1/ticker/24hr?symbol=${SYMBOL}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/premiumIndex?symbol=${SYMBOL}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/openInterest?symbol=${SYMBOL}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/klines?symbol=${SYMBOL}&interval=5m&limit=48`, baseUrl))
  ]);

  const apiKey = envValue(env, "BINANCE_API_KEY");
  const apiSecret = envValue(env, "BINANCE_API_SECRET");
  const hasPrivateCredentials = Boolean(apiKey && apiSecret);
  const recvWindow = envValue(env, "BINANCE_RECV_WINDOW", "5000");
  const timeOffsetMs = await resolveTimeOffset(baseUrl);
  const privateData = hasPrivateCredentials
    ? await getPrivateAccountData(baseUrl, apiKey, apiSecret, timeOffsetMs, recvWindow)
    : { configured: false, position: null, positions: [], activePositions: [], account: null };

  return {
    symbol: SYMBOL,
    updatedAt: new Date().toISOString(),
    market: {
      ticker,
      premiumIndex,
      openInterest,
      klines
    },
    private: privateData
  };
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "GET") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  try {
    res.status(200).json(await getDashboardData(process.env));
  } catch (error) {
    res.status(502).json({
      error: error instanceof Error ? error.message : "Unable to load Binance data"
    });
  }
}
