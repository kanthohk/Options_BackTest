# nifty_strangle_backtest.py
import os, glob, json, math, argparse
from datetime import datetime
import pandas as pd
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt

# -------------------------
# CONFIG (change as needed)
# -------------------------
DEFAULT_LOT_SIZE = 75
DEFAULT_STRIKE_PCT = 0.03   # 3% OTM
CAPITAL_PER_LOT = 150000.0  # used for % return calc; adjust to your broker margin
SELL_SLIPPAGE_PCT = 0.002   # 0.2% slippage on sell price (conservative)
BUY_SLIPPAGE_PCT  = 0.002
COMMISSION_PER_LEG = 20.0   # INR per leg (adjust)
TAX_AND_FEES_PCT = 0.0005   # 0.05% regulatory fees as example
MIN_DAYS_TO_EXPIRY = 5      # ignore days when expiry within this many days
PRICE_COL = "last_price"    # column in CSV for price to use (or 'mid' if you have)
UNDERLY_COL = "underlying_price"
# -------------------------

def load_snapshot(file_path):
    df = pd.read_csv(file_path)
    # enforce columns
    expected = { "date", "expiry", "option_type", "strike", UNDERLY_COL, PRICE_COL }
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {file_path}: {missing}")
    df['date'] = pd.to_datetime(df['date'])
    df['expiry'] = pd.to_datetime(df['expiry'])
    df['strike'] = df['strike'].astype(float)
    df[PRICE_COL] = df[PRICE_COL].astype(float)
    df[UNDERLY_COL] = df[UNDERLY_COL].astype(float)
    return df

def find_nearest_strike(df_snapshot, strike_target, option_type):
    # find available strikes of given option_type and pick the nearest
    df = df_snapshot[df_snapshot['option_type'] == option_type]
    if df.empty:
        return None
    # choose strike with minimal abs difference
    idx = (df['strike'] - strike_target).abs().idxmin()
    return df.loc[idx]

