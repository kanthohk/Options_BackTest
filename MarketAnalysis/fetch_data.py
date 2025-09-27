import requests
import time
'''
Option Chain 
    (Indices) 
        https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
        https://www.nseindia.com/api/option-chain-indices?symbol=BANKNIFTY   
    (Stocks) 
        https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE 

Index Quotes 
    (Nifty, BankNifty, India VIX, etc.) 
    https://www.nseindia.com/api/quote-derivative?symbol=NIFTY
    https://www.nseindia.com/api/quote-index?symbol=NIFTY 50
    https://www.nseindia.com/api/quote-index?symbol=INDIA VIX 
    https://www.nseindia.com/api/quote-equity?symbol=RELIANCE
    
Stock Quotes
    https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050
    https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20NEXT%2050

All Indices Snapshot 
    https://www.nseindia.com/api/allIndices   
    
    
'''

def get_ltp(symbol, request_type='stock', max_retries=5, delay=1):
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
                return data
            else:
                print(f"Attempt {attempt}: Response code {resp.status_code}. Retrying...")
                time.sleep(1.5*attempt)
        except Exception as e:
            print(f"Attempt {attempt}: Exception occurred: {e}. Retrying...")
            time.sleep(1.5*attempt)

    print(f"Failed to fetch {symbol} after retries.")
    return None

