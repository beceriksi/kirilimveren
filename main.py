import os
import ccxt
import pandas as pd
import numpy as np
import requests

# Telegram Bilgileri (GitHub Secrets'tan alınır)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")

# 1. Pivot High / Low Tespiti
def get_pivots(df, pivot_len=4):
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
            
    return ph_prices[-10:], ph_bars[-10:], pl_prices[-10:], pl_bars[-10:]

# 2. Çizgi Geçerlilik Kontrolü
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

# 3. Trend Çizgisi Bulma
def find_best_trendline(df, prices, bars, side, tol):
    n = len(prices)
    if n < 2:
        return None, None
    
    for i in range(n - 1, 0, -1):
        for j in range(i - 1, -1, -1):
            x1, y1 = bars[j], prices[j]
            x2, y2 = bars[i], prices[i]
            
            slope = (y2 - y1) / (x2 - x1)
            if side == 1 and slope >= 0:
                continue
            if side == -1 and slope <= 0:
                continue

            if is_line_valid(df, x1, y1, x2, y2, side, tol):
                intercept = y1 - slope * x1
                return slope, intercept
                
    return None, None

# 4. Kırılım ve Hacim Kontrolü
def check_breakout(symbol, timeframe='1h'):
    exchange = ccxt.binance()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # ATR Toleransı
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr = df['tr'].rolling(14).mean().iloc[-1]
        tol = 0.1 * atr
        
        # --- HACİM HESAPLAMASI ---
        # Son 20 barın ortalama hacmi (Şimdiki bar hariç)
        df['vol_ma'] = df['volume'].shift(1).rolling(20).mean()
        vol_curr = df['volume'].iloc[-1]
        vol_ma_val = df['vol_ma'].iloc[-1]
        
        # Hacim artış oranı (Örn: 1.5x, 2.1x gibi)
        vol_ratio = vol_curr / vol_ma_val if vol_ma_val > 0 else 1.0
        is_high_volume = vol_ratio >= 1.5  # Ortalama hacmin en az 1.5 katı mı?
        
        ph_prices, ph_bars, pl_prices, pl_bars = get_pivots(df, pivot_len=4)
        
        curr_bar = len(df) - 1
        prev_bar = len(df) - 2
        
        close_curr = df['close'].iloc[-1]
        close_prev = df['close'].iloc[-2]
        
        # --- DİRENÇ KIRILIMI ---
        if len(ph_prices) >= 2:
            res_slope, res_intercept = find_best_trendline(df, ph_prices, ph_bars, 1, tol)
            if res_slope is not None:
                res_val_curr = res_intercept + res_slope * curr_bar
                res_val_prev = res_intercept + res_slope * prev_bar
                
                if close_prev <= res_val_prev and close_curr > res_val_curr:
                    # Hacim durumuna göre başlık ve etiket belirle
                    header = "🔥 *YÜKSEK HACİMLİ DİRENÇ KIRILIMI!*" if is_high_volume else "🚀 *DİRENÇ KIRILDI (YUKARI)*"
                    vol_status = f"⚡ *Hacim Durumu:* Ortalama Hacmin *{round(vol_ratio, 2)} Katı!*" if is_high_volume else f"📊 *Hacim Oranı:* {round(vol_ratio, 2)}x (Normal)"
                    
                    send_telegram_message(
                        f"{header}\n\n"
                        f"• *Coin:* #{symbol.replace('/USDT', '')}\n"
                        f"• *Periyot:* {timeframe}\n"
                        f"• *Kapanış Fiyatı:* `{close_curr}`\n"
                        f"• *Trend Seviyesi:* `{round(res_val_curr, 4)}`\n"
                        f"• {vol_status}"
                    )

        # --- DESTEK KIRILIMI ---
        if len(pl_prices) >= 2:
            sup_slope, sup_intercept = find_best_trendline(df, pl_prices, pl_bars, -1, tol)
            if sup_slope is not None:
                sup_val_curr = sup_intercept + sup_slope * curr_bar
                sup_val_prev = sup_intercept + sup_slope * prev_bar
                
                if close_prev >= sup_val_prev and close_curr < sup_val_curr:
                    header = "💥 *HACİMLİ DESTEK KIRILIMI (DÜŞÜŞ)!*" if is_high_volume else "📉 *DESTEK KIRILDI (AŞAĞI)*"
                    vol_status = f"⚡ *Satış Hacmi:* Ortalama Hacmin *{round(vol_ratio, 2)} Katı!*" if is_high_volume else f"📊 *Hacim Oranı:* {round(vol_ratio, 2)}x (Normal)"
                    
                    send_telegram_message(
                        f"{header}\n\n"
                        f"• *Coin:* #{symbol.replace('/USDT', '')}\n"
                        f"• *Periyot:* {timeframe}\n"
                        f"• *Kapanış Fiyatı:* `{close_curr}`\n"
                        f"• *Trend Seviyesi:* `{round(sup_val_curr, 4)}`\n"
                        f"• {vol_status}"
                    )

    except Exception as e:
        pass

if __name__ == "__main__":
    exchange = ccxt.binance()
    tickers = exchange.fetch_tickers()
    usdt_pairs = [symbol for symbol in tickers if symbol.endswith('/USDT') and 'UP/' not in symbol and 'DOWN/' not in symbol]
    sorted_pairs = sorted(usdt_pairs, key=lambda x: tickers[x]['quoteVolume'] if tickers[x]['quoteVolume'] else 0, reverse=True)[:60]
    
    print("Tarama başlatıldı...")
    for symbol in sorted_pairs:
        check_breakout(symbol, timeframe='1h')
        check_breakout(symbol, timeframe='4h')
    print("Tarama bitti.")
