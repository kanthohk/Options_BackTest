import requests
import time


def get_ltp(symbol, request_type='stock', max_retries=3, delay=1):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/117.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/live-equity-market"
    }

    session = requests.Session()
    if request_type == 'stock':
        api_url = "https://www.nseindia.com/api/allIndices"
    else:
        api_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"

    for attempt in range(1, max_retries + 1):
        try:
            # Step 1: Hit NSE homepage to get cookies
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            time.sleep(delay)  # small pause to ensure cookies are set
            # Step 2: Hit the API URL
            resp = session.get(api_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if request_type == 'stock':
                    for idx in data["data"]:
                        if idx["index"].lower() == symbol.lower():
                            return float(idx["last"])
                    print(f"{symbol} not found in response.")
                    return None
                else:
                    return data
            else:
                print(f"Attempt {attempt}: Response code {resp.status_code}. Retrying...")
                time.sleep(1.5*attempt)
        except Exception as e:
            print(f"Attempt {attempt}: Exception occurred: {e}. Retrying...")
            time.sleep(1.5*attempt)

    print(f"Failed to fetch {symbol} after retries.")
    return None


# Example usage
#symbol = "india vix"
#price = get_ltp(symbol)
#print(f"{symbol}: {price}")

def get_option_chain(symbol='NIFTY'):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.nseindia.com/option-chain",
        "Accept-Language": "en-US,en;q=0.9"
    }
    session = requests.Session()

    # Hit NSE homepage to get cookies
    session.get("https://www.nseindia.com", headers=headers, timeout=5)
    time.sleep(0.5)

    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    resp = session.get(url, headers=headers, timeout=5)
    if resp.status_code != 200:
        print("Failed:", resp.status_code)
        return None

    data = resp.json()
    return data

#option_chain = get_option_chain()
#if option_chain:
#    for ce in option_chain["records"]["data"]:
#        if "CE" in ce:
#            print(ce["CE"]["strikePrice"], ce["CE"]["lastPrice"])
