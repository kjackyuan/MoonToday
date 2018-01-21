import requests
import json
import hmac, hashlib
import multiprocessing
import os
import csv

root_site = 'https://api.binance.com'

with open('api.cred.json', 'r') as f:
    data = json.load(f)
    publicKey = data['public_key']
    secretKey = data['secret_key']


ping = '/api/v1/ping'
time = '/api/v1/time'

orderbook = '/api/v1/depth'
trade = '/api/v3/order'
candle = '/api/v1/klines'
account = '/api/v3/account'

def serverTime():
    return requests.get(root_site + time).json()['serverTime']

def data_string(params):
    data = r''
    for key in sorted(params.keys()):
        data += r'%s=%s&' % (key[1:], params[key])
    
    data += r'timestamp=%s' % serverTime()
    return data

def signer(data):
    return hmac.new(secretKey, data, hashlib.sha256).hexdigest()

def trade_coin(symbol, side, quantity, price):
    template = {
        '1symbol': symbol.upper(),
        '2side': side.upper(),
        '3type': 'LIMIT',
        '4timeInForce': 'GTC',
        '5quantity': quantity,
        '6price': price
    }

    data = data_string(template)
    print data
    print signer(data)
    r = requests.post(root_site + trade + '?' + data + '&signature=%s' % signer(data), headers={'X-MBX-APIKEY': publicKey}).json()
    print r
    return r, r['orderId']

def check_order(symbol, orderId):
    template = {
        '1symbol': symbol.upper(),
        '2orderId': orderId
    }

    data = data_string(template)
    r = requests.get(root_site + trade + '?' + data + '&signature=%s' % signer(data), headers={'X-MBX-APIKEY': publicKey}).json()
    print r
    return r, r['status']

def wait_done(symbol, orderId):
    while(check_order(symbol, orderId)[1] != u'FILLED'):
        pass
    
eth_min = 1
btc_min = 0.06
safety_ratio = 0.7

def sat_vol(top, bot, prices):
    if bot == 'btc':
        thresh = btc_min
    elif bot == 'eth':
        thresh = eth_min
        
    total_vol = 0
    for price, vol, _ in prices:
        price = float(price)
        vol = float(vol)
        last_price = price
        total_vol += price*vol
        if total_vol >= thresh:
            break
            
    return last_price, total_vol


if not os.path.exists('error_log.txt'):
    with open('error_log.txt', 'wb') as f:
        pass

def get_price(top, bot, tradeType):
    data = requests.get(root_site + orderbook, params={'symbol':'%s%s'%(top.upper(), bot.upper()), 'limit': '10'})
    if data.ok:
        data = data.json()
        return sat_vol(top, bot, data[tradeType])
    else:
        with open('error_log.txt', 'a') as f:
            f.write('%s, %s, %s:\n' % (top, bot, tradeType))
            f.write(data.text)
            f.write('\n\n\n\n')
        return (0, 0)


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
#candidates = ['bnb']

stride = 8
alt_input = [(idx, candidates[x:x+stride]) for idx, x in enumerate(xrange(0, len(candidates), stride))]


price_thresh = 1.003
output_file = 'shitcoin_profit_%s.csv'
heartbeat = 100

if not os.path.exists('alive.csv'):
    with open('alive.csv', 'wb') as f:
        pass


def monika_monitor((pid, targets)):
    counter = 0
    while True:
        if counter == 0 or counter == heartbeat:
            counter = 1
            with open('alive.csv', 'a') as f:
                csv.writer(f).writerow([pid])

        counter += 1

        for alt in targets:
            price1, vol1, p11, p12, p13 = eth_btc_alt_eth(alt)
            price2, vol2, p21, p22, p23 = eth_alt_btc_eth(alt)
            
            if (price1 >= price_thresh or price2 >= price_thresh):
                print 'TRADE! %s' % alt
                with open(output_file % pid, 'a') as f:
                    writer = csv.writer(f)
                    writer.writerow([alt, price1, vol1, price2, vol2])
                    
                vol1 = vol1 * safety_ratio
                vol2 = vol2 * safety_ratio
                
                if price1 > price2:
                    symbol = 'ethbtc'
                    vol = eth_min * safety_ratio
                    sell_eth_btc, orderId = trade_coin(symbol, 'sell', vol, p11)
                    wait_done(symbol, orderId)

                    symbol = '%sbtc' % alt
                    vol = (vol * p11) / p12
                    buy_alt_btc, orderId = trade_coin(symbol, 'buy', vol, p12)
                    wait_done(symbol, orderId)

                    symbol = '%seth' % alt
                    sell_alt_eth, orderId = trade_coin(symbol, 'sell', vol, p13)
                    wait_done(symbol, orderId)
                else:
                    symbol = '%seth' % alt
                    vol = (eth_min * safety_ratio) / p21
                    buy_alt_eth, orderId = trade_coin(symbol, 'buy', vol, p21)
                    wait_done(symbol, orderId)

                    symbol = '%sbtc' % alt
                    sell_alt_btc, orderId = trade_coin(symbol, 'sell', vol, p22)
                    wait_done(symbol, orderId)

                    symbol = 'ethbtc'
                    vol = vol * p22
                    buy_eth_btc, orderId = trade_coin(symbol, 'buy', vol, p23)
                    wait_done(symbol, orderId)
                

for i, alts in alt_input:
    if not os.path.exists(output_file % i):
        with open(output_file % i, 'wb') as f:
            writer = csv.writer(f)
            writer.writerow(alts)
            

p = multiprocessing.Pool(len(alt_input))
p.map(monika_monitor, alt_input)

# monika_monitor(alt_input[0])
