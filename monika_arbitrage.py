import requests
import json
import hmac, hashlib
import multiprocessing
import os
import csv

root_site = 'https://api.binance.com'
defaultPublicKey = 'vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A'
defaultSecretKey = 'NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j'

commands = {
    'ping': '/api/v1/ping',
    'time': '/api/v1/time',
    'orderbook': '/api/v1/depth',
    'trade': '/api/v3/order',
    'candle': '/api/v1/klines',
    'account': '/api/v3/account'
}

cred_file = 'api.cred.json'


try:
    with open(cred_file, 'r') as f:
        data = json.load(f)
        publicKey = data['public_key']
        secretKey = data['secret_key']
except IOError:
    publicKey = defaultPublicKey
    secretKey = defaultSecretKey


def compose_query_string(params):
    data = r''
    for key in sorted(params.keys()):
        data += r'%s=%s&' % (key[1:], params[key])
    
    data += r'timestamp=%s' % serverTime()
    return data

def signer(data):
    return hmac.new(secretKey, data, hashlib.sha256).hexdigest()


def serverTime():
    return requests.get(root_site + time).json()['serverTime']



eth_min_vol = 1
btc_min_vol = 0.06
safety_ratio = 0.7

def check_volume(base_coin, prices):
    if base_coin == 'btc':
        thresh = btc_min_vol
    elif base_coin == 'eth':
        thresh = eth_min_vol
        
    total_vol = 0
    for price, vol, _ in prices:
        price = float(price)
        vol = float(vol)
        last_price = price
        total_vol += price*vol
        if total_vol >= thresh:
            break
            
    return last_price, total_vol


def log_maker(filename):
    if not os.path.exists(filename):
        with open(filename, 'wb') as f:
            pass

    def decorator(fcn):
        def log(*args, **kwargs):
            with open(filename, 'a') as f:
                f.write(', '.join(args))
                f.write('\n')
                f.write(kwargs['data'].text)
                f.write('\n\n')

        setattr(fcn, 'log', log)
        return fcn

    return decorator


@log_maker('price_fail.err')
def log_price_failure(target_coin, base_coin, tradeType, data):
    log_price_failure.log(target_coin, base_coin, tradeType, data=data)

@log_maker('trade_fail.err')
def log_trade_failure(symbol, side, data):
    log_trade_failure.log(symbol, side, data=data)


def get_price(target_coin, base_coin, tradeType):
    data = requests.get(root_site + orderbook, params={'symbol':'%s%s'%(target_coin.upper(), base_coin.upper()), 'limit': '10'})
    if data.ok:
        data = data.json()
        last_price, total_vol = check_volume(base_coin, data[tradeType])
        return last_price, total_vol
    else:
        log_price_failure(target_coin, base_coin, tradeType, data)
        return (0, 0)


def make_trade(symbol, side, quantity, price):
    template = {
        '1symbol': symbol.upper(),
        '2side': side.upper(),
        '3type': 'LIMIT',
        '4timeInForce': 'GTC',
        '5quantity': quantity,
        '6price': price
    }

    data = compose_query_string(template)
    r = requests.post(root_site + trade + '?' + data + '&signature=%s' % signer(data), headers={'X-MBX-APIKEY': publicKey})

    if r.ok:
        r = r.json()
        return r, r['orderId']
    else:
        log_trade_failure(symbol, side, data)
        return None, None


def check_order(symbol, orderId):
    template = {
        '1symbol': symbol.upper(),
        '2orderId': orderId
    }

    data = compose_query_string(template)
    r = requests.get(root_site + trade + '?' + data + '&signature=%s' % signer(data), headers={'X-MBX-APIKEY': publicKey}).json()
    return r, r['status']



def wait_done(symbol, orderId):
    while(check_order(symbol, orderId)[1] != u'FILLED'):
        pass


