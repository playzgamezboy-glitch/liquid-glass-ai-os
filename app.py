import asyncio,json,uuid,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse,HTMLResponse
from pydantic import BaseModel,Field
app=FastAPI(title='PaperTrade Lab Crypto')
STATE_FILE=Path('paper_state.json')
DEFAULT={'starting_cash':50.0,'target_cash':60.0,'position_size':10.0,'max_loss':3.0,'auto_paper':False,'interval':'1h','universe':['BTCUSDT','ETHUSDT','SOLUSDT'],'news_mode':'filtered'}
def load():
 try:return json.loads(STATE_FILE.read_text())
 except:return {'cash':50.0,'positions':{},'trades':[],'settings':DEFAULT,'journal':[]}
state=load(); state.setdefault('settings',{}); state['settings']={**DEFAULT,**state['settings']}; state.setdefault('positions',{}); state.setdefault('trades',[]); state.setdefault('cash',50.0)
def save():STATE_FILE.write_text(json.dumps(state,indent=2))
class Settings(BaseModel):
 starting_cash:float=50;target_cash:float=60;position_size:float=10;max_loss:float=3;auto_paper:bool=False;interval:str='1h';universe:list[str]=Field(default_factory=lambda:['BTCUSDT','ETHUSDT','SOLUSDT']);news_mode:str='filtered'
