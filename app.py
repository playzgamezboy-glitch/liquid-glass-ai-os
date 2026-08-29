import asyncio, json, math, os, statistics, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import xml.etree.ElementTree as ET

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="PaperTrade Lab")
STATE_FILE = Path("paper_state.json")
DEFAULT_SETTINGS = {"starting_cash": 50.0, "target_cash": 60.0, "position_stop_price": 30.0, "trade_frequency": "balanced", "news_mode": "filtered", "universe": ["SPY", "QQQ", "DIA", "IWM"]}

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except Exception: pass
    return {"cash": 50.0, "starting_cash": 50.0, "target_cash": 60.0, "positions": {}, "trades": [], "settings": DEFAULT_SETTINGS, "journal": []}
state = load_state()

def save_state(): STATE_FILE.write_text(json.dumps(state, indent=2))

class Settings(BaseModel):
    starting_cash: float = 50.0
    target_cash: float = 60.0
    position_stop_price: float = 30.0
    trade_frequency: str = "balanced"
    news_mode: str = "filtered"
    universe: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "DIA", "IWM"])
class SymbolRequest(BaseModel): symbol: str
class BacktestRequest(BaseModel): symbol: str = "SPY"; days: int = 730; initial_cash: float = 50.0
class TradeRequest(BaseModel): symbol: str; side: str; pounds: float = 10.0; reason: str = "Manual paper trade"

async def yahoo_chart(symbol: str, range_: str = "2y", interval: str = "1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol.upper())}?range={range_}&interval={interval}&events=div%2Csplits"
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent":"PaperTradeLab/1.0"}) as client:
        r = await client.get(url); r.raise_for_status(); result = r.json()["chart"]["result"][0]
    q = result["indicators"]["quote"][0]; timestamps = result.get("timestamp", [])
    rows=[]
    for i, ts in enumerate(timestamps):
        close = q.get("close", [])[i] if i < len(q.get("close", [])) else None
        if close is not None: rows.append({"date":datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), "open":q.get("open", [None]*len(timestamps))[i], "high":q.get("high", [None]*len(timestamps))[i], "low":q.get("low", [None]*len(timestamps))[i], "close":close, "volume":q.get("volume", [None]*len(timestamps))[i]})
    return rows

def sma(values, n): return sum(values[-n:]) / n if len(values) >= n else None
def rsi(values, n=14):
    if len(values) <= n: return None
    gains=[]; losses=[]
    for a,b in zip(values[-n-1:-1], values[-n:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    avg_gain=sum(gains)/n; avg_loss=sum(losses)/n
    return 100 if avg_loss == 0 else 100-(100/(1+avg_gain/avg_loss))
def signal(rows):
    closes=[x["close"] for x in rows]; price=closes[-1]; fast=sma(closes,20); slow=sma(closes,50); prev_fast=sma(closes[:-1],20); prev_slow=sma(closes[:-1],50); momentum=rsi(closes)
    if not slow: return {"action":"WAIT","price":price,"reason":"Waiting for enough history."}
    if fast > slow and prev_fast <= prev_slow and (momentum is None or momentum < 70): return {"action":"BUY","price":price,"reason":"20-day average crossed above 50-day average; RSI is not overheated."}
    if fast < slow and prev_fast >= prev_slow: return {"action":"SELL","price":price,"reason":"20-day average crossed below 50-day average."}
    return {"action":"HOLD","price":price,"reason":f"Trend is {('up' if fast > slow else 'down')}; waiting for a confirmed crossover."}

@app.get("/", response_class=HTMLResponse)
async def index(): return FileResponse("static/index.html")
@app.get("/api/settings")
async def get_settings(): return {"settings":state["settings"], "paper_only":True}
@app.post("/api/settings")
async def set_settings(req: Settings):
    state["settings"] = req.model_dump(); state["starting_cash"] = req.starting_cash; state["target_cash"] = req.target_cash; save_state(); return {"status":"saved","settings":state["settings"]}
@app.post("/api/reset")
async def reset():
    state.clear(); state.update({"cash":DEFAULT_SETTINGS["starting_cash"],"starting_cash":DEFAULT_SETTINGS["starting_cash"],"target_cash":DEFAULT_SETTINGS["target_cash"],"positions":{},"trades":[],"settings":DEFAULT_SETTINGS,"journal":[]}); save_state(); return {"status":"reset"}
@app.get("/api/quote/{symbol}")
async def quote_data(symbol: str):
    rows=await yahoo_chart(symbol,"5d","1d"); return {"symbol":symbol.upper(),"quote":rows[-1] if rows else None}
@app.get("/api/candles/{symbol}")
async def candles(symbol: str):
    rows=await yahoo_chart(symbol,"6mo","1d")
    return {"symbol":symbol.upper(),"candles":rows[-90:],"as_of":datetime.now(timezone.utc).isoformat()}
@app.get("/api/market")
async def market():
    async def one(symbol):
        try:
            rows=await yahoo_chart(symbol,"5d","1d"); return {"symbol":symbol,"quote":rows[-1] if rows else None,"change":(rows[-1]["close"]-rows[-2]["close"])/rows[-2]["close"]*100 if len(rows)>1 else 0}
        except Exception as e: return {"symbol":symbol,"error":str(e)}
    out=await asyncio.gather(*(one(symbol) for symbol in state["settings"].get("universe", DEFAULT_SETTINGS["universe"])))
    return {"market":out,"as_of":datetime.now(timezone.utc).isoformat()}
@app.get("/api/news/{symbol}")
async def news(symbol: str):
    url=f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote(symbol.upper())}&region=US&lang=en-US"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent":"PaperTradeLab/1.0"}) as client: r=await client.get(url)
    items=[]
    if r.status_code==200:
        try:
            root=ET.fromstring(r.text)
            for item in root.findall("./channel/item")[:8]: items.append({"title":item.findtext("title",""),"url":item.findtext("link",""),"published":item.findtext("pubDate","")})
        except ET.ParseError: pass
    return {"symbol":symbol.upper(),"items":items,"note":"News is a filter, not a standalone buy/sell signal. Headlines can be delayed or incomplete."}
