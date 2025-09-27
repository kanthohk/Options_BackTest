from flask import Flask, request, jsonify
import yaml
from TradingBroker.kite_api_bot import KITE_CONNECT
from MarketAnalysis.fetch_data import get_ltp #, get_option_chain
# Create Flask app
app = Flask(__name__)
broker_connections = {}

# Home route
@app.route("/")
def home():
    return "Welcome to my small financial app ..."

def get_credentials():
    with open("TradingBroker/config.yaml", "r") as file:
        config = yaml.safe_load(file)
    return config["credentials"]

# Example API: greet user
#@app.route("/get_broker", methods=["GET"])
def get_broker(user):
    global broker_connections
    #name = request.args.get("name")
    credentials = get_credentials()
    if not user or not user in credentials:
        return [False, "Either user or his credentials are missing"]
    #
    kc = KITE_CONNECT(user, credentials.get(user))
    if kc:
        broker_connections[user]= kc
        return [True, "Got Connection successfully"]
    else:
        return [False, "Failed to get connection"]

@app.route("/get_orders", methods=["GET"])
def get_orders():
    global broker_connections
    user = request.args.get("user")
    orders = {}
    try:
        if user:
            if not user in broker_connections:
                get_broker(user)
            orders[user] = broker_connections[user].fetch_orders()
        else:
            for user in broker_connections:
                orders[user] = broker_connections[user].fetch_orders()
        return [True, orders]
    except Exception as e:
        print(f"Failed to get orders with error: {e}")
        return [False, f"Failed to get orders with error: {e}"]
@app.route("/get_positions", methods=["GET"])
def get_positions():
    global broker_connections
    positions = {}
    try:
        user = request.args.get("user")
        print(f"Trying to get positions for user {user}")
        positions = {}
        if user:
            if not user in broker_connections:
                print(f"Get the broker connection for {user}...")
                get_broker(user)
            positions[user] =  broker_connections[user].fetch_optoin_positions()
        else:
            for user in broker_connections:
                positions[user] = broker_connections[user].fetch_optoin_positions()
        return [True, positions]
    except Exception as e:
        print(f"Failed to get orders with error: {e}")
        return [False, f"Failed to get orders with error: {e}"]
# Example API: add numbers
@app.route("/watch_positions", methods=["GET"])
def watch_positions():
    user = request.args.get("user")
    adjustments = (True if request.args.get("adjustments").upper() == 'Y' else False) if request.args.get("adjustments") else False
    stoploss = (True if request.args.get("stoploss").upper() == 'Y' else False) if request.args.get("stoploss") else False
    trailprofit = (True if request.args.get("trailprofit").upper() == 'Y' else False) if request.args.get("trailprofit") else False
    watch = {}
    if user:
        with open("Monitor/watch_sync.yaml", "r") as file:
            watch = yaml.safe_load(file)
            if not watch:
                watch = {}
        with open("Monitor/watch_sync.yaml", "w") as file:
            watch[user] = {"adjustments": adjustments, "stoploss": stoploss, "trailprofit": trailprofit}
            yaml.dump(watch, file, default_flow_style=False, sort_keys=False)
    else:
        return [False, f"Please provide the user to watch"]
    return [True, f"Started watching the position of {user}"]
@app.route("/stop_watch_positions", methods=["GET"])
def stop_watch_positions():
    user = request.args.get("user")
    watch = {}
    if user:
        with open("Monitor/watch_sync.yaml", "r") as file:
            watch = yaml.safe_load(file)
        with open("Monitor/watch_sync.yaml", "w") as file:
            del watch[user]
            yaml.dump(watch, file, default_flow_style=False, sort_keys=False)
    else:
        return [False, f"Please provide the user to watch"]
    return [True, f"Stopped watching the position of {user}"]

@app.route("/get_current_price", methods=["GET"])
def get_current_price():
    symbol = request.args.get("symbol")
    request_type = request.args.get("request_type")
    ltp = get_ltp(symbol=symbol, request_type=request_type)
    if ltp:
        return [True, ltp]
    else:
        return [False, None]

'''
@app.route("/get_optionchain", methods=["GET"])
def get_optionchain():
    symbol = request.args.get("symbol")
    op_chain = get_option_chain(symbol=symbol)
    if op_chain:
        return [True, op_chain]
    else:
        return [False, None]
'''
@app.route("/place_order", methods=["GET"])
def place_order():
    user = request.args.get("user")
    symbol = request.args.get("symbol")
    quantity = request.args.get("quantity")
    transaction_type = request.args.get("transaction_type")
    try:
        if user:
            if not user in broker_connections:
                get_broker(user)
            order_id = broker_connections[user].place_order(symbol=symbol, quantity=quantity, transaction_type=transaction_type)
            return [True, f"Order is placed successfully:{order_id}"]
        else:
            raise Exception(f"User cannot be null")
    except Exception as e:
        print(f"Failed to place order with error: {e}")
        return [False, f"Failed to place order with error: {e}"]

# Run the app
if __name__ == "__main__":
    app.run(debug=True, port=5000)
