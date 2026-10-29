import asyncio, json, random, secrets, time, os, math
from pathlib import Path
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app=FastAPI(title='Fracture Isles')
ROOT=Path(__file__).parent
app.mount('/static',StaticFiles(directory=ROOT/'public'),name='static')
@app.get('/')
def index(): return FileResponse(ROOT/'public'/'index.html')
@app.get('/health')
def health():return {'ok':True,'rooms':len(rooms)}
ISLANDS=['Verdantia','Pyrrhos','Aetheria','Solara','Tiderest','Frostholm']
BUILDINGS={'farm':{'food':0,'energy':2},'tower':{'food':2,'energy':0},'market':{'food':2,'energy':1},'monument':{'food':3,'energy':3}}
OUTPUT={'farm':('food',3,4),'tower':('energy',3,4),'market':('influence',2,3),'monument':('prosperity',3,5)}
LAWS={'harvest':'Abundant Harvest','ration':'Energy Rationing','trade':'Trade Incentive','restore':'Core Restoration','levy':'Wealth Levy','powers':'Emergency Powers'}
# Longer server-authoritative timers for two-browser testing. Set FI_TIMER_MODE=quick for original pacing.
TIMER_MODES={'testing':{'build':240,'diplomacy':300,'council':180,'pledge':180},'quick':{'build':20,'diplomacy':35,'council':15,'pledge':15}}
TIMER_MODE=os.getenv('FI_TIMER_MODE','testing').lower()
TIMERS=TIMER_MODES.get(TIMER_MODE,TIMER_MODES['testing'])
rooms={}; sockets=defaultdict(set)
def now():return time.time()
def clamp(n,lo,hi):return max(lo,min(hi,n))
def add(p,k,v):p[k]=clamp(p[k]+v,0,999 if k=='prosperity' else 10 if k=='wellbeing' else 99)
def pay(p,cost):
 if any(p.get(k,0)<v for k,v in cost.items()):return False
 for k,v in cost.items():add(p,k,-v)
 return True
def event(r,s):r['log'].append(s);r['log']=r['log'][-40:]
def player(r,token):return next((p for p in r['players'] if p['token']==token),None)
def public(r,token):
 me=player(r,token)
 return {'type':'state','code':r['code'],'host':r['host'],'phase':r['phase'],'round':r['round'],'deadline':r['deadline'],'core':r['core'],'revision':r['revision'],'players':[{k:v for k,v in p.items() if k not in ('token','pledge','vote','reserved')}|{'you':p is me,'pledged':p.get('pledge') is not None,'voted':p.get('vote') is not None} for p in r['players']],'laws':r['laws'],'proposal':r['proposal'],'trades':r['trades'],'alliances':r['alliances'],'log':r['log'][-16:],'winner':r['winner'],'crisis_target':r.get('crisis_target'),'my_vote':me.get('vote') if me else None,'my_pledge':me.get('pledge') if me else None}
async def broadcast(r):
 r['revision']+=1
 for ws,token in list(sockets[r['code']]):
  try:await ws.send_json(public(r,token))
  except Exception:sockets[r['code']].discard((ws,token))
def make_room(code):return {'code':code,'host':None,'phase':'lobby','round':0,'deadline':0,'core':70,'players':[],'laws':[],'proposal':None,'candidates':{},'trades':[],'alliances':[],'log':[],'revision':0,'winner':None,'crisis_target':None,'processed':set(),'lock':asyncio.Lock(),'sequence':0}
def new_player(name,token,seat):return {'name':name[:18],'token':token,'seat':seat,'island':None,'food':6,'energy':6,'influence':3,'prosperity':0,'wellbeing':10,'plots':[None]*6,'ready':False,'used':False,'vote':None,'pledge':None,'reserved':0,'trades_done':0,'offers_made':0,'alliance_created':-1,'alliance_broken':-1,'contrib':0,'shield':0,'connected':True}
def alliance(r,p):return next((a for a in r['alliances'] if a['active'] and p['seat'] in a['seats']),None)
def active(r,key):return any(l['id']==key for l in r['laws'])
def cost_build(p,b):
 c=BUILDINGS[b].copy()
 if p['island']=='Verdantia' and b=='tower':c['energy']+=1
 if p['island']=='Pyrrhos' and b=='farm':c['food']+=1
 if p['island']=='Tiderest' and b=='market':c['food']+=1
 return c
def damage(p,n):
 n=max(0,n-(1 if p['island']=='Frostholm' else 0)); absorb=min(p['shield'],n);p['shield']-=absorb;add(p,'wellbeing',-(n-absorb))
