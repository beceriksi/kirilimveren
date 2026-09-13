import os
import ccxt
import pandas as pd
import numpy as np
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri bulunamadı!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram mesaj hatası: {e}")

# 1. Pivot Tespiti
def get_pivots(df, pivot_len=8):
    highs = df['high'].values
    lows = df['low'].values
    
    ph_prices, ph_bars = [], []
    pl_prices, pl_bars = [], []
    
    n = len(df)
    for i in range(pivot_len, n - pivot_len):
        if all(highs[i] >= highs[i - j] for j in range(1, pivot_len + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, pivot_len + 1)):
            ph_prices.append(highs[i])
            ph_bars.append(i)
            
        if all(lows[i] <= lows[i - j] for j in range(1, pivot_len + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, pivot_len + 1)):
            pl_prices.append(lows[i])
            pl_bars.append(i)
            
    return ph_prices[-12:], ph_bars[-12:], pl_prices[-12:], pl_bars[-12:]

# 2. Çizgi İhlal Kontrolü
def is_line_valid(df, x1, y1, x2, y2, side, tol):
    slope = (y2 - y1) / (x2 - x1)
    intercept = y1 - slope * x1
    highs = df['high'].values
    lows = df['low'].values
    
    for b in range(x1 + 1, x2):
        line_val = intercept + slope * b
        if side == 1:
            if highs[b] > line_val + tol:
                return False
        else:
            if lows[b] < line_val - tol:
                return False
    return True

# 3. Ana Trend Çizgisini Bulma
def find_best_trendline(df, prices, bars, side, tol):
    n = len(prices)
    if n < 2:
        return None, None
    
    for i in range(n - 1, 0, -1):
        for j in range(i - 1, -1, -1):
            x1, y1 = bars[j], prices[j]
            x2, y2 = bars[i], prices[i]
            
            if (x2 - x1) < 15: # En az 15 mum mesafe şartı
                continue
                
            slope = (y2 - y1) / (x2 - x1)
            if side == 1 and slope >= 0:
                continue
            if side == -1 and slope <= 0:
                continue

            if is_line_valid(df, x1, y1, x2, y2, side, tol):
                intercept = y1 - slope * x1
                return slope, intercept
                
    return None, None

# 4. Kırılım Analizi
def check_breakout(exchange, symbol, timeframe='1h'):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr = df['tr'].rolling(14).mean().iloc[-1]
        tol = 0.15 * atr
        
        df['vol_ma'] = df['volume'].shift(1).rolling(20).mean()
        vol_curr = df['volume'].iloc[-1]
        vol_ma_val = df['vol_ma'].iloc[-1]
        vol_ratio = vol_curr / vol_ma_val if vol_ma_val > 0 else 1.0
        is_high_volume = vol_ratio >= 1.5
        
        ph_prices, ph_bars, pl_prices, pl_bars = get_pivots(df, pivot_len=8)
        
        curr_bar = len(df) - 1
        prev_bar = len(df) - 2
        
        close_curr = df['close'].iloc[-1]
        close_prev = df['close'].iloc[-2]
        
        coin_name = symbol.split('/')[0]
        vol_str = f"⚡ *{round(vol_ratio, 1)}x Hacim*" if is_high_volume else f"📊 {round(vol_ratio, 1)}x Hacim"

        # DİRENÇ KIRILIMI (YUKARI)
        if len(ph_prices) >= 2:
            res_slope, res_intercept = find_best_trendline(df, ph_prices, ph_bars, 1, tol)
            if res_slope is not None:
                res_val_curr = res_intercept + res_slope * curr_bar
                res_val_prev = res_intercept + res_slope * prev_bar
                
                if close_prev <= res_val_prev and close_curr > res_val_curr:
                    return {
                        'coin': coin_name,
                        'type': 'UP',
                        'price': close_curr,
                        'level': round(res_val_curr, 4),
                        'vol': vol_str,
                        'high_vol': is_high_volume
                    }

        # DESTEK KIRILIMI (AŞAĞI)
        if len(pl_prices) >= 2:
            sup_slope, sup_intercept = find_best_trendline(df, pl_prices, pl_bars, -1, tol)
            if sup_slope is not None:
                sup_val_curr = sup_intercept + sup_slope * curr_bar
                sup_val_prev = sup_intercept + sup_slope * prev_bar
                
                if close_prev >= sup_val_prev and close_curr < sup_val_curr:
                    return {
                        'coin': coin_name,
                        'type': 'DOWN',
                        'price': close_curr,
                        'level': round(sup_val_curr, 4),
                        'vol': vol_str,
                        'high_vol': is_high_volume
                    }

    except Exception:
        pass
    return None

