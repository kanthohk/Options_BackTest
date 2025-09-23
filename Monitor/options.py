import logging, os
import yaml, time, requests, re, threading
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

EXPIRY_WEEKDAY = {
    "SENSEX": 3, # Thursday
    "NIFTY": 1,  # Tuesday
    "BANKNIFTY": 1,  # Tuesday
    "FINNIFTY": 1,  # Tuesday
}

def last_weekday_of_month(year, month, weekday):
    """Return last given weekday of a month (0=Mon ... 6=Sun)."""
    d = datetime(year, month, 1) + relativedelta(day=31)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d

def split_symbol(symbol):
    """Parse KiteConnect option tradingsymbol into components."""
    match = re.match(r"([A-Z]+)(.+?)(CE|PE)?$", symbol)
    if not match:
        return None
    underlying, middle, opt_type = match.groups()
    if re.search(r"[A-Z]{3}", middle):
        yy = int(middle[:2])
        mon_str = middle[2:5]
        strike = int(middle[5:])
        year = 2000 + yy
        month = datetime.strptime(mon_str, "%b").month
        expiry_dt = last_weekday_of_month(year, month, EXPIRY_WEEKDAY.get(underlying, 1))
    else:
        # Weekly expiry e.g. NIFTY2592324900PE
        date_part = middle[:-5] # assuming strike is 5 digit
        yy = int(date_part[-2:])
        mm = int(date_part[2:-2]) if len(date_part[2:-2]) > 0 else 1
        dd = int(date_part[:2])
        strike = int(middle[-5:])
        expiry_dt = datetime(2000+yy, mm, dd)
    return underlying, expiry_dt, strike, opt_type

class SyncFileHandler(logging.FileHandler):
    """FileHandler that flushes and syncs every log record."""

    def emit(self, record):
        super().emit(record)  # normal logging
        self.stream.flush()  # flush Python buffer
        os.fsync(self.stream.fileno())  # flush OS buffer