class Trade(BaseModel):symbol:str;side:str;amount:float=10;reason:str='Manual crypto paper trade'
class CryptoBacktest(BaseModel):symbol:str='BTCUSDT';hours:int=720;initial_cash:float=50
async def binance(symbol,interval='1h',limit=200):
 url=f'https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}'
 async with httpx.AsyncClient(timeout=10,headers={'User-Agent':'PaperTradeLab/1.0'}) as c:r=await c.get(url);r.raise_for_status();data=r.json()
 return [{'time':datetime.fromtimestamp(x[0]/1000,timezone.utc).isoformat(),'date':datetime.fromtimestamp(x[0]/1000,timezone.utc).strftime('%Y-%m-%d %H:%M'),'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4]),'volume':float(x[5])} for x in data]
def sma(a,n):return sum(a[-n:])/n if len(a)>=n else None
def rsi(a,n=14):
 if len(a)<=n:return None
 g=[max(b-a,0) for a,b in zip(a[-n-1:-1],a[-n:])];l=[max(a-b,0) for a,b in zip(a[-n-1:-1],a[-n:])];ag=sum(g)/n;al=sum(l)/n
 return 100 if al==0 else 100-100/(1+ag/al)
def signal(rows):
 a=[x['close'] for x in rows];fast=sma(a,20);slow=sma(a,50);pf=sma(a[:-1],20);ps=sma(a[:-1],50);moment=rsi(a);price=a[-1]
 if not slow:return {'action':'WAIT','price':price,'reason':'Waiting for enough hourly candles.'}
 if fast>slow and pf<=ps and (moment is None or moment<70):return {'action':'BUY','price':price,'reason':'20-hour average crossed above 50-hour average; RSI is below 70.'}
 if fast<slow and pf>=ps:return {'action':'SELL','price':price,'reason':'20-hour average crossed below 50-hour average.'}
 return {'action':'HOLD','price':price,'reason':f"Trend is {'up' if fast>slow else 'down'}; waiting for a confirmed crossover."}
async def crypto_news(symbol):
 url='https://www.coindesk.com/arc/outboundfeeds/rss/'
 try:
  async with httpx.AsyncClient(timeout=10,headers={'User-Agent':'PaperTradeLab/1.0'}) as c:r=await c.get(url)
  root=ET.fromstring(r.text);key=symbol[:3].lower();items=[]
  for x in root.findall('./channel/item'):
   title=x.findtext('title','')
   if key in title.lower() or symbol=='BTCUSDT':items.append({'title':title,'url':x.findtext('link',''),'published':x.findtext('pubDate','')})
  return items[:8]
 except:return []
@app.get('/',response_class=HTMLResponse)
async def index():return FileResponse('static/index.html')
@app.get('/api/settings')
async def get_settings():return {'settings':state['settings'],'paper_only':True}
@app.post('/api/settings')
async def set_settings(x:Settings):
 state['settings']=x.model_dump();state['cash']=x.starting_cash;save();return {'status':'saved','settings':state['settings']}
@app.post('/api/reset')
async def reset():
 state.clear();state.update({'cash':DEFAULT['starting_cash'],'positions':{},'trades':[],'settings':DEFAULT.copy(),'journal':[]});save();return {'status':'reset'}
@app.get('/api/crypto/market')
async def market():
 async def one(s):
  try:
   r=await binance(s,state['settings'].get('interval','1h'),2);return {'symbol':s,'quote':r[-1],'change_pct':(r[-1]['close']/r[-2]['close']-1)*100}
  except Exception as e:return {'symbol':s,'error':str(e)}
 return {'market':await asyncio.gather(*(one(s) for s in state['settings'].get('universe',DEFAULT['universe']))),'as_of':datetime.now(timezone.utc).isoformat(),'source':'Binance public market data'}
@app.get('/api/crypto/candles/{symbol}')
async def candles(symbol:str):return {'symbol':symbol.upper(),'candles':(await binance(symbol,state['settings'].get('interval','1h'),120)),'as_of':datetime.now(timezone.utc).isoformat(),'source':'Binance public market data'}
@app.get('/api/crypto/signal/{symbol}')
async def crypto_signal(symbol:str):
 rows=await binance(symbol,state['settings'].get('interval','1h'),200);s=signal(rows);n=await crypto_news(symbol);risk=any(any(w in x['title'].lower() for w in ['hack','exploit','fraud','bankrupt','collapse']) for x in n)
 if risk and s['action']=='BUY':s={**s,'action':'WAIT','reason':'Filtered: adverse crypto headline detected; waiting for clarity.'}
 return {'symbol':symbol.upper(),'signal':s,'news_filter':'BLOCKED' if risk else 'CLEAR','news':n}
@app.post('/api/crypto/backtest')
async def crypto_backtest(x:CryptoBacktest):
 rows=await binance(x.symbol,state['settings'].get('interval','1h'),min(x.hours,1000));rows=rows[-x.hours:];cash=x.initial_cash;units=0;trades=[];curve=[]
 for i in range(55,len(rows)):
  s=signal(rows[:i+1]);price=rows[i]['close']
  if units==0 and s['action']=='BUY': units=cash/price;cash=0;trades.append({'time':rows[i]['time'],'side':'BUY','price':price})
  elif units and (s['action']=='SELL' or units*price<=state['settings'].get('max_loss',3)): cash=units*price;units=0;trades.append({'time':rows[i]['time'],'side':'SELL','price':price,'reason':'Crossover or £3 position-loss stop'})
  curve.append(cash+units*price)
 final=cash+units*rows[-1]['close'];peak=x.initial_cash;dd=0
 for v in curve:peak=max(peak,v);dd=min(dd,(v-peak)/peak)
 return {'symbol':x.symbol.upper(),'initial':x.initial_cash,'final':round(final,2),'return_pct':round((final/x.initial_cash-1)*100,2),'max_drawdown_pct':round(dd*100,2),'trades':trades,'method':'20/50-hour SMA crossover with RSI confirmation and position-loss stop; illustrative only.'}
@app.get('/api/portfolio')
async def portfolio():
 total=state['cash'];out=[]
 for sym,p in state['positions'].items():
  try:q=(await binance(sym,state['settings'].get('interval','1h'),2))[-1]['close']
  except:q=p['entry_price']
  val=p['units']*q;total+=val;out.append({**p,'symbol':sym,'last_price':q,'value':val,'pnl':(q-p['entry_price'])*p['units']})
 return {'cash':state['cash'],'total':total,'target':state['settings'].get('target_cash',60),'positions':out,'trades':state['trades'][-50:],'auto_paper':state['settings'].get('auto_paper',False),'paper_only':True}
@app.post('/api/paper-trade')
async def paper_trade(t:Trade):
 sym=t.symbol.upper();rows=await binance(sym,state['settings'].get('interval','1h'),2);price=rows[-1]['close'];p=state['positions'].get(sym)
 if t.side=='BUY':
  spend=min(t.amount,state['cash']);
  if spend<=0:return {'status':'error','message':'Not enough paper cash.'}
  units=spend/price
  if p:
   old=p['units'];p['units']+=units;p['entry_price']=(p['entry_price']*old+price*units)/p['units']
  else:state['positions'][sym]={'units':units,'entry_price':price,'max_loss':state['settings'].get('max_loss',3)}
  state['cash']-=spend
 elif t.side=='SELL':
  if not p:return {'status':'error','message':'No open paper position.'}
  units=min(p['units'],t.amount/price);state['cash']+=units*price;p['units']-=units
  if p['units']<1e-10:del state['positions'][sym]
 else:return {'status':'error','message':'Side must be BUY or SELL.'}
 tr={'id':str(uuid.uuid4()),'time':datetime.now(timezone.utc).isoformat(),'symbol':sym,'side':t.side,'price':price,'amount':t.amount,'reason':t.reason,'paper':True};state['trades'].append(tr);save();return {'status':'executed','trade':tr}
@app.post('/api/auto/toggle')
async def toggle():state['settings']['auto_paper']=not state['settings'].get('auto_paper',False);save();return {'auto_paper':state['settings']['auto_paper'],'paper_only':True}
async def auto_loop():
 while True:
  await asyncio.sleep(60)
  if not state['settings'].get('auto_paper',False):continue
  for sym in state['settings'].get('universe',DEFAULT['universe']):
   try:
    rows=await binance(sym,state['settings'].get('interval','1h'),200);s=signal(rows);n=await crypto_news(sym);blocked=any(any(w in x['title'].lower() for w in ['hack','exploit','fraud','bankrupt','collapse']) for x in n);p=state['positions'].get(sym);price=rows[-1]['close']
    if blocked and s['action']=='BUY':s={'action':'WAIT'}
    if p and (price-p['entry_price'])*p['units']<=-state['settings'].get('max_loss',3):await paper_trade(Trade(symbol=sym,side='SELL',amount=p['units']*price,reason='Automatic £3 maximum-loss stop'))
    elif s['action']=='BUY' and not p:await paper_trade(Trade(symbol=sym,side='BUY',amount=state['settings'].get('position_size',10),reason='Automatic 20/50-hour crossover buy'))
    elif s['action']=='SELL' and p:await paper_trade(Trade(symbol=sym,side='SELL',amount=p['units']*price,reason='Automatic 20/50-hour crossover sell'))
   except Exception:continue
@app.on_event('startup')
async def startup():asyncio.create_task(auto_loop())
if __name__=='__main__':
 import uvicorn;uvicorn.run(app,host='127.0.0.1',port=8000)
