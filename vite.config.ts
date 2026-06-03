import { createHmac } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv, type Plugin } from "vite";
import { WebSocket, WebSocketServer } from "ws";

const DEFAULT_SYMBOL = "BNBUSDT";
const DASHBOARD_SOCKET_PATH = "/api/binance/bnb-dashboard/socket";

type Env = Record<string, string>;
type ServerTimeResponse = {
  serverTime: number;
};

const TIME_SYNC_INTERVAL_MS = 30_000;
let cachedTimeOffsetMs = 0;
let lastTimeSyncAt = 0;

function sendJson(res: ServerResponse, status: number, body: unknown) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
}

function socketMessage(type: string, payload: unknown) {
  return JSON.stringify({ type, payload });
}

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

type PositionRisk = {
  symbol?: string;
  positionAmt?: string;
  notional?: string;
  unRealizedProfit?: string;
};

function normalizeSymbol(symbol?: string) {
  const normalized = symbol?.trim().toUpperCase();
  return normalized && /^[A-Z0-9_]+$/.test(normalized) ? normalized : DEFAULT_SYMBOL;
}

function chooseDashboardPosition(activePositions: PositionRisk[]) {
  return activePositions.reduce<PositionRisk | null>((selected, position) => {
    if (!selected) {
      return position;
    }

    const selectedExposure = Math.abs(Number(selected.notional ?? selected.positionAmt ?? 0));
    const positionExposure = Math.abs(Number(position.notional ?? position.positionAmt ?? 0));
    return positionExposure > selectedExposure ? position : selected;
  }, null);
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
  const dashboardPosition = chooseDashboardPosition(activePositions);

  return {
    configured: true,
    position: dashboardPosition,
    positions: positionRisk,
    activePositions,
    account
  };
}

async function getMarketData(baseUrl: URL, symbol: string) {
  const encodedSymbol = encodeURIComponent(symbol);

  const [ticker, premiumIndex, openInterest, klines] = await Promise.all([
    fetchJson(new URL(`/fapi/v1/ticker/24hr?symbol=${encodedSymbol}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/premiumIndex?symbol=${encodedSymbol}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/openInterest?symbol=${encodedSymbol}`, baseUrl)),
    fetchJson(new URL(`/fapi/v1/klines?symbol=${encodedSymbol}&interval=5m&limit=48`, baseUrl))
  ]);

  return {
    ticker,
    premiumIndex,
    openInterest,
    klines
  };
}

async function getDashboardData(env: Env) {
  const rawBaseUrl = envValue(env, "BINANCE_BASE_URL", "https://fapi.binance.com");
  let baseUrl: URL;

  try {
    baseUrl = new URL(rawBaseUrl);
  } catch {
    throw new Error(`Invalid BINANCE_BASE_URL: ${rawBaseUrl}`);
  }

  if (envValue(env, "BINANCE_TLS_INSECURE") === "true") {
    process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
  }

  const apiKey = envValue(env, "BINANCE_API_KEY");
  const apiSecret = envValue(env, "BINANCE_API_SECRET");
  const hasPrivateCredentials = Boolean(apiKey && apiSecret);
  const recvWindow = envValue(env, "BINANCE_RECV_WINDOW", "5000");
  const timeOffsetMs = await resolveTimeOffset(baseUrl);
  const privateData = hasPrivateCredentials
    ? await getPrivateAccountData(baseUrl, apiKey, apiSecret, timeOffsetMs, recvWindow)
    : { configured: false, position: null, positions: [], activePositions: [], account: null };
  const symbol = normalizeSymbol(privateData.position?.symbol);
  const marketData = await getMarketData(baseUrl, symbol);

  return {
    symbol,
    updatedAt: new Date().toISOString(),
    market: marketData,
    private: privateData
  };
}

function binanceApiPlugin(env: Env): Plugin {
  return {
    name: "tradingclaw-binance-readonly-api",
    configureServer(server) {
      const socketIntervalMs = Math.max(Number(env.DASHBOARD_SOCKET_INTERVAL_MS || 2500), 1500);
      const wss = new WebSocketServer({ noServer: true });
      const clients = new Set<WebSocket>();

      async function sendDashboard(ws: WebSocket) {
        try {
          ws.send(socketMessage("dashboard", await getDashboardData(env)));
        } catch (error) {
          ws.send(
            socketMessage("error", {
              error: error instanceof Error ? error.message : "Unable to load Binance data"
            })
          );
        }
      }

      async function broadcastDashboard() {
        if (!clients.size) {
          return;
        }

        try {
          const payload = socketMessage("dashboard", await getDashboardData(env));
          for (const client of clients) {
            if (client.readyState === WebSocket.OPEN) {
              client.send(payload);
            }
          }
        } catch (error) {
          const payload = socketMessage("error", {
            error: error instanceof Error ? error.message : "Unable to load Binance data"
          });
          for (const client of clients) {
            if (client.readyState === WebSocket.OPEN) {
              client.send(payload);
            }
          }
        }
      }

      wss.on("connection", (ws) => {
        clients.add(ws);
        sendDashboard(ws);

        ws.on("message", (message) => {
          if (message.toString() === "refresh") {
            sendDashboard(ws);
          }
        });

        ws.on("close", () => {
          clients.delete(ws);
        });
      });

      server.httpServer?.on("upgrade", (req, socket, head) => {
        const url = req.url ? new URL(req.url, "http://localhost") : null;
        if (url?.pathname !== DASHBOARD_SOCKET_PATH) {
          return;
        }

        wss.handleUpgrade(req, socket, head, (ws) => {
          wss.emit("connection", ws, req);
        });
      });

      const timer = setInterval(broadcastDashboard, socketIntervalMs);
      server.httpServer?.on("close", () => {
        clearInterval(timer);
        wss.close();
      });

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
    plugins: [tailwindcss(), react(), binanceApiPlugin(env)]
  };
});
