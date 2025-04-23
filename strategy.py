import pandas as pd, math, pytz, logging
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
    "mode": "PAPER",
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
logging.basicConfig(
    filename=C["log_file"], level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

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
    df2 = df[df.index >= df.index[0] + pd.Timedelta(minutes=C["ignore_minutes"])]
    for i in range(1, len(df2)):
        p, c = df2.iloc[i-1], df2.iloc[i]
        d = 'up' if p.close > p.open else 'down'
        if (d=='up' and c.close>p.high) or (d=='down' and c.close<p.low):
            return df2.index[i], d
    return None, None

def size(price):
    return int(C["position_usd"]/(price*100)) if price>0 else 0

def select_option(ib, sym, d):
    # snapshot=True to avoid subscription errors
    ticker = ib.reqMktData(Stock(sym,'SMART','USD'), "", True, False)
    ib.sleep(1)
    price = ticker.last
    if price is None or (isinstance(price, float) and math.isnan(price)):
        logging.error(f"{sym} invalid price: {price}")
        return None
    exp = (datetime.now(tz).date() + timedelta(days=C["exp_days_ahead"])).strftime('%Y%m%d')
    strike = math.ceil(price) if d=='up' else math.floor(price)
    if abs(strike-price)>C["otm_threshold"]:
        strike = int(price)+(1 if d=='up' else -1)
    return Option(sym, exp, strike, 'CALL' if d=='up' else 'PUT', 'SMART')

def place_orders(ib, ctr, q):
    if q<1: 
        logging.info("Quantity <1, skipping")
        return
    tr = ib.placeOrder(ctr, MarketOrder('BUY', q)); ib.sleep(1)
    fp = tr.orderStatus.avgFillPrice
    logging.info(f"ENTERED {q}@{fp} {ctr}")
    tp = fp*(1+C["take_profit_pct"]); sl = fp*(1-C["stop_loss_pct"])
    tpq = int(q*C["partial_sell_pct"])
    oca = f"OCA_{datetime.now(tz).strftime('%H%M%S')}"
    for qty, price in [(tpq, tp), (q, sl)]:
        o = LimitOrder('SELL', qty, price)
        o.ocaGroup=oca; o.ocaType=2
        ib.placeOrder(ctr, o)
    logging.info(f"Placed TP@{tp}, SL@{sl}")

def eod(ib):
    now = datetime.now(tz)
    tgt = tz.localize(datetime.combine(now.date(), time.fromisoformat(C["eod_time"])))
    if now<tgt: return
    for o in ib.openOrders(): ib.cancelOrder(o)
    for pos in ib.positions():
        if pos.position:
            side='SELL' if pos.position>0 else 'BUY'
            ib.placeOrder(pos.contract, MarketOrder(side, abs(int(pos.position))))
    ib.disconnect(); logging.info("EOD cleanup done")

def run():
    ib = connect_ib()
    for sym in C["symbols"]:
        try:
            df = get_bars(ib, sym)
            t, d = find_trigger(df)
            if not t:
                logging.info(f"{sym} no trigger"); continue
            logging.info(f"{sym} trigger at {t}, dir={d}")
            ctr = select_option(ib, sym, d)
            if not ctr: continue
            tick = ib.reqMktData(ctr, "", True, False); ib.sleep(1)
            place_orders(ib, ctr, size(tick.last))
        except Exception as e:
            logging.error(f"{sym} error: {e}")
    eod(ib)

if __name__=="__main__":
    run()
