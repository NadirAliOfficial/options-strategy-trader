import pandas as pd
from datetime import datetime
import pytz

# ---------------- Milestone 1: Strategy Logic & Candle Validation ----------------

IGNORE_MINUTES = 15  # ignore first 15 minutes

def filter_bars(df):
    """Filter out the first IGNORE_MINUTES from the start of the DataFrame."""
    cutoff = df.index[0] + pd.Timedelta(minutes=IGNORE_MINUTES)
    return df[df.index >= cutoff]

def find_trigger(df):
    """
    Identify the trigger candle based on wick-break logic:
    - Determine direction of previous candle (up/down)
    - If up and current close > previous high, trigger
    - If down and current close < previous low, trigger
    """
    df2 = filter_bars(df)
    for i in range(1, len(df2)):
        prev = df2.iloc[i-1]
        curr = df2.iloc[i]
        direction = 'up' if prev.close > prev.open else 'down'
        if direction == 'up' and curr.close > prev.high:
            return df2.index[i]
        if direction == 'down' and curr.close < prev.low:
            return df2.index[i]
    return None

def calculate_contracts(price_usd):
    """
    Dynamic sizing: $10,000 position divided by (price * 100 shares per contract).
    Returns integer number of contracts.
    """
    if price_usd <= 0:
        return 0
    return int(10000 / (price_usd * 100))


# ---------------------- Testing Milestone 1 ----------------------

if __name__ == "__main__":
    # Synthetic 5-min bar data (timestamps in UTC for simplicity)
    times = pd.date_range(start="2025-04-21 07:00", periods=6, freq="5T", tz="UTC")
    data = {
        'open':  [100, 102, 104, 103, 105, 106],
        'high':  [102, 104, 104, 105, 107, 107],
        'low':   [99, 101, 103, 102, 104, 105],
        'close': [102, 104, 103, 105, 107, 106]
    }
    df = pd.DataFrame(data, index=times)

    # 1. Trigger detection test
    trigger = find_trigger(df)
    print("Trigger found at:", trigger)        # Expect 2025-04-21 07:20:00+00:00

    # 2. Contract sizing tests
    print("\nContract sizing tests:")
    for price in [2.5, 0, -1]:
        print(f"  Price = {price} → Contracts = {calculate_contracts(price)}")
