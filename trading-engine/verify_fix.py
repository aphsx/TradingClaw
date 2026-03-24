from data.ccxt_client import get_balance
from config import EXCHANGE_NAME, IS_DEMO

print(f"Testing via CCXT_CLIENT: {EXCHANGE_NAME.upper()} | Demo: {IS_DEMO}")

try:
    res = get_balance()
    print("\n--- Success! ---")
    print(f"Balance Data: {res}")
except Exception as e:
    print(f"\n--- Error ---")
    print(str(e))
