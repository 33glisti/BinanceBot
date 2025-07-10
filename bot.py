import os
import json
import time
import logging
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from order_storage import save_or_update_orders, get_filled_orders, mark_order_filled

# Настройка логгера
logging.basicConfig(
    filename='events.log',
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log_info(message):
    print(message)
    logging.info(message)

def log_error(message):
    print(message)
    logging.error(message)

def get_moving_average(client, symbol, minutes=5):
    """Вычисляет среднюю цену за N минут (по свечам)."""
    klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=minutes)
    if not klines:
        raise ValueError(f"No Kline data for {symbol}")
    close_prices = [float(kline[4]) for kline in klines]  # kline[4] — цена закрытия
    return sum(close_prices) / len(close_prices)

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def load_settings(path='settings.json'):
    with open(path, 'r') as f:
        return json.load(f)

def get_open_orders(client, symbol):
    try:
        return client.get_open_orders(symbol=symbol)
    except BinanceAPIException as e:
        log_error(f"[ERROR] Failed to fetch orders for {symbol}: {e.message}")
        return []

def get_current_price(client, symbol):
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except BinanceAPIException as e:
        log_error(f"[ERROR] Failed to fetch price for {symbol}: {e.message}")
        return None

def place_opposite_order(client, original_order, settings, symbol_config):
    order_side = original_order.side
    order_price = float(original_order.price)
    symbol = original_order.symbol

    fee = settings['global']['fee_percent'] / 100
    profit = symbol_config['profit_percent'] / 100
    confirm = settings['global'].get('confirm_order', True)

    price_min = symbol_config['price_min']
    price_max = symbol_config['price_max']
    price_precision = symbol_config.get('price_precision', 2)

    if order_side == SIDE_BUY:
        volume = symbol_config['volume_sell']
        price = order_price + (order_price * profit) + ((order_price * volume) * fee)
        side = SIDE_SELL

        if price < price_min:
            log_info(f"[INFO] SKIPPED: {symbol} SELL price {price:.2f} < min {price_min:.4f}")
            return

    elif order_side == SIDE_SELL:
        volume = symbol_config['volume_buy']
        price = order_price - (order_price * profit) - ((order_price * volume) * fee)
        side = SIDE_BUY

        if price < price_min:
            log_info(f"[INFO] SKIPPED: {symbol} BUY price {price:.2f} < min {price_min:.4f}")
            return
        if price > price_max:
            log_info(f"[INFO] SKIPPED: {symbol} BUY price {price:.2f} > max {price_max:.4f}")
            return

        # Проверка адаптивного коридора (если включен)
        adaptive_percent = symbol_config.get('adaptive_limit_percent', 0)
        ma_period = symbol_config.get('moving_average_period_min', 0)
        if adaptive_percent > 0 and ma_period > 0:
            try:
                moving_avg = get_moving_average(client, symbol, minutes=ma_period)
                adaptive_limit = moving_avg * (1 + adaptive_percent / 100)
                if price > adaptive_limit:
                    log_info(f"[INFO] SKIPPED: {symbol} price {price:.{price_precision}f} > adaptive limit {adaptive_limit:.{price_precision}f} (MA {moving_avg:.{price_precision}f} + {adaptive_percent}%)")
                    return
            except Exception as e:
                log_error(f"[ERROR] Failed to get moving average for {symbol}: {e}")
                return

    price_str = f"{price:.{price_precision}f}"
    log_info(f"[INFO] Ready to place {side} {symbol} {volume} @ {price_str}")

    if confirm:
        user_input = input("Confirm order? [y/N]: ").strip().lower()
        if user_input != 'y':
            print("[INFO] Order cancelled by user.")
            return

    try:
        client.create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_LIMIT,
            quantity=volume,
            price=price_str,
            timeInForce=TIME_IN_FORCE_GTC
        )
        log_info(f"[INFO] Order placed: {side} {symbol} {volume} @ {price_str}")
    except BinanceAPIException as e:
        log_error(f"[ERROR] Failed to place order: {e.message}")

def main():
    settings = load_settings()
    api_key = settings['global']['api_key']
    api_sec = settings['global']['api_sec']
    poll_interval = settings['global'].get('poll_interval_sec', 10)

    client = Client(api_key, api_sec)

    symbols_config = settings['symbols']
    active_symbols = [s for s, cfg in symbols_config.items() if cfg.get('is_active')]
    if not active_symbols:
        print("[INFO] No active symbols found.")
        return

    try:
        while True:
            clear_console()
            for symbol in active_symbols:
                cfg = symbols_config[symbol]
                current_price = get_current_price(client, symbol)
                open_orders = get_open_orders(client, symbol)
                save_or_update_orders(open_orders)
                existing_orders = get_filled_orders([symbol])
                open_order_ids = {o['orderId'] for o in open_orders}

                for order in existing_orders:
                    if order.order_id not in open_order_ids:
                        log_info(f"[INFO] Order executed: {order.side} {symbol} {order.volume} @ {order.price}")
                        place_opposite_order(client, order, settings, cfg)
                        mark_order_filled(order.order_id)

                t = time.localtime()
                current_time = time.strftime("%H:%M:%S", t)
                print(f"[INFO] {symbol} | Price: {current_price:.4f} | Open orders: {len(open_orders)} | Profit: {cfg['profit_percent']} | {current_time}")
                for order in open_orders:
                    qty = float(order['origQty'])
                    price = float(order['price'])
                    precision = cfg.get('volume_precision', 1)
                    print(f" - {order['symbol']} {order['side']} {qty:.{precision}f} @ {price:.4f}")
                print()

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")

if __name__ == "__main__":
    main()