def eth_btc_alt_eth(alt):
    acq_btc, btc_vol1 = get_price('eth', 'btc', 'bids')
    acq_alt, btc_vol2 = get_price(alt, 'btc', 'asks')
    acq_eth, eth_vol = get_price(alt, 'eth', 'bids')
    btc_vol3 = eth_vol*acq_btc
    
    profit_ratio = acq_btc*(1.0/acq_alt)*acq_eth
    return profit_ratio, min(btc_vol1, btc_vol2, btc_vol3), acq_btc, acq_alt, acq_eth


def eth_alt_btc_eth(alt):
    acq_alt, eth_vol = get_price(alt, 'eth', 'asks')
    acq_btc, btc_vol1 = get_price(alt, 'btc', 'bids')
    acq_eth, btc_vol2 = get_price('eth', 'btc', 'asks')
    btc_vol3 = eth_vol*acq_eth
    
    profit_ratio = (1.0/acq_alt)*acq_btc*(1.0/acq_eth)
    return profit_ratio, min(btc_vol1, btc_vol2, btc_vol3), acq_alt, acq_btc, acq_eth


candidates = ['bcd', 'dgd', 'xzc', 'ppt', 'nav', 'nebl', 'waves', 'kmd', 'btg', 'ark', 'storj', 'strat', 'zec', 'mod', 'oax',
              'iota', 'neo', 'icx', 'req', 'appc', 'ven', 'eos', 'poe', 'ltc', 'xvg', 'xlm', 'bnb', 'ada', 'arn', 'xrp', 'trx']

stride = 8
alt_input = [(idx, candidates[x:x+stride]) for idx, x in enumerate(xrange(0, len(candidates), stride))]


price_thresh = 1.003
output_file = 'coin_profit_%s.csv'


def monika_arbitrage(pid, targets):
    while True:
        for alt in targets:
            price1, vol1, p11, p12, p13 = eth_btc_alt_eth(alt)
            price2, vol2, p21, p22, p23 = eth_alt_btc_eth(alt)
            
            if (price1 >= price_thresh or price2 >= price_thresh):
                with open(output_file % pid, 'a') as f:
                    writer = csv.writer(f)
                    writer.writerow([alt, price1, vol1, price2, vol2])
                    
                vol1 = vol1 * safety_ratio
                vol2 = vol2 * safety_ratio
                
                if price1 > price2:
                    symbol = 'ethbtc'
                    vol = eth_min * safety_ratio
                    sell_eth_btc, orderId = trade_coin(symbol, 'sell', vol, p11)
                    if orderId is None:
                        continue
                    wait_done(symbol, orderId)

                    symbol = '%sbtc' % alt
                    vol = (vol * p11) / p12
                    buy_alt_btc, orderId = trade_coin(symbol, 'buy', vol, p12)
                    if orderId is None:
                        continue
                    wait_done(symbol, orderId)

                    symbol = '%seth' % alt
                    sell_alt_eth, orderId = trade_coin(symbol, 'sell', vol, p13)
                    if orderId is None:
                        continue
                    wait_done(symbol, orderId)
                else:
                    symbol = '%seth' % alt
                    vol = (eth_min * safety_ratio) / p21
                    buy_alt_eth, orderId = trade_coin(symbol, 'buy', vol, p21)
                    if orderId is None:
                        continue
                    wait_done(symbol, orderId)

                    symbol = '%sbtc' % alt
                    sell_alt_btc, orderId = trade_coin(symbol, 'sell', vol, p22)
                    if orderId is None:
                        continue
                    wait_done(symbol, orderId)

                    symbol = 'ethbtc'
                    vol = vol * p22
                    buy_eth_btc, orderId = trade_coin(symbol, 'buy', vol, p23)
                    if orderId is None:
                        continue
                    wait_done(symbol, orderId)
                

for i, alts in alt_input:
    if not os.path.exists(output_file % i):
        with open(output_file % i, 'wb') as f:
            writer = csv.writer(f)
            writer.writerow(alts)
            

p = multiprocessing.Pool(len(alt_input))
p.map(monika_arbitrage, alt_input)
