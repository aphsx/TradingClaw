const ENGINE_HTTP_URL =
  process.env.TRADING_ENGINE_HTTP_URL ||
  process.env.NEXT_PUBLIC_ENGINE_HTTP_URL ||
  "http://localhost:8081";

export function getEngineHttpUrl(): string {
  return ENGINE_HTTP_URL;
}
