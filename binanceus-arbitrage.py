#!/usr/bin/env python3
import hashlib
import hmac
import json
import math
import operator
import requests
import time
import logging

binance_url = "https://api.binance.us/api/v3/"
api_key = open("api-public.txt").read().strip()
api_secret = open("api-secret.txt", 'rb').read().strip()
real_trade = True
order_str = "order" if real_trade else "order/test"
profit_threshold = 0.25
max_trade_value = 100

timestamp = 0
sleep_seconds = 0.15

logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s',
                    level=logging.INFO,
                    datefmt='%Y-%m-%d %H:%M:%S')

headers = {"X-MBX-APIKEY": api_key, "Accept": "application/json"}

stablecoins = [
    "USD",
    "USDC",
    "USDT",
    "BUSD"
]

base_tokens = [
    "BTC",
    "ETH",
    "ONE",
    "ADA",
    "VTHO",
    "VET",
    "ZIL",
    "ATOM",
    "BAT",
    "ALGO",
    "XLM",
    "LTC",
    "DOGE",
    "ZRX",
    "OMG",
    "UNI",
    "NEO",
    "MATIC"
]


def round_decimals_down(number: float, decimals: int = 2):
    """
    Returns a value rounded down to a specific number of decimal places.
    :param decimals:
    :type number: number
    """
    if not isinstance(decimals, int):
        raise TypeError("decimal places must be an integer")
    elif decimals < 0:
        raise ValueError("decimal places has to be 0 or more")
    elif decimals == 0:
        return math.floor(number)

    factor = 10 ** decimals
    return math.floor(number * factor) / factor


class APIResponseCodeError(Exception):
    pass


class TradeFailed(Exception):
    pass


def send_request(endpoint, payload="", method="GET", sign=False):
    request = requests.Request(
        method, binance_url + endpoint,
        headers=headers)
    if sign:
        global timestamp
        payload += '&timestamp=' + str(int(timestamp))
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


def sync_timestamp():
    global timestamp
    timestamp = send_request("time")["serverTime"]