class handle_options:
    def __init__(self, user):
        self.user = user
        self.logger = self._setup_logger()
        self.api_url = "http://localhost:5000"
        self.lock_profit = 0
        self.trail_profit_hit_count = 0
        self.positions = []
        self.closed_positions = []
        self.quantity = 1000000
        self.long_put_symbol = None
        self.short_put_symbol = None
        self.short_call_symbol = None
        self.long_call_symbol = None
        self.short_put_entry = 0
        self.short_call_entry = 0
        self.long_put_price = 0
        self.short_put_price = 0
        self.short_call_price = 0
        self.long_call_price = 0
        self.total_premium_collected = 0
        self.total_premium_earned = 0
        with open("config.yaml", "r") as file:
            self.config = yaml.safe_load(file)

    def _setup_logger(self):
        """Create a per-user thread-safe logger with immediate disk writes."""
        logger = logging.getLogger(f"{self.user}_logger")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            fh = SyncFileHandler(f"{self.user}_watch.log", mode='w')
            formatter = logging.Formatter(
                '%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
            )
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        return logger

    def watch(self):
        with open("watch_sync.yaml", "r") as file:
            watch_sync = yaml.safe_load(file)
        should_watch = self.user in watch_sync
        if should_watch:
            self.logger.info(f"Started to Watch user: {self.user}")
        else:
            self.logger.info(f"Not watching the user: {self.user}. Record not found in watch_sync.yaml")
        return should_watch
    def process_positions(self):
        url = f"{self.api_url}/get_positions?user={self.user}"
        self.positions = []
        self.closed_positions = []
        self.total_premium_collected = self.total_premium_earned = 0
        response = requests.get(url)
        success = response.json()[0]
        if success:
            positions_list = response.json()[1][self.user]
            self.logger.info(f"Received {len(positions_list)} positions, processing them")
            option_chain = []
            for position in positions_list:
                position_to_save = {}
                position_to_save['symbol'] = position['tradingsymbol']
                position_to_save['transtype'] = 'buy' if position['buy_quantity'] > 0 else 'sell'
                position_to_save['transprice'] = position['average_price']
                position_to_save['quantity'] = position['buy_quantity'] if position['buy_quantity'] > 0 else position['sell_quantity']
                position_to_save['pnl'] = position['pnl']
                #####Get Option latest price ################
                position_to_save['last_price'] = position['last_price']
                underlying, expiry, strike, option_type = split_symbol(position_to_save['symbol'])
                if len(option_chain) == 0:
                    url = f"{self.api_url}/get_current_price?symbol={underlying}&request_type=option"
                    response = requests.get(url)
                    if response.json()[0]:
                        self.logger.info(f"Received Option Chain ...{response.json()[0]}")
                        option_chain = response.json()[1]['records']['data']
                    else:
                        self.logger.info(f"Failed to get Option Chain ...")
                        option_chain = []
                #self.logger.info(f"Looking for {position_to_save['symbol']} : {expiry.strftime('%d-%b-%Y')} : {int(strike)}")
                for item in option_chain:
                    if option_type in item:
                        #self.logger.info(f"{item['strikePrice']} : {item['expiryDate']} : {option_type} : {item.get(option_type).get('lastPrice')}")
                        if item["strikePrice"] == int(strike) and item["expiryDate"] == expiry.strftime("%d-%b-%Y"):
                            self.logger.info(f"Got the last price for {position_to_save['symbol']}: {item.get(option_type).get('lastPrice')}")
                            position_to_save['last_price'] = item.get(option_type).get('lastPrice')
                            break
                ####Get Option latest price ################
                if position['quantity'] == 0:
                    self.closed_positions.append(position_to_save)
                    continue
                else:
                    self.positions.append(position_to_save)
                self.quantity = min(self.quantity, position_to_save['quantity'])
                if position_to_save['transtype'] == 'buy':
                    self.total_premium_collected -= position_to_save['transprice']
                    self.total_premium_earned -= position_to_save['last_price']
                    if position_to_save['symbol'][-2:] == 'PE':
                        self.long_put_symbol = position_to_save['symbol']
                        self.long_put_price = position_to_save['last_price']
                    else:
                        self.long_call_symbol = position_to_save['symbol']
                        self.long_call_price = position_to_save['last_price']
                else:
                    self.total_premium_collected += position_to_save['transprice']
                    self.total_premium_earned += position_to_save['last_price']
                    if position_to_save['symbol'][-2:] == 'PE':
                        self.short_put_symbol = position_to_save['symbol']
                        self.short_put_entry = position_to_save['transprice']
                        self.short_put_price = position_to_save['last_price']
                    else:
                        self.short_call_symbol = position_to_save['symbol']
                        self.short_call_entry = position_to_save['transprice']
                        self.short_call_price = position_to_save['last_price']
            self.logger.info(f"Loaded {len(self.positions)} active positions & {len(self.closed_positions)} closed positions.")

    def get_pnl(self):
        pnl=0
        for position in self.positions:
            self.logger.info(f"{position['symbol']}, {position['transtype']}, {position['transprice']}, {position['last_price']}")
            if position['transtype'] == 'buy':
                pnl += (position['last_price'] - position['transprice']) * position['quantity']
            else:
                pnl += (position['transprice'] - position['last_price']) * position['quantity']
        return round(pnl, 2)

    def check_stop_loss(self):
        underlying, expiry, long_call_strike, option_type = split_symbol(self.long_call_symbol)
        dte = (expiry.date() - date.today()).days
        base_factor = 1.0
        if dte > 20:
            base_factor = 1.5
        elif 15 < dte <= 20:
            base_factor = 1.4
        elif 10 < dte <= 15:
            base_factor = 1.3
        elif 5 < dte <= 10:
            base_factor = 1.2
        else:
            base_factor = 1.0

        url = f"{self.api_url}/get_current_price?symbol=india vix"
        response = requests.get(url)
        if response.json()[0]:
            vix_value = response.json()[1]
            self.logger.info(f"Got the VIX: {vix_value}")
        else:
            self.logger.info(f"Failed to get the VIX. Using default value")
            vix_value = 12


        if vix_value < 10:
            vix_factor = 0.8
        elif 10 <= vix_value < 12:
            vix_factor = 0.9
        elif 12 <= vix_value < 15:
            vix_factor = 1
        elif 15 <= vix_value < 18:
            vix_factor = 1.2
        elif 18 <= vix_value < 22:
            vix_factor = 1.5
        else:
            vix_factor = 2

        sl_factor = 1 + (base_factor - 1) * vix_factor
        stop_loss_hit = False
        sl_premium = self.total_premium_collected * sl_factor
        if self.total_premium_earned >= sl_premium:
            stop_loss_hit = True
        self.logger.info(f"Base_factor: {base_factor}, VIX_factor: {vix_factor}, SL Factor: {sl_factor}")
        self.logger.info(f"Premium Collected: {round(self.total_premium_collected,2)}, Premium Earned: {round(self.total_premium_earned,2)}, StopLoss Premium: {round(sl_premium,2)}")

        nearing_strike = False
        underlying, expiry, long_call_strike, option_type = split_symbol(self.long_call_symbol)
        underlying, expiry, short_call_strike, option_type = split_symbol(self.short_call_symbol)
        underlying, expiry, short_put_strike, option_type = split_symbol(self.short_put_symbol)
        underlying, expiry, long_put_strike, option_type = split_symbol(self.long_put_symbol)

        if underlying == 'NIFTY':
            url = f"{self.api_url}/get_current_price?symbol=nifty 50"
        elif underlying == 'BANKNIFTY':
            url = f"{self.api_url}/get_current_price?symbol=nifty bank"
        else:
            url = f"{self.api_url}/get_current_price?symbol={underlying}"
        response = requests.get(url)
        if response.json()[0]:
            current_price = response.json()[1]
            self.logger.info(f"Got the Index price {current_price}")
        else:
            current_price = round((int(short_put_strike) + int(short_call_strike))/2,2)
            self.logger.info(f"Failed to get the Index price. Using default: {current_price}")

        if current_price <= int(short_put_strike) + 200 or current_price >= int(short_call_strike) - 200:
            nearing_strike = True

        if stop_loss_hit or nearing_strike:
            self.logger.info(f"### Close the strikes as Stop Loss Hit is {stop_loss_hit} and Nifty reaching the strikes is {nearing_strike} ###")
            try:
                pass
                #self.place_order(short_call_strike, self.quantity, "BUY")
                #self.place_order(short_put_strike, self.quantity, "BUY")
                #self.place_order(long_call_strike, self.quantity, "SELL")
                #self.place_order(long_put_strike, self.quantity, "SELL")
                #return True
            except Exception as e:
                self.logger.error(f"Failed to close the Iron Condor: {e}")
        return False

    def trail_profit(self):
        pnl = self.get_pnl()
        trail_profit = round(self.quantity * self.config['trailing_profit_multiplier'],2)
        self.logger.info(f"Current Profit: {pnl}, Lock Profit: {self.lock_profit}, Trail Profit: {trail_profit}")
        if pnl <= self.lock_profit and self.lock_profit > 0:
            self.trail_profit_hit_count += 1
            self.logger.info(f"Trailing profit is hit count: {self.trail_profit_hit_count}")

            if self.trail_profit_hit_count > self.config['trail_profit_threshold']:
                self.logger.info(f"Closing the positions")
                underlying, expiry, long_call_strike, option_type = split_symbol(self.long_call_symbol)
                underlying, expiry, short_call_strike, option_type = split_symbol(self.short_call_symbol)
                underlying, expiry, short_put_strike, option_type = split_symbol(self.short_put_symbol)
                underlying, expiry, long_put_strike, option_type = split_symbol(self.long_put_symbol)
                try:
                    pass
                    #self.place_order(short_call_strike, self.quantity, "BUY")
                    #self.place_order(short_put_strike, self.quantity, "BUY")
                    #self.place_order(long_call_strike, self.quantity, "SELL")
                    #self.place_order(long_put_strike, self.quantity, "SELL")
                    #return True
                except Exception as e:
                    self.logger.info(f"Failed to close the Iron Condor: {e}")

        if pnl >= (self.lock_profit + trail_profit + 500):
            self.lock_profit = pnl - trail_profit
            self.logger.info(f"Locking the profit: {self.lock_profit}")
        return False
    def adjustments(self):
    #
        underlying, expiry, long_put_strike, option_type = split_symbol(self.long_put_symbol)
        underlying, expiry, short_put_strike, option_type = split_symbol(self.short_put_symbol)
        underlying, expiry, short_call_strike, option_type = split_symbol(self.short_call_symbol)
        underlying, expiry, long_call_strike, option_type = split_symbol(self.long_call_symbol)

        if self.short_call_price > 0 and self.short_put_price > 0:
            self.logger.info(f"PE Price: {self.short_put_price}, CE Price: {self.short_call_price}")
            if self.short_call_price <= self.short_put_price * 55/100:
                self.logger.info(f"Market is going down. Adjustment is needed on CE side")
                self.logger.info(f"Buying {self.short_call_symbol} & Selling {underlying}{int(short_call_strike)-50}CE")
                self.place_order(symbol=self.short_call_symbol,
                                 quantity=self.quantity,
                                 transaction_type="BUY")
                self.place_order(symbol=self.short_call_symbol.replace(short_call_strike, str(int(short_call_strike)-50)),
                                 quantity=self.quantity,
                                 transaction_type="SELL")
                self.logger.info(f"Need to sell {self.long_call_symbol} & Need to buy {underlying}{int(long_call_strike)-50}CE")
            elif self.short_put_price <= self.short_call_price * 55/100:
                self.logger.info(f"Market is going up. Adjustment is needed on PE side")
                self.logger.info(f"Buying {self.short_put_symbol} & Selling {underlying}{int(short_put_strike)+50}PE")
                self.place_order(symbol=self.short_put_symbol,
                                 quantity=self.quantity,
                                 transaction_type="BUY")
                self.place_order(symbol=self.short_put_symbol.replace(short_put_strike, str(int(short_put_strike)+50)),
                                 quantity=self.quantity,
                                 transaction_type="SELL")
                self.logger.info(f"Need to sell {self.long_put_symbol} & Need to buy {underlying}{int(long_put_strike)+50}PE")
            else:
                self.logger.info(f"No need of any adjustments.")
        else:
            self.logger.info(f"Either PE_price or CE_price is not retrieved properly")

    def place_order(self, symbol, quantity, transaction_type):
        url = f"{self.api_url}/place_order?user={self.user}&symbol={symbol}&quantity={quantity}&transaction_type={transaction_type}"
        response = requests.get(url)
        success = response.json()[0]
        if success:
            self.logger.info(f"{transaction_type} transaction for  {symbol} of {self.user} is successful")

    def run(self):
        self.logger.info("#" * 100)
        if self.watch():
            self.process_positions()
            if len(self.positions) == 4:
                self.logger.info("-" * 25)
                self.logger.info("Got the positions. Proceeding for stop loss")
                closed = self.check_stop_loss()
                if not closed:
                    self.logger.info("-" * 25)
                    self.logger.info("Stop loss is verified. Proceeding to trail profit")
                    closed = self.trail_profit()
                    if not closed:
                        self.logger.info("-" * 25)
                        self.logger.info("Trail Profit is done. Proceeding to check adjustments")
                        self.adjustments()
            time.sleep(self.config.get('delay'))