def core_change(r,n):r['core']=clamp(r['core']+n,0,100)
def finish_collapse(r):
 if r['core']<=0:r['phase']='collapsed';r['deadline']=0;r['winner']=None;event(r,'The Core shattered. Every island has fallen!')
def score(p):return p['prosperity']+2*sum(bool(b) for b in p['plots'])+p['wellbeing']+min(8,p['contrib']//3)
def finish(r):
 order=sorted(r['players'],key=lambda p:(-score(p),-p['wellbeing'],-(p['food']+p['energy']+p['influence']),p['seat']))
 r['winner']=order[0]['seat'];r['phase']='finished';r['deadline']=0;event(r,f"{order[0]['name']} wins with {score(order[0])} points!")
def reset_ready(r):
 for p in r['players']:p['ready']=False

def phase(r,new):
 r['phase']=new;r['deadline']=now()+TIMERS.get(new,0);reset_ready(r)
 if new=='build':
  r['round']+=1;r['proposal']=None;r['candidates']={};r['trades']=[]
  for p in r['players']:p['vote']=None;p['pledge']=None;p['reserved']=0;p['trades_done']=0;p['offers_made']=0
 event(r,f"Round {r['round']} · {new.title()} phase" if new=='build' else f'{new.title()} phase started')
def start(r):
 if len(r['players'])<2 or any(p['island'] is None for p in r['players']):raise ValueError('Need at least 2 players, each with an island')
 phase(r,'build')
def council_resolve(r):
 prop=r['proposal']
 if not prop:return
 yes=sum(p['vote']=='yes' for p in r['players']);passed=yes>len(r['players'])//2
 prop['passed']=passed;event(r,f"{LAWS[prop['id']]} {'passed' if passed else 'failed'} ({yes}/{len(r['players'])} yes)")
 if not passed:return
 law=prop['id'];owner=r['players'][prop['seat']]
 if law=='restore':
  if all(p['energy']>=2 for p in r['players']):
   for p in r['players']:pay(p,{'energy':2})
   core_change(r,8)
  else:event(r,'Core Restoration failed: insufficient energy')
 elif law=='levy':
  target=sorted(r['players'],key=lambda p:(-p['prosperity'],p['seat']))[0]
  add(target,'prosperity',-4)
  for p in r['players']:
   if p is not target:add(p,'prosperity',1)
 elif law=='powers':add(owner,'influence',3);add(owner,'prosperity',-3)
 else:
  if len(r['laws'])>=2:r['laws'].pop(0)
  r['laws'].append({'id':law,'remaining':2,'activated':r['round']})
  if law=='harvest':core_change(r,-3)
 finish_collapse(r)
def select_proposal(r):
 candidates=sorted(r['candidates'].items(),key=lambda x:(int(x[0])-r['round'])%len(r['players']))
 r['proposal']=None
 for seat,law in candidates:
  p=r['players'][int(seat)]
  if p['influence']<2:continue
  if law=='restore' and any(q['energy']<2 for q in r['players']):continue
  if law in ('harvest','ration','trade') and active(r,law):continue
  pay(p,{'influence':2});r['proposal']={'id':law,'seat':p['seat'],'passed':None};event(r,f"{p['name']} proposed {LAWS[law]}");break

def resolve_crisis(r):
 total=sum(p['pledge'] or 0 for p in r['players']);target=r['crisis_target']
 if total>=target:
  core_change(r,5)
  for p in r['players']:p['contrib']+=p['pledge'] or 0
  event(r,f'Crisis prevented! {total}/{target} energy contributed. Core +5')
 else:
  core_change(r,-12)
  for p in r['players']:damage(p,2)
  event(r,f'Crisis failed! {total}/{target} contributed. Core -12; well-being damaged')
 for p in r['players']:p['reserved']=0;p['shield']=0
 r['crisis_target']=None

def reckon(r):
 # deterministic order; production snapshot is based on post-decay Core
 core_change(r,-3);finish_collapse(r)
 if r['phase']=='collapsed':return
 critical=r['core']<=30
 for p in r['players']:
  totals=defaultdict(int)
  for b in p['plots']:
   if not b:continue
   kind=b['type'];res,v1,v2=OUTPUT[kind];out=v1 if b['level']==1 else v2
   if kind=='farm':out+=(p['island']=='Verdantia')-(p['island'] in ('Solara','Frostholm'))+active(r,'harvest')
   if kind=='tower':out+=(p['island']=='Pyrrhos')-(p['island']=='Aetheria')+active(r,'ration')
   if kind=='market':out+=(p['island']=='Aetheria')
   if critical and kind!='monument':out-=1
   totals[res]+=max(0,out)
  for k,v in totals.items():add(p,k,v)
  if p['food']>=2:pay(p,{'food':2})
  else:p['food']=0;add(p,'wellbeing',-2);add(p,'prosperity',-2)
  if active(r,'ration'):add(p,'food',-1)
 for a in r['alliances']:
  if a['active'] and a['created']<r['round']:
   for seat in a['seats']:add(r['players'][seat],'prosperity',1)
 if r['round'] in (3,6):resolve_crisis(r)
 finish_collapse(r)
 if r['phase']=='collapsed':return
 for l in r['laws']:
  if l['id']=='trade':
   if r['round']>l['activated']:l['remaining']-=1
  else:l['remaining']-=1
 r['laws']=[l for l in r['laws'] if l['remaining']>0]
 event(r,f"Round {r['round']} resolved · Core {r['core']}/100")
 if r['round']==8:finish(r)
 else:phase(r,'build')

def advance(r):
 if r['phase']=='build':phase(r,'diplomacy')
 elif r['phase']=='diplomacy':
  select_proposal(r)
  if r['proposal']:phase(r,'council')
  elif r['round'] in (3,6):start_pledge(r)
  else:phase(r,'reckoning');reckon(r)
 elif r['phase']=='council':
  council_resolve(r)
  if r['phase']=='collapsed':return
  if r['round'] in (3,6):start_pledge(r)
  else:phase(r,'reckoning');reckon(r)
 elif r['phase']=='pledge':phase(r,'reckoning');reckon(r)
def start_pledge(r):
 target=(2 if r['round']==3 else 3)*len(r['players'])
 if r['core']<=50:target+=len(r['players'])
 r['crisis_target']=target;phase(r,'pledge')

def act(r,p,msg):
 t=msg.get('action');seat=p['seat'];phase_name=r['phase']
 if t=='choose':
  if phase_name!='lobby':raise ValueError('Game already started')
  island=msg.get('island')
  if island not in ISLANDS or any(q is not p and q['island']==island for q in r['players']):raise ValueError('Island unavailable')
  p['island']=island;event(r,f"{p['name']} selected {island}")
 elif t=='start':
  if phase_name!='lobby' or r['host']!=seat:raise ValueError('Only host can start')
  start(r)
 elif t=='build':
  if phase_name!='build' or p['ready']:raise ValueError('Not your Build turn')
  i=msg.get('plot');kind=msg.get('building')
  if type(i)!=int or not 0<=i<6:raise ValueError('Invalid plot')
  if p['plots'][i]:
   if p['plots'][i]['level']>=2:raise ValueError('Already upgraded')
   if not pay(p,{'food':2,'energy':2}):raise ValueError('Not enough resources')
   p['plots'][i]['level']=2;event(r,f"{p['name']} upgraded a {p['plots'][i]['type']}")
  else:
   if kind not in BUILDINGS:raise ValueError('Invalid building')
   if not pay(p,cost_build(p,kind)):raise ValueError('Not enough resources')
   p['plots'][i]={'type':kind,'level':1};event(r,f'{p["name"]} built a {kind}')
  p['ready']=True
 elif t=='ability':
  if phase_name!='build' or p['ready'] or p['used']:raise ValueError('Ability unavailable')
  island=p['island']
  if island=='Verdantia':
   if not pay(p,{'influence':1}):raise ValueError('Need influence')
   add(p,'food',3)
  elif island=='Pyrrhos':add(p,'energy',4);core_change(r,-3)
  elif island=='Aetheria':
   if not pay(p,{'energy':2}):raise ValueError('Need energy')
   add(p,'influence',3)
  elif island=='Solara':
   target=msg.get('target')
   if type(target)!=int or target==seat or not 0<=target<len(r['players']):raise ValueError('Select a rival')
   if not pay(p,{'energy':2}):raise ValueError('Need energy')
   add(r['players'][target],'energy',2);add(p,'prosperity',4)
  elif island=='Tiderest':
   if not pay(p,{'food':2}):raise ValueError('Need food')
   p['shield']=2
  elif island=='Frostholm':
   if not pay(p,{'prosperity':2}):raise ValueError('Need prosperity')
   add(p,'food',3)
  p['used']=True;p['ready']=True;event(r,f'{p["name"]} activated their island ability');finish_collapse(r)
 elif t=='ready':
  if phase_name not in ('build','diplomacy'):raise ValueError('Cannot ready now')
  p['ready']=True
 elif t=='offer':
  if phase_name!='diplomacy' or p['ready'] or p['offers_made']>=3:raise ValueError('Offer unavailable')
  target=msg.get('target');give=msg.get('give');want=msg.get('want');ga=msg.get('giveAmount');wa=msg.get('wantAmount')
  if type(target)!=int or target==seat or not 0<=target<len(r['players']):raise ValueError('Invalid target')
  if give not in ('food','energy','influence') or want not in ('food','energy','influence') or type(ga)!=int or type(wa)!=int or not 1<=ga<=30 or not 1<=wa<=30:raise ValueError('Invalid trade')
  if give==want and ga==wa:raise ValueError('No-op trade')
  if p['trades_done']>=2 or r['players'][target]['trades_done']>=2:raise ValueError('Trade limit reached')
  if p[give]<ga:raise ValueError('Insufficient resources')
  if any(o['status']=='open' and set((o['from'],o['to']))==set((seat,target)) for o in r['trades']):raise ValueError('Offer already pending')
  r['sequence']+=1;r['trades'].append({'id':r['sequence'],'from':seat,'to':target,'give':give,'want':want,'giveAmount':ga,'wantAmount':wa,'status':'open'});p['offers_made']+=1
  event(r,f'{p["name"]} offered a trade to {r["players"][target]["name"]}')
 elif t=='trade_reply':
  if phase_name!='diplomacy' or p['ready']:raise ValueError('Diplomacy closed')
  o=next((x for x in r['trades'] if x['id']==msg.get('id') and x['to']==seat and x['status']=='open'),None)
  if not o:raise ValueError('Offer unavailable')
  if not msg.get('accept'):o['status']='declined';return
  a=r['players'][o['from']];b=p
  if a['trades_done']>=2 or b['trades_done']>=2 or a[o['give']]<o['giveAmount'] or b[o['want']]<o['wantAmount']:raise ValueError('Trade no longer affordable')
  add(a,o['give'],-o['giveAmount']);add(b,o['give'],o['giveAmount']);add(b,o['want'],-o['wantAmount']);add(a,o['want'],o['wantAmount']);a['trades_done']+=1;b['trades_done']+=1;o['status']='accepted'
  for q in (a,b):
   if q['island']=='Solara':add(q,'prosperity',1)
   if active(r,'trade') and q.get('trade_bonus_round')!=r['round']:q['trade_bonus_round']=r['round'];q['trade_bonus_count']=0
   if active(r,'trade') and q.get('trade_bonus_count',0)<4:add(q,'prosperity',2);q['trade_bonus_count']+=2
  if active(r,'trade'):core_change(r,-2);finish_collapse(r)
  event(r,f'{a["name"]} and {b["name"]} completed a trade')
 elif t=='ally_offer':
  if phase_name!='diplomacy' or p['ready'] or alliance(r,p) or p['alliance_broken']==r['round'] or p['alliance_created']==r['round']:raise ValueError('Alliance unavailable')
  target=msg.get('target')
  if type(target)!=int or target==seat or not 0<=target<len(r['players']):raise ValueError('Invalid target')
  q=r['players'][target]
  if alliance(r,q) or q['alliance_broken']==r['round'] or q['alliance_created']==r['round']:raise ValueError('Target unavailable')
  if any(a['status']=='pending' and set(a['seats'])==set((seat,target)) for a in r['alliances']):raise ValueError('Already pending')
  r['sequence']+=1;r['alliances'].append({'id':r['sequence'],'seats':[seat,target],'status':'pending','active':False,'created':r['round']});event(r,f'{p["name"]} proposed an alliance')
 elif t=='ally_reply':
  if phase_name!='diplomacy' or p['ready']:raise ValueError('Diplomacy closed')
  a=next((x for x in r['alliances'] if x['id']==msg.get('id') and x['status']=='pending' and x['seats'][1]==seat),None)
  if not a:raise ValueError('Alliance unavailable')
  a['status']='declined'
  if msg.get('accept'):
   x,y=(r['players'][i] for i in a['seats'])
   if alliance(r,x) or alliance(r,y) or x['alliance_broken']==r['round'] or y['alliance_broken']==r['round']:raise ValueError('Alliance unavailable')
   a['status']='active';a['active']=True;x['alliance_created']=r['round'];y['alliance_created']=r['round'];event(r,f'{x["name"]} and {y["name"]} formed an alliance')
 elif t=='break_ally':
  if phase_name!='diplomacy' or p['ready']:raise ValueError('Diplomacy closed')
  a=alliance(r,p)
  if not a or not pay(p,{'influence':2,'prosperity':2}):raise ValueError('Cannot break alliance')
  a['active']=False;a['status']='broken';p['alliance_broken']=r['round'];event(r,f'{p["name"]} broke an alliance')
 elif t=='propose':
  if phase_name!='diplomacy' or p['ready']:raise ValueError('Diplomacy closed')
  law=msg.get('law')
  if law not in LAWS:raise ValueError('Unknown law')
  r['candidates'][str(seat)]=law
 elif t=='vote':
  if phase_name!='council' or p['vote'] is not None:raise ValueError('Vote already submitted')
  if msg.get('value') not in ('yes','no','abstain'):raise ValueError('Invalid vote')
  p['vote']=msg['value']
 elif t=='pledge':
  if phase_name!='pledge' or p['pledge'] is not None:raise ValueError('Pledge already submitted')
  amount=msg.get('amount')
  if type(amount)!=int or amount<0 or amount>99:raise ValueError('Invalid pledge')
  cost=max(1,amount-1) if p['island']=='Tiderest' and amount>0 else amount
  if not pay(p,{'energy':cost}):raise ValueError('Not enough energy')
  p['pledge']=amount;p['reserved']=cost
 elif t=='rematch':
  if phase_name not in ('finished','collapsed') or seat!=r['host']:raise ValueError('Host only')
  for q in r['players']:
   old=q['island'];connected=q['connected'];name=q['name'];token=q['token'];n=q['seat'];q.clear();q.update(new_player(name,token,n));q['island']=old;q['connected']=connected
  r['core']=70;r['round']=0;r['laws']=[];r['alliances']=[];r['trades']=[];r['log']=[];r['winner']=None;r['processed']=set();start(r)
 else:raise ValueError('Unknown action')

async def ticker():
 while True:
  await asyncio.sleep(.5)
  for r in list(rooms.values()):
   if r['phase'] in TIMERS and r['deadline']<=now():
    async with r['lock']:
     if r['phase'] in TIMERS and r['deadline']<=now():advance(r);await broadcast(r)
@app.on_event('startup')
async def startup():app.state.ticker=asyncio.create_task(ticker())
@app.on_event('shutdown')
async def shutdown():app.state.ticker.cancel()
@app.websocket('/ws')
async def ws_endpoint(ws:WebSocket):
 await ws.accept();r=None;p=None;token=None
 try:
  while True:
   msg=await ws.receive_json();action=msg.get('action')
   if action in ('create','join') and r is None:
    if action=='create':
     code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
     while code in rooms:code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
     r=make_room(code);rooms[code]=r
    else:
     code=str(msg.get('code','')).upper().strip();r=rooms.get(code)
     if not r:raise ValueError('Room not found')
    async with r['lock']:
     token=msg.get('token')
     p=player(r,token) if isinstance(token,str) else None
     if not p:
      if r['phase']!='lobby':raise ValueError('Match started. Rejoin with your original browser session.')
      if len(r['players'])>=6:raise ValueError('Room full')
      token=secrets.token_urlsafe(32);p=new_player(str(msg.get('name','Player')).strip() or 'Player',token,len(r['players']));r['players'].append(p)
      if r['host'] is None:r['host']=p['seat']
      event(r,f"{p['name']} joined the archipelago")
     p['connected']=True;sockets[r['code']].add((ws,token));await ws.send_json({'type':'identity','token':token,'code':r['code']});await broadcast(r)
   elif r and p:
    async with r['lock']:
     try:
      aid=msg.get('idempotency')
      if not isinstance(aid,str) or len(aid)>100 or len(aid)<8:raise ValueError('Missing valid action ID')
      if (token,aid) in r['processed']:await ws.send_json({'type':'ack','id':aid,'duplicate':True});continue
      act(r,p,msg);r['processed'].add((token,aid))
      if r['phase']=='build' and all(q['ready'] for q in r['players']):advance(r)
      elif r['phase']=='diplomacy' and all(q['ready'] for q in r['players']):advance(r)
      elif r['phase']=='council' and all(q['vote'] is not None for q in r['players']):advance(r)
      elif r['phase']=='pledge' and all(q['pledge'] is not None for q in r['players']):advance(r)
      await ws.send_json({'type':'ack','id':aid});await broadcast(r)
     except ValueError as e:await ws.send_json({'type':'error','message':str(e)})
   else:await ws.send_json({'type':'error','message':'Create or join a room first'})
 except WebSocketDisconnect:pass
 except Exception as e:
  try:await ws.send_json({'type':'error','message':str(e)})
  except Exception:pass
 finally:
  if r and p:
   sockets[r['code']].discard((ws,token))
   if not any(tok==token for _,tok in sockets[r['code']]):p['connected']=False
   if r['host']==p['seat']:
    connected=[q for q in r['players'] if q['connected']]
    if connected:r['host']=min(q['seat'] for q in connected)
   await broadcast(r)