class ArbitrageTrader:
    prices = {}
    balances = {}
    current_stablecoin = ""
    profit_threshold = 0.0  # Percentage profit to make a trade
    exchange_info = {}

    def __init__(self, profit_threshold=0.225):
        sync_timestamp()
        self.profit_threshold = profit_threshold
        self.update_prices()
        self.update_balances()
        self.update_exchange_info()

    def update_prices(self):
        self.prices = send_request("ticker/bookTicker", method="GET")

    def update_balances(self):
        self.balances = send_request("account", method="GET", sign=True)["balances"]
        self.update_current_stablecoin()

    def update_current_stablecoin(self):
        stablecoin_balances = self.get_ticker_balances(stablecoins)
        self.current_stablecoin = max(stablecoin_balances.items(), key=operator.itemgetter(1))[0]

    def update_exchange_info(self):
        self.exchange_info = send_request("exchangeInfo", method="GET")

    def get_ticker_balances(self, tickers):
        ret_vals = {}
        for ticker in tickers:
            ticker_balance = 0.0
            for symbol in self.balances:
                if symbol['asset'] == ticker:
                    ticker_balance = (symbol['free'])
                    break
            ret_vals[ticker] = ticker_balance
        return ret_vals

    def get_pair_prices(self, pairs):
        ret_vals = {}
        for pair in pairs:
            for price in self.prices:
                if price['symbol'] == pair:
                    ret_vals[pair] = price
                    break
        return ret_vals

    def find_best_deal(self, ticker):
        possible_pairs = [ticker + stablecoin for stablecoin in stablecoins]
        pairs = self.get_pair_prices(possible_pairs)
        asks = {}
        ask_quantities = {}
        bids = {}
        bid_quantities = {}
        for pair in pairs:
            bids[pair] = float(pairs[pair]["bidPrice"])
            bid_quantities[pair] = float(pairs[pair]["bidQty"])
            asks[pair] = float(pairs[pair]["askPrice"])
            ask_quantities[pair] = float(pairs[pair]["askQty"])

        max_pair = max(bids.items(), key=operator.itemgetter(1))[0]
        min_pair = min(asks.items(), key=operator.itemgetter(1))[0]
        max_pair_bid = bids[max_pair]
        min_pair_ask = asks[min_pair]

        percent_diff = ((max_pair_bid / min_pair_ask) * 100) - 100
        effective_profit_threshold = self.profit_threshold
        if (ticker + self.current_stablecoin) == min_pair:
            effective_profit_threshold -= 0.075
        if percent_diff < effective_profit_threshold:
            return [None, None, 0, 0]

        liquidities = [asks[min_pair] * ask_quantities[min_pair], bids[max_pair] * bid_quantities[max_pair]]
        lowest_liquidity = min(liquidities)
        max_trade = min([lowest_liquidity, max_trade_value])
        if max_trade < 10:
            return [None, None, 0, 0]

        logging.info("Deal found: BUY {} at {}, SELL {} at {}, for PROFIT: {}%".format(min_pair, min_pair_ask, max_pair,
                                                                                       max_pair_bid, percent_diff))
        return [min_pair, max_pair, percent_diff, max_trade]

    def execute_trade_seq(self, min_pair, max_pair, token, max_trade):
        dest_stablecoin = [stablecoin for stablecoin in stablecoins if (token + stablecoin == min_pair)][0]
        if (token + self.current_stablecoin != min_pair) and not self.swap_stablecoin(dest_stablecoin, max_trade):
            return False
        dest_stablecoin_quantity = float(self.get_ticker_balances([dest_stablecoin])[dest_stablecoin])
        if dest_stablecoin_quantity > max_trade:
            dest_stablecoin_quantity = max_trade
        if not self.execute_trade(min_pair, "BUY", dest_stablecoin_quantity):
            return False

        to_sell_quantity = self.get_ticker_balances([token])[token]
        if not self.execute_trade(max_pair, "SELL", to_sell_quantity):
            return False
        return True

    def execute_trade(self, pair, action, quantity=max_trade_value):
        quantity = self.filter_quantity(quantity, pair)
        logging.info("Executing trade: {}ing {} of pair {}".format(action, quantity, pair))
        quantity_type = "quoteOrderQty" if action == "BUY" else "quantity"
        response = send_request("{}".format(order_str),
                                payload="symbol={}&side={}&type=MARKET&{}={}".format(pair, action, quantity_type,
                                                                                     quantity),
                                method="POST", sign=True)
        self.update_balances()
        try:
            return response["status"] == "FILLED"
        except KeyError:
            return False

    def swap_stablecoin(self, dest_stablecoin, max_trade):
        if float(self.get_ticker_balances([dest_stablecoin])[dest_stablecoin]) > max_trade:
            return True
        logging.info("Swapping {} for {}".format(self.current_stablecoin, dest_stablecoin))
        dest_stablecoin_quantity = max_trade
        if self.current_stablecoin == "USD":
            return self.execute_trade(dest_stablecoin + "USD", "BUY", dest_stablecoin_quantity)
        elif dest_stablecoin == "USD":
            return self.execute_trade(self.current_stablecoin + "USD", "SELL", dest_stablecoin_quantity)
        elif dest_stablecoin == "USDT" and self.current_stablecoin == "BUSD":
            return self.execute_trade("BUSDUSDT", "SELL", dest_stablecoin_quantity)
        elif dest_stablecoin == "BUSD" and self.current_stablecoin == "USDT":
            return self.execute_trade("BUSDUSDT", "BUY", dest_stablecoin_quantity)
        logging.info("Swap failed")
        return False

    def filter_quantity(self, quantity, pair):
        quantity = float(quantity)
        lot_size_filter = self.get_lot_size(pair)
        step_size = float(lot_size_filter["stepSize"])
        n = 0
        while step_size < 1.0:
            step_size *= 10
            n += 1
        min_quantity = float(lot_size_filter["minQty"])
        if quantity < min_quantity:
            quantity = min_quantity
        return str(round_decimals_down(quantity, n))

    def get_lot_size(self, pair):
        for symbol in self.exchange_info["symbols"]:
            if symbol["symbol"] == pair:
                for filter_type in symbol["filters"]:
                    if filter_type["filterType"] == "LOT_SIZE":
                        return filter_type


trader = ArbitrageTrader(profit_threshold=profit_threshold)
logging.info("Starting Arbitrage Trader")
while True:
    sync_timestamp()
    trader.update_prices()
    for trade_token in base_tokens:
        trade_min_pair, trade_max_pair, trade_percent_diff, this_max_trade = trader.find_best_deal(trade_token)
        if not trade_percent_diff:
            continue
        logging.info("Executing Trade Sequence: BUY {}, SELL {}, for PROFIT: {}%".format(trade_min_pair, trade_max_pair,
                                                                                         trade_percent_diff))
        trader.execute_trade_seq(trade_min_pair, trade_max_pair, trade_token, this_max_trade)
    time.sleep(sleep_seconds)