def run_user(user, handle_obj):
    """Worker function to run each user's trading logic."""
    try:
        handle_obj.run()
    except Exception as e:
        print(f"Error in thread for {user}: {e}")

if __name__ == "__main__":
    handle_objs = {}
    while True:
        with open("watch_sync.yaml", "r") as file:
            watch_sync = yaml.safe_load(file)
        if watch_sync:
            remove_users = []
            # Delete the users in handle_objs but not in watch_sync
            for user in handle_objs:
                if user not in watch_sync:
                    remove_users.append(user)
            for user in remove_users:
                del handle_objs[user]
            # Add the users in handle_objs that are in watch_sync
            for user in watch_sync:
                if user not in handle_objs:
                    handle_objs[user] = handle_options(user)
            # Spawn a thread for each user
            threads = []
            for user, handle_obj in handle_objs.items():
                t = threading.Thread(target=run_user, args=(user, handle_obj))
                t.daemon = True  # allows program to exit even if threads are running
                t.start()
                threads.append(t)

            # Join all threads (wait for them to finish one cycle)
            for t in threads:
                t.join()
        # Sleep before next iteration (to avoid hammering file + APIs)
        time.sleep(20)
'''
    handle_objs = {}
    while True:
        with open("watch_sync.yaml", "r") as file:
            watch_sync = yaml.safe_load(file)
        if watch_sync:
            remove_users = []
            # Delete the users in handle_objs but not in watch_sync
            for user in handle_objs:
                if user not in watch_sync:
                    remove_users.append(user)
            for user in remove_users:
                del handle_objs[user]
            # Add the users in handle_objs that are in watch_sync
            for user in watch_sync:
                if user not in handle_objs:
                    handle_objs[user] = handle_options(user)
            # Run the users added in handle_objs
            for user in handle_objs:
                handle_objs[user].run()
'''