def run_backtest(data_dir,
                 strike_pct=DEFAULT_STRIKE_PCT,
                 lot_size=DEFAULT_LOT_SIZE,
                 min_days_to_expiry=MIN_DAYS_TO_EXPIRY,
                 sell_slip_pct=SELL_SLIPPAGE_PCT,
                 buy_slip_pct=BUY_SLIPPAGE_PCT,
                 commission_per_leg=COMMISSION_PER_LEG):

    # Expect files: YYYY-MM-DD_open.csv and YYYY-MM-DD_close.csv
    open_files = sorted(glob.glob(os.path.join(data_dir, "*_open.csv")))
    close_files = sorted(glob.glob(os.path.join(data_dir, "*_close.csv")))
    # Map date string -> file
    open_map = { os.path.basename(f).split("_")[0]: f for f in open_files }
    close_map = { os.path.basename(f).split("_")[0]: f for f in close_files }
    trade_rows = []

    dates = sorted(set(open_map.keys()) & set(close_map.keys()))
    if not dates:
        raise ValueError("No matching open/close snapshot pairs found in data dir")

    for dstr in tqdm(dates, desc="Processing days"):
        open_file = open_map[dstr]
        close_file = close_map[dstr]
        df_open = load_snapshot(open_file)
        df_close = load_snapshot(close_file)
        # determine spot from open (take median to avoid outliers)
        spot = float(df_open[UNDERLY_COL].median())
        # Pick nearest monthly expiry > min_days_to_expiry
        # compute days to expiry and pick the nearest expiry that is monthly (user may constrain)
        df_open['dte'] = (df_open['expiry'] - pd.to_datetime(dstr)).dt.days
        # choose the nearest expiry with dte >= min_days_to_expiry and dte > 7 (to avoid last-week)
        candidate_exps = df_open[df_open['dte'] >= min_days_to_expiry]['expiry'].unique()
        if len(candidate_exps) == 0:
            # no eligible expiry this day
            continue
        # choose the expiry with max days (monthly target) OR choose min positive > min_days... pick logic as you like
        expiry = sorted(candidate_exps)[0]  # earliest eligible expiry
        # narrow open/close snapshots to chosen expiry
        snap_open = df_open[df_open['expiry'] == expiry].copy()
        snap_close = df_close[df_close['expiry'] == expiry].copy()
        if snap_open.empty or snap_close.empty:
            continue

        # compute strikes target
        put_target = spot * (1.0 - strike_pct)
        call_target = spot * (1.0 + strike_pct)
        # find nearest available strikes in open snapshot
        put_row = find_nearest_strike(snap_open, put_target, 'PE')
        call_row = find_nearest_strike(snap_open, call_target, 'CE')
        if put_row is None or call_row is None:
            continue

        strike_put = put_row['strike']
        strike_call = call_row['strike']

        # find corresponding rows in close snapshot for same strike & option type
        close_put = snap_close[(snap_close['option_type']=='PE') & (snap_close['strike']==strike_put)]
        close_call = snap_close[(snap_close['option_type']=='CE') & (snap_close['strike']==strike_call)]
        if close_put.empty or close_call.empty:
            # missing close price for a leg; skip or attempt interpolation
            continue

        # price to sell at open (use last_price); apply sell slippage
        sell_put_price = float(put_row[PRICE_COL]) * (1 + sell_slip_pct)
        sell_call_price = float(call_row[PRICE_COL]) * (1 + sell_slip_pct)
        # price to buy at close (apply buy slippage)
        buy_put_price = float(close_put.iloc[0][PRICE_COL]) * (1 + buy_slip_pct)
        buy_call_price = float(close_call.iloc[0][PRICE_COL]) * (1 + buy_slip_pct)

        # gross P/L per option unit (positive for seller)
        pl_put_unit = sell_put_price - buy_put_price
        pl_call_unit = sell_call_price - buy_call_price
        pl_unit = pl_put_unit + pl_call_unit

        # apply commissions and fees (both legs)
        total_commission = 2 * commission_per_leg  # sell and buy each side counted as per-leg, but simplified
        total_fees = (sell_put_price + sell_call_price + buy_put_price + buy_call_price) * lot_size * TAX_AND_FEES_PCT

        pl_lot = pl_unit * lot_size - total_commission - total_fees

        # margin estimate (very approximate): you should replace with actual SPAN/EPS or broker margin
        # Here assume capital per lot provided by user; we record pl relative to that separately.
        trade_rows.append({
            "date": dstr,
            "expiry": expiry,
            "spot": spot,
            "strike_put": strike_put,
            "strike_call": strike_call,
            "sell_put": sell_put_price,
            "sell_call": sell_call_price,
            "buy_put": buy_put_price,
            "buy_call": buy_call_price,
            "pl_unit": pl_unit,
            "pl_lot": pl_lot
        })

    trades = pd.DataFrame(trade_rows)
    if trades.empty:
        print("No trades executed with given data and filters.")
        return None

    # Summary stats
    total_pl = trades['pl_lot'].sum()
    avg_pl = trades['pl_lot'].mean()
    median_pl = trades['pl_lot'].median()
    win_rate = (trades['pl_lot'] > 0).mean()
    months = trades['date'].nunique()
    avg_monthly = trades.groupby('date')['pl_lot'].sum().mean()

    print("\n=== Backtest Summary ===")
    print(f"Trades executed: {len(trades)}")
    print(f"Unique trading days (months): {months}")
    print(f"Total P/L (INR): {total_pl:.2f}")
    print(f"Avg P/L per trade (INR): {avg_pl:.2f}")
    print(f"Median P/L per trade (INR): {median_pl:.2f}")
    print(f"Win rate: {win_rate*100:.2f}%")
    print(f"Avg monthly P/L (INR): {avg_monthly:.2f}")
    print(f"Avg monthly return (% of capital_per_lot={CAPITAL_PER_LOT}): {(avg_monthly/CAPITAL_PER_LOT)*100:.4f}%")

    # plot equity curve (cumulative)
    trades['cum_pl'] = trades['pl_lot'].cumsum()
    trades['date_dt'] = pd.to_datetime(trades['date'])
    plt.figure(figsize=(10,5))
    plt.plot(trades['date_dt'], trades['cum_pl'], marker='o', linestyle='-')
    plt.title("Cumulative P&L (INR)")
    plt.xlabel("Date")
    plt.ylabel("Cumulative P&L")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    # monthly P&L bar
    monthly = trades.groupby('date')['pl_lot'].sum()
    plt.figure(figsize=(10,5))
    monthly.plot(kind='bar')
    plt.title("P&L per trading day (monthly strangle intraday)")
    plt.xlabel("Date")
    plt.ylabel("P&L (INR)")
    plt.tight_layout()
    plt.show()

    return trades

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="Directory containing *_open.csv and *_close.csv snapshots")
    parser.add_argument("--strike-pct", type=float, default=DEFAULT_STRIKE_PCT, help="OTM percent e.g. 0.03 for 3%")
    parser.add_argument("--lot-size", type=int, default=DEFAULT_LOT_SIZE)
    args = parser.parse_args()

    trades_df = run_backtest(args.data_dir, strike_pct=args.strike_pct, lot_size=args.lot_size)
    if trades_df is not None:
        trades_df.to_csv("backtest_trades_output.csv", index=False)
        print("Saved detailed trades to backtest_trades_output.csv")
