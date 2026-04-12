"""
Dylan O'Neill VIX Futures Strategy — Expert Advisor
Monitors ES, NQ, and VIX for high-probability setups and executes
trades with manual confirmation.
"""

import os
import time
from dotenv import load_dotenv

from bot.connection import connect, disconnect
from bot.strategy  import get_snapshot, evaluate, print_dashboard
from bot.trader    import execute

load_dotenv()

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))

# Track last signal type to avoid spamming the same alert repeatedly
_last_signal_type = None


def run():
    global _last_signal_type

    print("\n  VIX Futures Strategy EA — Starting scanner...")
    print(f"  Scan interval: every {SCAN_INTERVAL}s  |  Press Ctrl+C to stop\n")

    while True:
        try:
            snap   = get_snapshot()
            signal = evaluate(snap)

            print_dashboard(snap)

            if signal and signal.signal_type != _last_signal_type:
                _last_signal_type = signal.signal_type
                execute(signal)
            elif signal is None:
                _last_signal_type = None
                print("  No setup detected — monitoring...")

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n  Stopped by user.")
            break
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(SCAN_INTERVAL)


def main():
    try:
        connect()
        run()
    finally:
        disconnect()


if __name__ == "__main__":
    main()
