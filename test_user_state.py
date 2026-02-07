from __future__ import annotations

import os

from dotenv import load_dotenv

from hyperliquid.info import Info


def main() -> None:
    # Load env
    load_dotenv(".env.local")

    base_url = os.getenv("NEURABOT_HL_BASE_URL", "https://api.hyperliquid.xyz")
    user = os.getenv("NEURABOT_WALLET_ADDRESS")

    print("Base URL:", base_url)
    print("User address:", user)

    if not user:
        print("ERROR: NEURABOT_WALLET_ADDRESS is not set")
        return

    info = Info(base_url=base_url, skip_ws=True)

    print("\nCalling info.user_state(...) directly...\n")
    try:
        state = info.user_state(address=user)
        print("user_state response type:", type(state))
        print("user_state keys:", list(state.keys())[:20])
        print("marginSummary:", state.get("marginSummary"))
    except Exception as e:
        # Print full error repr so we see status code + message
        print("ERROR while calling user_state:", repr(e))


if __name__ == "__main__":
    main()
