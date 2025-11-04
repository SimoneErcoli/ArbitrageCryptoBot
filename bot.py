# PER ESEGUIRE IL BOT CON DATI REALI (Richiede setup e chiavi API):
# 1. Installa la libreria CCXT: pip install ccxt
# 2. Questo script utilizza le capacità asincrone di Python (asyncio) per
#    velocizzare il polling e l'esecuzione dei trade.
# 3. Inserisci le tue chiavi API nella sezione CONFIGURAZIONE API.

import asyncio
import time
import random
import os
import ccxt.async_support as ccxt # Ora usiamo la versione asincrona di ccxt

# --- Configurazione Globale ---
INITIAL_CASH = 100.0  # Saldo iniziale in USD
ARBITRAGE_THRESHOLD = 0.005  # Soglia minima di profitto NETTO (0.5%)
TRADE_SIZE = 100.0   # Dimensione fissa di ogni trade simulato in USD
FEES = 0.001         # Commissione di trading simulata (0.1% per ogni lato del trade)
POLLING_INTERVAL_SEC = 1.5  # Intervallo di polling per i dati di prezzo (minimo, in realtà sarà più veloce)

# --- CONFIGURAZIONE API (PLACEHOLDER) ---
# In un bot reale, queste chiavi andrebbero caricate da un file .env per sicurezza.
API_CONFIG = {
    'Exchange A': {'name': 'binance', 'apiKey': 'YOUR_API_KEY_A', 'secret': 'YOUR_SECRET_A'},
    'Exchange B': {'name': 'kraken', 'apiKey': 'YOUR_API_KEY_B', 'secret': 'YOUR_SECRET_B'},
    'Exchange C': {'name': 'kucoin', 'apiKey': 'YOUR_API_KEY_C', 'secret': 'YOUR_SECRET_C'},
}

# Coppie di trading che il bot monitorerà
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT']
EXCHANGES = list(API_CONFIG.keys()) # ['Exchange A', 'Exchange B', 'Exchange C']


# Dati di fallback/simulazione (usati se l'API reale non è configurata)
simulated_prices = {
    'BTC/USDT': {'Exchange A': 60000.0, 'Exchange B': 60150.0, 'Exchange C': 59900.0},
    'ETH/USDT': {'Exchange A': 3200.0, 'Exchange B': 3205.0, 'Exchange C': 3195.0},
    'XRP/USDT': {'Exchange A': 0.52, 'Exchange B': 0.51, 'Exchange C': 0.525},
}

# Stato del Portafoglio
portfolio = {
    'cash': INITIAL_CASH,
    'total_profit': 0.0,
    'trades_executed': 0,
    'last_update_time': "N/A"
}

# Dizionario per memorizzare le istanze degli exchange CCXT
exchange_instances = {} 


# --- Funzioni di Core Logic ---

def clear_console():
    """Cancella la console per mantenere l'output pulito come in una UI."""
    os.system('cls' if os.name == 'nt' else 'clear')


async def initialize_exchanges():
    """
    Inizializza le istanze CCXT asincrone per tutti gli exchange configurati.
    """
    for alias, config in API_CONFIG.items():
        exchange_id = config['name']
        try:
            # Recupera la classe corretta dal modulo ccxt.async_support
            ExchangeClass = getattr(ccxt, exchange_id)
            exchange = ExchangeClass({
                'apiKey': config['apiKey'],
                'secret': config['secret'],
                'timeout': 10000, # 10 secondi di timeout
                'enableRateLimit': True,
            })
            exchange_instances[alias] = exchange
            print(f"✅ Exchange {alias} ({exchange_id}) inizializzato.")
        except AttributeError:
            print(f"❌ Exchange {alias} ({exchange_id}) non supportato da CCXT o nome errato.")


