import asyncio, secrets, time
from pathlib import Path
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app=FastAPI(title='Fracture Isles')
ROOT=Path(__file__).parent
app.mount('/static',StaticFiles(directory=ROOT/'public'),name='static')
rooms={}
sockets=defaultdict(set)
ISLANDS=['Verdantia','Pyrrhos','Aetheria','Solara','Tiderest','Frostholm']
BUILDINGS={
 'farm':{'cost':{'energy':1},'points':1},
 'tower':{'cost':{'food':1},'points':1},
 'monument':{'cost':{'food':2,'energy':2},'points':3},
}
TOTAL_ROUNDS=8
TURN_SECONDS=45
LAWS={'balanced':'Balanced','harvest':'Harvest Charter','power':'Power Charter'}

def now(): return time.time()
def clamp(n,low,high): return max(low,min(high,n))
def add(p,key,amount): p[key]=clamp(p.get(key,0)+amount,0,999)
def pay(p,cost):
 if any(p.get(key,0)<amount for key,amount in cost.items()): return False
 for key,amount in cost.items(): add(p,key,-amount)
 return True
def event(r,message): r['log']=(r['log']+[message])[-40:]
def player(r,token): return next((p for p in r['players'] if p['token']==token),None)
def score(p): return p['prosperity']
def public(r,token):
 me=player(r,token)
 return {'type':'state','code':r['code'],'host':r['host'],'phase':r['phase'],'round':r['round'],'deadline':r['deadline'],'core':r['core'],'law':r.get('law','balanced'),'next_law':r.get('next_law'),'law_set_by':r.get('law_set_by'),'turn_seat':r.get('turn_seat'),'trade':({**r['trade'],'from_name':next((p['name'] for p in r['players'] if p['seat']==r['trade']['from']),''),'to_name':next((p['name'] for p in r['players'] if p['seat']==r['trade']['to']),'' )} if r.get('trade') else None),'revision':r['revision'],'players':[{k:v for k,v in p.items() if k!='token'}|{'you':p is me} for p in r['players']],'laws':[],'proposal':None,'trades':[],'alliances':[],'log':r['log'][-16:],'winner':r['winner'],'crisis_target':None}
async def broadcast(r):
 r['revision']+=1
 for ws,token in list(sockets[r['code']]):
  try: await ws.send_json(public(r,token))
  except Exception: sockets[r['code']].discard((ws,token))
def make_room(code):
 return {'code':code,'host':None,'phase':'lobby','round':0,'deadline':0,'core':60,'players':[],'log':[],'revision':0,'winner':None,'law':'balanced','next_law':None,'law_set_by':None,'turn_seat':None,'trade':None,'processed':set(),'lock':asyncio.Lock()}
def new_player(name,token,seat):
 return {'name':name[:18],'token':token,'seat':seat,'island':None,'food':2,'energy':2,'prosperity':0,'plots':[None]*6,'ready':False,'connected':True}
def begin_round(r,round_number):
 r['phase']='build';r['round']=round_number
 for p in r['players']: p['ready']=False
 r['turn_seat']=r['host'] if any(p['seat']==r['host'] for p in r['players']) else min((p['seat'] for p in r['players']),default=None);r['deadline']=now()+TURN_SECONDS if r['turn_seat'] is not None else 0
 if r['turn_seat'] is not None: event(r,f"Round {round_number} started. {next(p['name'] for p in r['players'] if p['seat']==r['turn_seat'])} chooses first.")
def finish(r):
 order=sorted(r['players'],key=lambda p:(-score(p),p['seat']))
 r['winner']=order[0]['seat'] if order else None;r['phase']='finished';r['deadline']=0;r['turn_seat']=None
 if order: event(r,f"{order[0]['name']} wins with {score(order[0])} points")
def resolve_round(r):
 if r['phase']!='build': return
 law=r.get('law','balanced')
 for p in r['players']:
  farms=sum(1 for b in p['plots'] if b and b['type']=='farm')
  towers=sum(1 for b in p['plots'] if b and b['type']=='tower')
  p['food']=clamp(p['food']+farms*(2 if law=='harvest' else 1),0,99)
  p['energy']=clamp(p['energy']+towers*(2 if law=='power' else 1),0,99)
 if r.get('trade'):
  offer=r['trade'];giver=next((p for p in r['players'] if p['seat']==offer['from']),None)
  if giver: add(giver,offer['give'],1)
  event(r,'An unanswered trade expired; the offered resource was returned.')
  r['trade']=None
 r['core']=clamp(r['core']-(10 if law!='balanced' else 8),0,60)
 event(r,f"Round {r['round']} ended under {LAWS[law]}. The Core is at {r['core']}/60.")
 if r['core']<=0:
  r['phase']='collapsed';r['deadline']=0;r['winner']=None;r['turn_seat']=None;event(r,'The Core ran out of power. Everyone loses.');return
 if r['round']>=TOTAL_ROUNDS: finish(r);return
 if r.get('next_law'):
  r['law']=r['next_law'];event(r,f"{LAWS[r['law']]} set by {r.get('law_set_by','a player')} takes effect next round.")
 r['next_law']=None;r['law_set_by']=None
 begin_round(r,r['round']+1)
