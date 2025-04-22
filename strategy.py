# strategy.py

import pandas as pd
import math
import pytz
from datetime import datetime, timedelta
from ib_insync import IB, Stock, Option, MarketOrder, util

# ------------------ CONFIG ------------------
SYMBOL = 'AAPL'
POSITION_USD = 10000
IGNORE_MINUTES = 15
OTM_THRESHOLD = 1.0
EXP_DAYS_AHEAD = 1
TIMEZONE = 'US/Mountain'
IB_HOST = '127.0.0.1'
IB_PORT = 7497
IB_CLIENT_ID = 1
# --------------------------------------------

def connect_ib():
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
    return ib

def get_5min_bars(ib):
    """
    Fetches 1 day of 5‑minute bars for SYMBOL (useRTH).
    """
    contract = Stock(SYMBOL, 'SMART', 'USD')
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='5 mins',
        whatToShow='TRADES',
        useRTH=True,
        formatDate=1
    )
    df = util.df(bars)
    df.index = pd.to_datetime(df.date).tz_localize('UTC')
    return df[['open', 'high', 'low', 'close']]

def filter_bars(df):
    cutoff = df.index[0] + pd.Timedelta(minutes=IGNORE_MINUTES)
    return df[df.index >= cutoff]

def find_trigger(df):
    """
    Returns (trigger_time, direction) if a wick‑break trigger is found.
    """
    df2 = filter_bars(df)
    for i in range(1, len(df2)):
        prev, curr = df2.iloc[i-1], df2.iloc[i]
        direction = 'up' if prev.close > prev.open else 'down'
        if direction == 'up' and curr.close > prev.high:
            return df2.index[i], direction
        if direction == 'down' and curr.close < prev.low:
            return df2.index[i], direction
    return None, None

def calculate_contracts(price):
    if price <= 0:
        return 0
    return int(POSITION_USD / (price * 100))

def select_option(ib, direction):
    """
    Chooses next‑day expiring CALL (up) or PUT (down), ≤ $1 OTM.
    """
    stock = Stock(SYMBOL, 'SMART', 'USD')
    ticker = ib.reqMktData(stock)
    ib.sleep(1)
    price = ticker.last

    local = pytz.timezone(TIMEZONE)
    today = datetime.now(local).date()
    exp = today + timedelta(days=EXP_DAYS_AHEAD)
    exp_str = exp.strftime('%Y%m%d')

    if direction == 'up':
        strike = math.ceil(price)
        right = 'CALL'
    else:
        strike = math.floor(price)
        right = 'PUT'

    if abs(strike - price) > OTM_THRESHOLD:
        strike = int(price) + (1 if direction == 'up' else -1)

    return Option(SYMBOL, exp_str, strike, right, 'SMART')

def place_entry(ib, contract, qty):
    if qty < 1:
        print("Quantity < 1 → no order placed")
        return
    order = MarketOrder('BUY', qty)
    ib.placeOrder(contract, order)
    ib.sleep(1)
    print(f"Placed BUY order: {qty} contracts of {contract.symbol} {contract.strike} {contract.right}")

def run_strategy():
    ib = connect_ib()
    df = get_5min_bars(ib)
    trigger_time, direction = find_trigger(df)
    if not trigger_time:
        print("No trigger found")
        return
    print(f"Trigger at {trigger_time}, direction: {direction}")

    contract = select_option(ib, direction)
    ticker = ib.reqMktData(contract)
    ib.sleep(1)
    price = ticker.last

    qty = calculate_contracts(price)
    place_entry(ib, contract, qty)

if __name__ == "__main__":
    # — Milestone 1 Test —
    print("\n--- Milestone 1 Test ---")
    times = pd.date_range(start="2025-04-21 07:00", periods=6, freq="5T", tz="UTC")
    data = {
        'open':  [100, 102, 104, 103, 105, 106],
        'high':  [102, 104, 104, 105, 107, 107],
        'low':   [99, 101, 103, 102, 104, 105],
        'close': [102, 104, 103, 105, 107, 106]
    }
    df_test = pd.DataFrame(data, index=times)
    trig, dirn = find_trigger(df_test)
    print(f"Trigger at: {trig} (direction: {dirn})")
    print("Contracts @ $2.5:", calculate_contracts(2.5))

    # — Milestone 2 Dummy IB Test —
    print("\n--- Milestone 2 Dummy IB Test ---")
    class DummyIB:
        def reqMktData(self, contract): return type('T',(object,),{'last':2.5})()
        def sleep(self, t=0): pass
        def placeOrder(self, c, o): return o

    ib_dummy = DummyIB()
    opt = select_option(ib_dummy, 'up')
    print("Selected option:", opt)
    qty = calculate_contracts(2.5)
    place_entry(ib_dummy, opt, qty)

    # To run live, uncomment the next line:
    # run_strategy()