async def fetch_prices_real():
    """
    Funzione Reale: Tenta di connettersi agli exchange tramite CCXT.
    Questa funzione ora è una coroutine e può essere eseguita in parallelo.
    """
    global simulated_prices, portfolio
    
    new_prices = {}
    
    # ----------------------------------------------------------------------
    # Fase 1: Creazione dei task di fetching in parallelo
    # ----------------------------------------------------------------------
    
    fetch_tasks = []
    
    # Se le istanze non sono inizializzate (es. chiavi mancanti), ricadiamo sulla simulazione
    if not exchange_instances:
        # Esegue la simulazione dei prezzi
        for asset in simulated_prices:
            for exchange in EXCHANGES:
                current_price = simulated_prices[asset][exchange]
                delta = (random.random() - 0.5) * 0.01 * current_price
                new_price = current_price + delta
                simulated_prices[asset][exchange] = max(0.01, new_price)
        portfolio['last_update_time'] = time.strftime('%H:%M:%S')
        return

    # Se le istanze ci sono, crea i task CCXT
    for symbol in SYMBOLS:
        new_prices[symbol] = {}
        for alias, exchange in exchange_instances.items():
            # Aggiunge il task alla lista per l'esecuzione parallela
            fetch_tasks.append(
                asyncio.create_task(
                    fetch_exchange_data(exchange, symbol, alias)
                )
            )

    # ----------------------------------------------------------------------
    # Fase 2: Esecuzione in parallelo
    # ----------------------------------------------------------------------
    
    # Raccoglie i risultati di tutti i task
    results = await asyncio.gather(*fetch_tasks)

    # Processa i risultati
    for symbol, alias, ask_price in results:
        if symbol and ask_price is not None:
            new_prices[symbol][alias] = ask_price
        else:
            # Usa il prezzo precedente in caso di errore di fetching
            new_prices[symbol][alias] = simulated_prices[symbol][alias]

    simulated_prices = new_prices
    portfolio['last_update_time'] = time.strftime('%H:%M:%S')

# Coroutine ausiliaria per il fetching di un singolo exchange/simbolo
async def fetch_exchange_data(exchange, symbol, alias):
    """Fetches order book data for a single symbol on a single exchange."""
    try:
        # fetch_ticker è spesso più veloce di fetch_order_book per il solo prezzo
        ticker = await exchange.fetch_ticker(symbol)
        ask_price = ticker.get('ask') 
        # Per l'arbitraggio, il prezzo a cui si può vendere è l'ASK (il prezzo di offerta)
        if ask_price is None:
             raise ValueError("Ask price not available.")
        
        return symbol, alias, ask_price

    except Exception as e:
        # print(f"ATTENZIONE: Errore nel fetch di {symbol} su {alias}: {e}")
        return None, None, None # Indica fallimento


async def execute_trade(asset, buy_price, sell_price, buy_exchange, sell_exchange):
    """
    Gestisce l'esecuzione di un trade di arbitraggio in modo asincrono.
    """
    global portfolio
    
    trade_cost = TRADE_SIZE
    
    # 1. Calcolo del profitto NETTO
    buy_cost_with_fee = trade_cost * (1 + FEES)
    asset_amount = trade_cost / buy_price
    revenue = asset_amount * sell_price * (1 - FEES)
    net_profit = revenue - buy_cost_with_fee
    net_spread = net_profit / trade_cost

    if net_spread > ARBITRAGE_THRESHOLD:
        
        # --- LOGICA DI ESECUZIONE REALE ASINCRONA ---
        if exchange_instances:
            print("Tentativo di esecuzione trade parallelo...")
            
            try:
                buy_exchange_instance = exchange_instances[buy_exchange]
                sell_exchange_instance = exchange_instances[sell_exchange]
                
                # Calcola la quantità esatta da comprare (in base al TRADE_SIZE in USDT)
                buy_amount = trade_cost / buy_price
                # NOTA: Per un arbitraggio perfetto, la quantità venduta deve essere uguale a quella comprata.
                sell_amount = buy_amount 
                
                # Crea i task di ordine (uso Market Order per simulare velocità)
                buy_task = buy_exchange_instance.create_market_buy_order(asset, buy_amount)
                sell_task = sell_exchange_instance.create_market_sell_order(asset, sell_amount)
                
                # Esecuzione PARALLELA dei due ordini (essenziale per l'arbitraggio)
                buy_order, sell_order = await asyncio.gather(buy_task, sell_task)
                
                print(f"✅ Ordine di Acquisto: {buy_order['id']} | ✅ Ordine di Vendita: {sell_order['id']}")
                
            except Exception as e:
                print(f"❌ ERRORE CRITICO NELL'ESECUZIONE PARALLELA: {e}")
                # In un bot reale, qui andrebbe gestito il 'partial fill' o 'single fill'
                return # Interrompe l'aggiornamento del portafoglio se fallisce l'esecuzione
        
        # --- AGGIORNAMENTO PORTAFOGLIO SIMULATO ---
        portfolio['cash'] += net_profit
        portfolio['total_profit'] += net_profit
        portfolio['trades_executed'] += 1
        
        profit_percent = net_spread * 100
        
        # Log del trade eseguito
        print("--------------------------------------------------")
        print(f"🚨 TRADE ESEGUITO! #{portfolio['trades_executed']} ({time.strftime('%H:%M:%S')})")
        print(f"Asset: {asset} | Profitto Netto: ${net_profit:.4f} ({profit_percent:.4f}%)")
        print(f"Azione: Compra su {buy_exchange} a ${buy_price:.4f} / Vendi su {sell_exchange} a ${sell_price:.4f}")
        print("--------------------------------------------------")


