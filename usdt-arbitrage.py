#!/usr/bin/env python3
import requests, json, hashlib, hmac, time
binance_url = "https://api.binance.us/api/v3/"

api_key = open("api-public.txt").read().strip()
api_secret = open("api-secret.txt", 'rb').read().strip()

class APIResponseCodeError(Exception):
    pass

def send_request(endpoint, payload="", method="GET", sign=False):

    headers = {}
    headers["X-MBX-APIKEY"] = api_key
    headers["Accept"] = "application/json"

    request = requests.Request(
        method, binance_url+endpoint,
        headers=headers)
    if sign:
        payload += '&timestamp=' + str(get_timestamp())
        signature = hmac.new(api_secret, payload.encode('utf-8'), digestmod=hashlib.sha256)
        payload += '&signature=' + signature.hexdigest()

    if method == "GET":
        request.url += "?" + payload
    else:
        request.data = payload

    prepped = request.prepare()
    with requests.Session() as session:
        response = session.send(prepped)

    if response.status_code == 200:
        response_json = json.loads(response.content)
        return response_json
    else:
        raise APIResponseCodeError(response.status_code, response.content)

def get_balances(tickers):
    balances = send_request("account", method="GET", sign=True)["balances"]
    ret_vals = []
    for ticker in tickers:
        ticker_balance = 0.0
        for symbol in balances:
            if symbol['asset'] == ticker:
                ticker_balance = (symbol['free'])
                break
        ret_vals.append(ticker_balance)
    return ret_vals

def get_timestamp():
    response = send_request("time")
    return response["serverTime"]

while(True):
    usd_balance, usdt_balance = get_balances(["USD", "USDT"])
    if float(usd_balance) > 100:
        response = send_request("order", payload="symbol=USDTUSD&side=BUY&timeInForce=GTC&type=LIMIT&quantity=100&price=0.9989&newOrderRespType=FULL", method="POST", sign=True)
        print(json.dumps(response, indent=1))

    if float(usdt_balance) > 100:
        response = send_request("order", payload="symbol=USDTUSD&side=SELL&timeInForce=GTC&type=LIMIT&quantity=100&price=1.0015&newOrderRespType=FULL", method="POST", sign=True)
        print(json.dumps(response, indent=1))

    time.sleep(300)