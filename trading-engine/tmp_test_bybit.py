import hashlib
import hmac
import os
import time

import ccxt
import requests
from dotenv import load_dotenv


load_dotenv()

exchange_raw = os.getenv("EXCHANGE", "bybit").lower()
exchange_name = exchange_raw.split("_")[0]  # bybit_demo -> bybit
api_key = os.getenv(f"{exchange_name.upper()}_API_KEY", "")
secret_key = os.getenv(f"{exchange_name.upper()}_SECRET_KEY", "")
is_demo = (
    os.getenv("IS_DEMO", "false").lower() == "true"
    or "_demo" in exchange_raw
    or "_testnet" in exchange_raw
)
use_futures = os.getenv("USE_FUTURES", "false").lower() == "true"

print(f"Testing {exchange_raw.upper()} | Base Exchange: {exchange_name.upper()} | Demo: {is_demo} | Futures: {use_futures}")
print(f"API Key: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else ''}")

try:
    exchange_class = getattr(ccxt, exchange_name)
    exchange = exchange_class(
        {
            "apiKey": api_key,
            "secret": secret_key,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap" if use_futures else "spot",
            },
        }
    )

    if is_demo:
        if exchange_name == "bybit":
            exchange.options["demo"] = True
            print("Bybit Demo Trading mode enabled via options['demo']")
        else:
            exchange.set_sandbox_mode(True)
            print("Sandbox mode enabled")

    print(f"Base URL: {exchange.urls['api']}")

    # Manual debug with requests to verify Bybit headers/signature.
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    path = "/v5/account/wallet-balance"
    query = "accountType=UNIFIED"
    param_str = timestamp + api_key + recv_window + query
    signature = hmac.new(bytes(secret_key, "utf-8"), param_str.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
        "X-DEMO-TRADING": "1" if is_demo else "0",
    }

    url = "https://api-demo.bybit.com" + path + "?" + query if is_demo else "https://api.bybit.com" + path + "?" + query
    print(f"Testing manual request to: {url}")
    res = requests.get(url, headers=headers)
    print(f"Manual Response: {res.status_code} {res.text}")

    balance = exchange.fetch_balance()
    print("\n--- Success! ---")
    if "USDT" in balance:
        print(f"USDT Balance: {balance['USDT']}")
    else:
        print("USDT not found, available assets:")
        print([k for k, v in balance.items() if isinstance(v, dict) and v.get("total", 0) > 0])

except Exception as e:
    print("\n--- Error ---")
    print(str(e))