async def find_arbitrage_opportunities():
    """
    Cerca opportunità di arbitraggio calcolando lo spread tra tutte le coppie di borse.
    """
    trade_tasks = []
    
    for asset in SYMBOLS:
        asset_prices = simulated_prices[asset]

        for i in range(len(EXCHANGES)):
            for j in range(i + 1, len(EXCHANGES)):
                exchange_a = EXCHANGES[i]
                exchange_b = EXCHANGES[j]

                price_a = asset_prices[exchange_a]
                price_b = asset_prices[exchange_b]

                # Scenario 1: Compra su A, Vendi su B
                if price_b > price_a:
                    trade_tasks.append(
                        execute_trade(asset, price_a, price_b, exchange_a, exchange_b)
                    )

                # Scenario 2: Compra su B, Vendi su A
                if price_a > price_b:
                    trade_tasks.append(
                        execute_trade(asset, price_b, price_a, exchange_b, exchange_a)
                    )

    # Esegue tutte le potenziali esecuzioni di trade in parallelo (anche se la maggior parte non triggera)
    if trade_tasks:
        await asyncio.gather(*trade_tasks)


def display_status():
    """Mostra lo stato del portafoglio e le quotazioni attuali."""
    
    # 1. Intestazione e Portafoglio
    clear_console()
    print("==========================================================")
    print(f"| ARBITRAGGIO CRIPTOBOT - Backend Python Asincrono |")
    print("==========================================================")
    
    profit_sign = "+" if portfolio['total_profit'] >= 0 else ""
    
    print(f"Portafoglio Cash Attuale: $ {portfolio['cash']:.2f}")
    print(f"Profitto Totale Netto:    $ {profit_sign}{portfolio['total_profit']:.2f}")
    print(f"Trades Eseguiti:          {portfolio['trades_executed']}")
    print(f"Ultimo Aggiornamento Dati: {portfolio['last_update_time']}")
    print("----------------------------------------------------------")
    print(f"Soglia Netta Arbitraggio: {ARBITRAGE_THRESHOLD * 100}% | Intervallo di Attesa: {POLLING_INTERVAL_SEC}s")
    print("----------------------------------------------------------")
    
    # 2. Tabella Prezzi
    print("{:<10} {:>15} {:>15} {:>15}".format("Asset", EXCHANGES[0], EXCHANGES[1], EXCHANGES[2]))
    print("-" * 60)
    
    for asset, prices in simulated_prices.items():
        # Formattazione per visualizzare il nome base dell'asset (e.g., BTC/USDT -> BTC)
        asset_name = asset.split('/')[0]
        print("{:<10} {:>15.4f} {:>15.4f} {:>15.4f}".format(
            asset_name, prices[EXCHANGES[0]], prices[EXCHANGES[1]], prices[EXCHANGES[2]]
        ))
    
    print("-" * 60)
    print("In attesa del prossimo ciclo...")


async def main():
    """Ciclo principale del bot asincrono."""
    print("Avvio del Bot di Arbitraggio Criptovalute (Asincrono)...")
    
    # Inizializza gli exchange (importante per CCXT Asincrono)
    await initialize_exchanges()

    while True:
        try:
            # --- Fase 1: Aggiornamento Dati in parallelo ---
            # fetch_prices_real() tenta di connettersi a tutti gli exchange in parallelo
            await fetch_prices_real() 
            
            # --- Fase 2: Logica e Display ---
            display_status()
            
            # --- Fase 3: Ricerca e Potenziale Esecuzione Trade in parallelo ---
            await find_arbitrage_opportunities()
            
            # Attende per l'intervallo specificato, permettendo ad altre coroutine di essere eseguite
            await asyncio.sleep(POLLING_INTERVAL_SEC) 
            
        except KeyboardInterrupt:
            # Gestione dell'interruzione con CTRL+C
            print("\n----------------------------------------------------------")
            print("Simulazione interrotta dall'utente.")
            print(f"Risultato Finale: Cash ${portfolio['cash']:.2f} | Profitto Totale ${portfolio['total_profit']:.2f}")
            print("----------------------------------------------------------")
            
            # Chiude tutte le connessioni CCXT aperte in modo asincrono
            for alias, exchange in exchange_instances.items():
                await exchange.close()
            break
        except Exception as e:
            print(f"Errore critico non gestito nel loop principale: {e}. Riprova tra 5 secondi...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgramma terminato.")