if __name__ == "__main__":
    exchange = ccxt.okx()
    tickers = exchange.fetch_tickers()
    
    usdt_pairs = [symbol for symbol in tickers if symbol.endswith('/USDT') and 'SWAP' not in symbol]
    sorted_pairs = sorted(usdt_pairs, key=lambda x: tickers[x]['quoteVolume'] if tickers[x]['quoteVolume'] else 0, reverse=True)[:60]
    
    print("Tarama başlatıldı...")
    
    results = {
        '1h': {'UP': [], 'DOWN': []},
        '4h': {'UP': [], 'DOWN': []}
    }
    
    for symbol in sorted_pairs:
        # 1 Saatlik Tarama
        res_1h = check_breakout(exchange, symbol, timeframe='1h')
        if res_1h:
            results['1h'][res_1h['type']].append(res_1h)
            
        # 4 Saatlik Tarama
        res_4h = check_breakout(exchange, symbol, timeframe='4h')
        if res_4h:
            results['4h'][res_4h['type']].append(res_4h)

    # TELEGRAM RAPORUNU OLUŞTUR
    total_signals = len(results['1h']['UP']) + len(results['1h']['DOWN']) + len(results['4h']['UP']) + len(results['4h']['DOWN'])
    
    if total_signals > 0:
        msg = "🔍 *PIYASA KIRILIM RAPORU*\n"
        msg += "═══════════════════\n\n"
        
        # 1 SAATLİK SİNYALLER
        if results['1h']['UP'] or results['1h']['DOWN']:
            msg += "⏱ *[ 1 SAATLİK PERİYOT ]*\n"
            if results['1h']['UP']:
                msg += "🟢 *Yukarı Kırılımlar (Direnç):*\n"
                for item in results['1h']['UP']:
                    msg += f"  • *#{item['coin']}* | Fiyat: `{item['price']}` | ({item['vol']})\n"
            if results['1h']['DOWN']:
                msg += "🔴 *Aşağı Kırılımlar (Destek):*\n"
                for item in results['1h']['DOWN']:
                    msg += f"  • *#{item['coin']}* | Fiyat: `{item['price']}` | ({item['vol']})\n"
            msg += "\n"

        # 4 SAATLİK SİNYALLER
        if results['4h']['UP'] or results['4h']['DOWN']:
            msg += "⏱ *[ 4 SAATLİK PERİYOT ]*\n"
            if results['4h']['UP']:
                msg += "🟢 *Yukarı Kırılımlar (Direnç):*\n"
                for item in results['4h']['UP']:
                    msg += f"  • *#{item['coin']}* | Fiyat: `{item['price']}` | ({item['vol']})\n"
            if results['4h']['DOWN']:
                msg += "🔴 *Aşağı Kırılımlar (Destek):*\n"
                for item in results['4h']['DOWN']:
                    msg += f"  • *#{item['coin']}* | Fiyat: `{item['price']}` | ({item['vol']})\n"
            msg += "\n"
            
        msg += "═══════════════════\n"
        msg += "🤖 *Otomatik Tarama Tamamlandı.*"
        
        send_telegram_message(msg)
        print("Telegram mesajı gönderildi.")
    else:
        print("Kırılım tespit edilmedi, mesaj atılmadı.")