def start(r):
 if len(r['players'])<2: raise ValueError('At least 2 players are needed')
 if any(p['island'] is None for p in r['players']): raise ValueError('Everyone must choose an island')
 r['core']=60;r['winner']=None;r['law']='balanced';r['next_law']=None;r['law_set_by']=None;r['trade']=None;begin_round(r,1)
def act(r,p,msg):
 action=msg.get('action');seat=p['seat']
 if action=='choose':
  if r['phase']!='lobby': raise ValueError('The game has already started')
  island=msg.get('island')
  if island not in ISLANDS or any(q is not p and q['island']==island for q in r['players']): raise ValueError('Island unavailable')
  p['island']=island;event(r,f"{p['name']} chose {island}");return
 if action=='start':
  if r['phase']!='lobby' or r['host']!=seat: raise ValueError('Only the host can start')
  start(r);return
 if action=='rematch':
  if r['phase'] not in ('finished','collapsed') or seat!=r['host']: raise ValueError('Only the host can restart')
  for q in r['players']:
   old=q['island'];connected=q['connected'];name=q['name'];token=q['token'];n=q['seat']
   q.clear();q.update(new_player(name,token,n));q['island']=old;q['connected']=connected
  r['log']=[];r['core']=60;r['winner']=None;r['law']='balanced';r['next_law']=None;r['law_set_by']=None;r['trade']=None;r['processed']=set();start(r);return
 if r['phase']!='build' or p['ready']: raise ValueError('You have already chosen this round')
 if r.get('turn_seat')!=seat: raise ValueError('Wait for your turn')
 if action=='set_law':
  law=msg.get('law')
  if law not in LAWS: raise ValueError('Choose Balanced, Harvest Charter, or Power Charter')
  r['next_law']=law;r['law_set_by']=p['name'];event(r,f"{p['name']} set {LAWS[law]} for next round")
 elif action=='trade_accept':
  offer=r.get('trade')
  if not offer or offer['to']!=seat: raise ValueError('There is no trade waiting for you')
  if not pay(p,{offer['want']:1}): raise ValueError(f"You need 1 {offer['want']} to accept")
  giver=next(q for q in r['players'] if q['seat']==offer['from']);add(p,offer['give'],1);add(giver,offer['want'],1);r['trade']=None
  event(r,f"{p['name']} accepted {giver['name']}'s trade")
 elif action=='trade_offer':
  if r.get('trade'): raise ValueError('A trade is already waiting for its recipient')
  target=next((q for q in r['players'] if q['seat']==msg.get('target')),None)
  give=msg.get('give');want=msg.get('want')
  if not target or target is p: raise ValueError('Choose another player to trade with')
  if target['ready']: raise ValueError('Trade with a player who has not chosen this round yet')
  if give not in ('food','energy') or want not in ('food','energy') or give==want: raise ValueError('Trade 1 food for 1 energy, or 1 energy for 1 food')
  if not pay(p,{give:1}): raise ValueError(f'You need 1 {give} to offer it')
  r['trade']={'from':seat,'to':target['seat'],'give':give,'want':want}
  event(r,f"{p['name']} offered {target['name']} 1 {give} for 1 {want}")
 elif action=='build':
  plot=msg.get('plot');kind=msg.get('building')
  if type(plot)!=int or not 0<=plot<len(p['plots']): raise ValueError('Choose a plot')
  if p['plots'][plot]: raise ValueError('Choose an empty plot')
  if kind not in BUILDINGS: raise ValueError('Choose a Farm, Tower, or Monument')
  rule=BUILDINGS[kind]
  if not pay(p,rule['cost']): raise ValueError('Not enough food or energy')
  p['plots'][plot]={'type':kind,'level':1};add(p,'prosperity',rule['points'])
  event(r,f"{p['name']} built a {kind}")
 elif action=='gather':
  resource=msg.get('resource')
  if resource not in ('food','energy'): raise ValueError('Gather food or energy')
  add(p,resource,2);event(r,f"{p['name']} gathered 2 {resource}")
 elif action=='repair':
  if r['core']>=60: raise ValueError('The Core is already full')
  if not pay(p,{'energy':1}): raise ValueError('Repairing costs 1 energy')
  r['core']=clamp(r['core']+12,0,60);event(r,f"{p['name']} repaired the Core (+12)")
 elif action=='pass': event(r,f"{p['name']} passed")
 elif action not in ('set_law','trade_offer','trade_accept'): raise ValueError('Unknown action')
 if r.get('trade') and r['trade']['to']==seat and action!='trade_accept':
  offer=r['trade'];giver=next(q for q in r['players'] if q['seat']==offer['from']);add(giver,offer['give'],1);r['trade']=None;event(r,f"{p['name']} chose another action; the trade was declined and {giver['name']} got {offer['give']} back")
 p['ready']=True;advance_turn(r,p['seat'])