@app.post("/api/backtest")
async def backtest(req: BacktestRequest):
    rows=await yahoo_chart(req.symbol,"5y","1d"); rows=rows[-req.days:]; cash=req.initial_cash; units=0.0; entry=None; curve=[]; trades=[]
    for i in range(55,len(rows)):
        window=rows[:i+1]; s=signal(window); price=rows[i]["close"]
        if units==0 and s["action"]=="BUY": units= cash/price; entry=price; cash=0; trades.append({"date":rows[i]["date"],"side":"BUY","price":price})
        elif units>0 and (s["action"]=="SELL" or units*price <= state["settings"].get("position_stop_price", 30.0)):
            cash=units*price; trades.append({"date":rows[i]["date"],"side":"SELL","price":price,"reason":"Trend exit or position-value stop"}); units=0; entry=None
        curve.append(cash+units*price)
    final=(cash+units*rows[-1]["close"]) if rows else req.initial_cash; peak=req.initial_cash; draw=0
    for v in curve: peak=max(peak,v); draw=min(draw,(v-peak)/peak if peak else 0)
    wins=0
    for a,b in zip(trades,trades[1:]):
        if a["side"]=="BUY" and b["side"]=="SELL" and b["price"]>a["price"]: wins+=1
    sells=max(1,len([x for x in trades if x["side"]=="SELL"]))
    return {"symbol":req.symbol.upper(),"initial":req.initial_cash,"final":round(final,2),"return_pct":round((final/req.initial_cash-1)*100,2),"max_drawdown_pct":round(draw*100,2),"trades":trades,"win_rate_pct":round(wins/sells*100,2),"method":"20/50-day SMA crossover with RSI confirmation; illustrative backtest, no fees/slippage modelled."}
@app.get("/api/portfolio")
async def portfolio():
    total=state["cash"]; positions=[]
    for symbol,p in state["positions"].items():
        try: q=(await yahoo_chart(symbol,"5d","1d"))[-1]["close"]
        except Exception: q=p["avg_price"]
        value=p["units"]*q; total+=value; positions.append({**p,"symbol":symbol,"last_price":q,"value":value,"pnl":(q-p["avg_price"])*p["units"]})
    return {"cash":state["cash"],"total":total,"target":state["target_cash"],"positions":positions,"trades":state["trades"][-30:],"paper_only":True}
@app.post("/api/paper-trade")
async def paper_trade(req: TradeRequest):
    if req.side not in {"BUY","SELL"}: return {"status":"error","message":"Side must be BUY or SELL."}
    rows=await yahoo_chart(req.symbol,"5d","1d"); price=rows[-1]["close"]
    symbol=req.symbol.upper(); p=state["positions"].get(symbol)
    if req.side=="BUY":
        spend=min(req.pounds,state["cash"]); units=spend/price
        if spend<=0: return {"status":"error","message":"Not enough paper cash."}
        if p: p["units"]+=units; p["avg_price"]=(p["avg_price"]*p["units"]+price*units)/(p["units"]+units)
        else: state["positions"][symbol]={"units":units,"avg_price":price,"stop_price":state["settings"]["position_stop_price"]}
        state["cash"]-=spend
    else:
        if not p: return {"status":"error","message":"No paper position to sell."}
        units=min(p["units"],req.pounds/price); state["cash"]+=units*price; p["units"]-=units
        if p["units"]<1e-9: del state["positions"][symbol]
    trade={"id":str(uuid.uuid4()),"time":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"side":req.side,"price":price,"reason":req.reason,"paper":True}; state["trades"].append(trade); save_state(); return {"status":"executed","trade":trade}
@app.get("/api/signal/{symbol}")
async def get_signal(symbol: str):
    rows=await yahoo_chart(symbol,"2y","1d"); s=signal(rows); n=await news(symbol); blocked=any(any(w in x["title"].lower() for w in ["bankrupt","fraud","investigation","downgrade","offering"]) for x in n["items"][:5]);
    if blocked and s["action"]=="BUY": s={**s,"action":"WAIT","reason":"Filtered: recent headline risk detected; waiting for clarity."}
    return {"symbol":symbol.upper(),"signal":s,"news_filter":"BLOCKED" if blocked else "CLEAR","news":n["items"][:5]}
if __name__=="__main__":
    import uvicorn; uvicorn.run(app,host="127.0.0.1",port=8000)
