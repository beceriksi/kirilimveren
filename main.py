import os
import ccxt
import pandas as pd
import numpy as np
import requests

# Telegram Bilgileri (GitHub Secrets'tan kopyalanır)
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

# 1. Pivot Tespiti (Gürültüyü önlemek için pivot_len=8 yapıldı - Pine Script ile birebir)
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
        if side == 1: # Direnç
            if highs[b] > line_val + tol:
                return False
        else: # Destek
            if lows[b] < line_val - tol:
                return False
    return True

# 3. Ana Trend Çizgisini Bulma (Minimum 15 Bar Mesafe Şartı Eklenmiştir)
def find_best_trendline(df, prices, bars, side, tol):
    n = len(prices)
    if n < 2:
        return None, None
    
    # En anlamlı/geniş trend çizgisini bulmak için geriye doğru tara
    for i in range(n - 1, 0, -1):
        for j in range(i - 1, -1, -1):
            x1, y1 = bars[j], prices[j]
            x2, y2 = bars[i], prices[i]
            
            # Mikro önemsiz çizgileri engelle: İki tepe/dip arasında en az 15 mum olmalı
            if (x2 - x1) < 15:
                continue
                
            slope = (y2 - y1) / (x2 - x1)
            if side == 1 and slope >= 0: # Düşen trend aşağı meyil olmalı
                continue
            if side == -1 and slope <= 0: # Yükselen trend yukarı meyil olmalı
                continue

            if is_line_valid(df, x1, y1, x2, y2, side, tol):
                intercept = y1 - slope * x1
                return slope, intercept
                
    return None, None

# 4. Kırılım ve Hacim Analizi
def check_breakout(exchange, symbol, timeframe='1h'):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # ATR Toleransı (Fitil toleransı)
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr = df['tr'].rolling(14).mean().iloc[-1]
        tol = 0.15 * atr # Orijinal gösterge toleransı
        
        # Hacim Analizi
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
        
        # DİRENÇ KIRILIMI
        if len(ph_prices) >= 2:
            res_slope, res_intercept = find_best_trendline(df, ph_prices, ph_bars, 1, tol)
            if res_slope is not None:
                res_val_curr = res_intercept + res_slope * curr_bar
                res_val_prev = res_intercept + res_slope * prev_bar
                
                if close_prev <= res_val_prev and close_curr > res_val_curr:
                    header = "🔥 *YÜKSEK HACİMLİ DİRENÇ KIRILIMI!*" if is_high_volume else "🚀 *DİRENÇ KIRILDI (YUKARI)*"
                    vol_status = f"⚡ *Hacim Durumu:* Ortalama Hacmin *{round(vol_ratio, 2)} Katı!*" if is_high_volume else f"📊 *Hacim Oranı:* {round(vol_ratio, 2)}x (Normal)"
                    
                    send_telegram_message(
                        f"{header}\n\n"
                        f"• *Coin:* #{symbol.split('/')[0]}\n"
                        f"• *Periyot:* {timeframe}\n"
                        f"• *Kapanış Fiyatı:* `{close_curr}`\n"
                        f"• *Trend Seviyesi:* `{round(res_val_curr, 4)}`\n"
                        f"• {vol_status}"
                    )

        # DESTEK KIRILIMI
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
                        f"• *Coin:* #{symbol.split('/')[0]}\n"
                        f"• *Periyot:* {timeframe}\n"
                        f"• *Kapanış Fiyatı:* `{close_curr}`\n"
                        f"• *Trend Seviyesi:* `{round(sup_val_curr, 4)}`\n"
                        f"• {vol_status}"
                    )

    except Exception:
        pass

if __name__ == "__main__":
    exchange = ccxt.okx()
    tickers = exchange.fetch_tickers()
    
    usdt_pairs = [symbol for symbol in tickers if symbol.endswith('/USDT') and 'SWAP' not in symbol]
    sorted_pairs = sorted(usdt_pairs, key=lambda x: tickers[x]['quoteVolume'] if tickers[x]['quoteVolume'] else 0, reverse=True)[:60]
    
    print("OKX üzerinde stabil tarama başlatıldı...")
    for symbol in sorted_pairs:
        check_breakout(exchange, symbol, timeframe='1h')
        check_breakout(exchange, symbol, timeframe='4h')
    print("Tarama bitti.")
