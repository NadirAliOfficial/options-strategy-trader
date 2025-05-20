import pandas as pd
import math
import pytz
import logging
import ctypes
# import winsound
from datetime import datetime, timedelta, time
from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder, util

# -------------- CONFIG --------------
C = {
    "symbols": ["SPY"],
    "position_usd": 10000,
    "ignore_minutes": 15,
    "otm_threshold": 1.0,
    "exp_days_ahead": 1,
    "timezone": "US/Mountain",
    "mode": "PAPER",               # switch to "LIVE" for real trades
    "take_profit_pct": 0.10,
    "partial_sell_pct": 0.90,
    "stop_loss_pct": 0.10,
    "eod_time": "15:50",
    "ib_host": "127.0.0.1",
    "ib_port": 7497,
    "ib_client_id": 1,
    "log_file": "strategy.log"
}
tz = pytz.timezone(C["timezone"])

# Setup logging
logging.basicConfig(
    filename=C["log_file"],
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# def alert_user(title, msg):
#     """Show Windows pop-up and beep on trigger."""
#     ctypes.windll.user32.MessageBoxW(0, msg, title, 0x1000)
#     winsound.Beep(1000, 300)

def connect_ib():
    ib = IB()
    ib.connect(C["ib_host"], C["ib_port"], clientId=C["ib_client_id"])
    return ib

def get_bars(ib, sym):
    bars = ib.reqHistoricalData(
        Stock(sym,'SMART','USD'), '', '1 D', '5 mins',
        'TRADES', True, 1
    )
    df = util.df(bars)
    df.index = pd.to_datetime(df.date)
    df.index = df.index.tz_localize('UTC') if df.index.tz is None else df.index.tz_convert('UTC')
    return df[['open','high','low','close']]

def find_trigger(df):
    """
    Rolling trigger logic:
    - First 5m after ignore window becomes initial trigger candle.
    - For each next candle:
      • If same direction + wick-break → entry.
      • Else reset trigger to this candle.
    """
    df2 = df[df.index >= df.index[0] + pd.Timedelta(minutes=C["ignore_minutes"])]
    if df2.empty:
        return None, None

    # start with first post-ignore candle
    trigger = df2.iloc[0]
    for curr in df2.iloc[1:].itertuples():
        prev = trigger
        prev_dir = 'up' if prev.close > prev.open else 'down'
        curr_dir = 'up' if curr.close > curr.open else 'down'

        # entry condition
        if prev_dir == curr_dir:
            if (prev_dir == 'up'   and curr.close > prev.high) or \
               (prev_dir == 'down' and curr.close < prev.low):
                return curr.Index, prev_dir

        # reset trigger
        trigger = df2.loc[curr.Index]

    return None, None

def size(price):
    return int(C["position_usd"] / (price * 100)) if price and price > 0 else 0

def select_option(ib, sym, direction, bars):
    ticker = ib.reqMktData(Stock(sym,'SMART','USD'), "", True, False)
    ib.sleep(1)
    price = ticker.last
    if price is None or (isinstance(price, float) and math.isnan(price)):
        price = bars['close'].iloc[-1]
        logging.warning(f"{sym} live data down, using last bar close {price}")
    exp = (datetime.now(tz).date() + timedelta(days=C["exp_days_ahead"])).strftime('%Y%m%d')
    strike = math.ceil(price) if direction=='up' else math.floor(price)
    if abs(strike - price) > C["otm_threshold"]:
        strike = int(price) + (1 if direction=='up' else -1)
    right = 'CALL' if direction=='up' else 'PUT'
    return Option(sym, exp, strike, right, 'SMART')

def place_orders(ib, contract, qty):
    if qty < 1:
        logging.warning(f"{contract.symbol} qty {qty}<1, skipping")
        return
    tr = ib.placeOrder(contract, MarketOrder('BUY', qty))
    ib.sleep(1)
    fill = tr.orderStatus.avgFillPrice
    logging.info(f"ENTERED {qty}@{fill:.2f} {contract.symbol} {contract.strike} {contract.right}")
    tp = fill * (1 + C["take_profit_pct"])
    sl = fill * (1 - C["stop_loss_pct"])
    tp_qty = int(qty * C["partial_sell_pct"])
    oca = f"OCA_{datetime.now(tz).strftime('%H%M%S')}"
    for q, price in [(tp_qty, tp), (qty, sl)]:
        order = LimitOrder('SELL', q, price)
        order.ocaGroup = oca; order.ocaType = 2
        ib.placeOrder(contract, order)
    logging.info(f"TP@{tp:.2f} SL@{sl:.2f} placed for {contract.symbol}")

def eod_cleanup(ib):
    now = datetime.now(tz)
    cutoff = tz.localize(datetime.combine(now.date(), time.fromisoformat(C["eod_time"])))
    if now < cutoff:
        return
    for o in ib.openOrders():
        ib.cancelOrder(o)
    for pos in ib.positions():
        if pos.position:
            side = 'SELL' if pos.position>0 else 'BUY'
            ib.placeOrder(pos.contract, MarketOrder(side, abs(int(pos.position))))
    logging.info("EOD cleanup completed")
    ib.disconnect()

def run_strategy():
    logging.info("=== TaskScheduler run: strategy started ===")
    ib = connect_ib()
    for sym in C["symbols"]:
        try:
            bars = get_bars(ib, sym)
            t_time, direction = find_trigger(bars)
            if not t_time:
                logging.info(f"{sym} no trigger")
                continue

            # alert and log trigger
            local_time = t_time.astimezone(tz).strftime('%H:%M:%S %Z')
            # alert_user("Trading Bot Trigger", f"{sym} {direction.upper()} @ {local_time}")
            logging.info(f"{sym} trigger at {t_time}, dir={direction}")

            contract = select_option(ib, sym, direction, bars)
            tick = ib.reqMktData(contract, "", True, False)
            ib.sleep(1)
            price = tick.last
            if price is None or (isinstance(price, float) and math.isnan(price)):
                price = bars['close'].iloc[-1]
                logging.warning(f"{sym} tick data down, fallback price {price}")
            logging.info(f"{sym} sizing price: {price}")

            qty = size(price)
            if qty < 1:
                logging.warning(f"{sym} qty {qty}<1, skipping")
                continue

            place_orders(ib, contract, qty)
        except Exception as e:
            logging.error(f"Error processing {sym}: {e}")
    eod_cleanup(ib)
    logging.info("=== TaskScheduler run: strategy completed ===")

if __name__ == "__main__":
    run_strategy()