def advance_turn(r,previous_seat):
 if r['phase']!='build': return
 remaining=sorted((p for p in r['players'] if not p['ready']),key=lambda p:p['seat'])
 if not remaining:
  r['turn_seat']=None;r['deadline']=0;resolve_round(r);return
 next_player=next((p for p in remaining if p['seat']>previous_seat),remaining[0])
 r['turn_seat']=next_player['seat'];r['deadline']=now()+TURN_SECONDS
 event(r,f"{next_player['name']}'s turn")
def advance_if_ready(r):
 if r['phase']=='build' and r['players'] and all(p['ready'] for p in r['players']): resolve_round(r)

@app.get('/')
def index(): return FileResponse(ROOT/'public'/'index.html')
@app.get('/health')
def health(): return {'ok':True,'rooms':len(rooms)}
@app.on_event('startup')
async def startup(): app.state.ticker=asyncio.create_task(ticker())
@app.on_event('shutdown')
async def shutdown(): app.state.ticker.cancel()
async def ticker():
 while True:
  await asyncio.sleep(.5)
  for r in list(rooms.values()):
   if r['phase']=='build' and r['deadline']<=now():
    async with r['lock']:
     if r['phase']=='build' and r['deadline']<=now():
      p=next((q for q in r['players'] if q['seat']==r.get('turn_seat')),None)
      if p and not p['ready']:
       if r.get('trade') and r['trade']['to']==p['seat']:
        offer=r['trade'];giver=next(q for q in r['players'] if q['seat']==offer['from']);add(giver,offer['give'],1);r['trade']=None
        event(r,f"{p['name']} timed out; the trade was declined and {giver['name']} got {offer['give']} back")
       p['ready']=True;event(r,f"{p['name']} ran out of time and passed");advance_turn(r,p['seat']);await broadcast(r)

@app.websocket('/ws')
async def ws_endpoint(ws:WebSocket):
 await ws.accept();r=None;p=None;token=None
 try:
  while True:
   msg=await ws.receive_json();action=msg.get('action')
   if action in ('create','join') and r is None:
    if action=='create':
     code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
     while code in rooms: code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
     r=make_room(code);rooms[code]=r
    else:
     code=str(msg.get('code','')).upper().strip();r=rooms.get(code)
     if not r: raise ValueError('Room not found')
    async with r['lock']:
     token=msg.get('token');p=player(r,token) if isinstance(token,str) else None
     if not p:
      if r['phase']!='lobby': raise ValueError('The game has started. Rejoin with your original browser session.')
      if len(r['players'])>=6: raise ValueError('Room full')
      token=secrets.token_urlsafe(32);p=new_player(str(msg.get('name','Player')).strip() or 'Player',token,len(r['players']));r['players'].append(p)
      if r['host'] is None:r['host']=p['seat']
      event(r,f"{p['name']} joined the room")
     p['connected']=True;sockets[r['code']].add((ws,token));await ws.send_json({'type':'identity','token':token,'code':r['code']});await broadcast(r)
   elif r and p:
    async with r['lock']:
     try:
      aid=msg.get('idempotency')
      if not isinstance(aid,str) or not 8<=len(aid)<=100: raise ValueError('Missing valid action ID')
      if (token,aid) in r['processed']:
       await ws.send_json({'type':'ack','id':aid,'duplicate':True});continue
      act(r,p,msg);r['processed'].add((token,aid));advance_if_ready(r)
      await ws.send_json({'type':'ack','id':aid});await broadcast(r)
     except ValueError as e: await ws.send_json({'type':'error','message':str(e)})
   else: await ws.send_json({'type':'error','message':'Create or join a room first'})
 except WebSocketDisconnect: pass
 except Exception as e:
  try: await ws.send_json({'type':'error','message':str(e)})
  except Exception: pass
 finally:
  if r and p:
   sockets[r['code']].discard((ws,token))
   if not any(tok==token for _,tok in sockets[r['code']]):p['connected']=False
   if r['host']==p['seat']:
    connected=[q for q in r['players'] if q['connected']]
    if connected:r['host']=min(q['seat'] for q in connected)
   await broadcast(r)
