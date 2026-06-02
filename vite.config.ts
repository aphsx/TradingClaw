import { createHmac } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

const SYMBOL = "BNBUSDT";

type Env = Record<string, string>;

function sendJson(res: ServerResponse, status: number, body: unknown) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
}

async function fetchJson<T>(url: URL, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(url, init);
  } catch (error) {
    const maybeCause = error instanceof Error ? (error as Error & { cause?: unknown }).cause : null;
    const cause =
      maybeCause instanceof Error ? `: ${maybeCause.message}` : "";
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

function signedUrl(baseUrl: string, path: string, secret: string, params: Record<string, string>) {
  const url = new URL(path, baseUrl);
  const searchParams = new URLSearchParams({
    ...params,
    recvWindow: "5000",
    timestamp: Date.now().toString()
  });
  const signature = createHmac("sha256", secret).update(searchParams.toString()).digest("hex");
  searchParams.set("signature", signature);
  url.search = searchParams.toString();
  return url;
}

type PositionRisk = {
  symbol?: string;
  positionAmt?: string;
  unRealizedProfit?: string;
};

async function getPrivateAccountData(baseUrl: string, apiKey: string, apiSecret: string) {
  const positionUrl = signedUrl(baseUrl, "/fapi/v2/positionRisk", apiSecret, {});
  const accountUrl = signedUrl(baseUrl, "/fapi/v2/account", apiSecret, {});
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
  const baseUrl = env.BINANCE_BASE_URL || "https://fapi.binance.com";

  if (env.BINANCE_TLS_INSECURE === "true") {
    process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
  }

  const [ticker, premiumIndex, openInterest, klines] = await Promise.all([
    fetchJson(new URL(`/fapi/v1/ticker/24hr?symbol=${SYMBOL}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/premiumIndex?symbol=${SYMBOL}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/openInterest?symbol=${SYMBOL}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/klines?symbol=${SYMBOL}&interval=5m&limit=48`, baseUrl))
  ]);

  const hasPrivateCredentials = Boolean(env.BINANCE_API_KEY && env.BINANCE_API_SECRET);
  const privateData = hasPrivateCredentials
    ? await getPrivateAccountData(baseUrl, env.BINANCE_API_KEY, env.BINANCE_API_SECRET)
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

function binanceApiPlugin(env: Env): Plugin {
  return {
    name: "tradingclaw-binance-readonly-api",
    configureServer(server) {
      server.middlewares.use("/api/binance/bnb-dashboard", async (req: IncomingMessage, res: ServerResponse) => {
        if (req.method !== "GET") {
          sendJson(res, 405, { error: "Method not allowed" });
          return;
        }

        try {
          sendJson(res, 200, await getDashboardData(env));
        } catch (error) {
          sendJson(res, 502, {
            error: error instanceof Error ? error.message : "Unable to load Binance data"
          });
        }
      });
    }
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react(), binanceApiPlugin(env)]
  };
});
