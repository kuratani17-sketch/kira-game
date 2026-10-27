import asyncio, json, os, random, secrets, string, time
from collections import Counter
from aiohttp import web, WSMsgType

ROOT = os.path.dirname(os.path.abspath(__file__))
ROOMS = {}
ROLES = {'kira':'キラ','follower':'崇拝者','l':'L','investigator':'捜査員','watari':'ワタリ','gevanni':'ジェバンニ'}
NPC_NAMES = ('夜神','竜崎','相沢','模木','松田','魅上','伊出','音原田','渋井丸','火口','弥','ペンバー','南空','マット')
MAX_PLAYERS = 12

def uid(n=16): return secrets.token_urlsafe(n)
def broadcast(room):
    for p in room['players']:
        if p['ws'] is not None:
            asyncio.create_task(send(p['ws'], {'type':'state','data':view(room,p)}))
async def send(ws,data):
    try: await ws.send_json(data)
    except Exception: pass

def addlog(r, s):
    r['log'].append(s)
    r['log'] = r['log'][-100:]

def living(r): return [p for p in r['players'] if p['alive']]
def who(r, pid): return next((p for p in r['players'] if p['id']==pid),None)
def byrole(r, role): return next((p for p in r['players'] if p['role']==role), None)
def candidates(r): return [p for p in living(r) if not p.get('cleared',False)]

def view(r,p):
    aware = {}
    if r['stage']!='lobby':
        aware[p['id']]=p['role']
        if p['role']=='follower':
            aware.update({q['id']: 'kira' for q in r['players'] if q['role']=='kira'})
        if p['role']=='watari':
            aware.update({q['id']: 'l' for q in r['players'] if q['role']=='l'})
    def player_view(q):
        result={'id':q['id'],'name':q['name'],'npc':q['npc'],'alive':q['alive'],
                'suspicion':q['suspicion'],'cleared':q.get('cleared',False)}
        if r['stage']=='ended' or (not q['alive'] and r['options'].get('revealRolesOnDeath',True)):
            result['role']=q['role']
        elif q['id'] in aware:
            result['role']=aware[q['id']]
        return result
    return {
      'code':r['code'],'gameId':r.get('gameId'),'host':r['host']==p['id'],'self':p['id'],
      'stage':r['stage'],'day':r['day'],'round':r['round'],
      'deadline':r['deadline'],'options':r['options'],
      'players':[player_view(q) for q in r['players']],
      'myRole':p['role'],'known':[qid for qid in aware if qid!=p['id']],
      'investigations':p['investigations'],
      'log':r['log'],'publicInfo':r.get('publicInfo',[]),'dailyNominations':r.get('dailyNominations',[]),'reveal':r['reveal'],'winner':r['winner'],
      'hasActed':p['id'] in r['actions'],'lastGuard':p['lastGuard'],
      'hostOptions':r['options'], 'next':r.get('next', '')
    }

def options_from(raw):
    n = max(5,min(MAX_PLAYERS,int(raw.get('size',5))))
    f = max(0,min(n-2,int(raw.get('follower',1))))
    w = max(0,min(n-2,int(raw.get('watari',0))))
    g = max(0,min(n-2,int(raw.get('gevanni',0))))
    if f+w+g > n-3: raise ValueError('捜査員を最低1人残してください')
    return {'size':n,'follower':f,'watari':w,'gevanni':g,
            'discussion':max(15,min(900,int(raw.get('discussion',40)))),
            'night':max(10,min(300,int(raw.get('night',20)))),
            'revealRolesOnDeath':raw.get('revealRolesOnDeath',True) is not False}

def declare(r, winner, reason):
    r['winner']=winner; r['stage']='ended';r['deadline']=None
    r['reveal']={'kind':'win','team':winner,'text':('キラ陣営の勝利' if winner=='kira' else 'L陣営の勝利'),'sub':reason}
    addlog(r,r['reveal']['text']+' — '+reason)

def finish_if(r, p, method):
    if p['role']=='kira': declare(r,'l',f'キラ「{p["name"]}」が{method}された');return True
    if p['role']=='l': declare(r,'kira',f'L「{p["name"]}」が{method}された');return True
    if not any(q['alive'] and q['role'] in ('investigator','watari','gevanni') for q in r['players']):
        declare(r,'kira','L以外のL陣営が全員脱落した');return True
    return False

def begin_discussion(r):
    r['stage']='discussion';r['actions']={};r['deadline']=time.time()+r['options']['discussion'];r['reveal']=None
    addlog(r,f'{r["day"]}日目・第{r["round"]}回 議論開始')

def begin_nomination(r):
    r['stage']='nomination';r['actions']={};r['deadline']=time.time()+30;r['reveal']=None
    addlog(r,f'{r["day"]}日目・第{r["round"]}回 指名開始')
    for q in living(r):
        if q['npc']: r['actions'][q['id']]=npc_nominate(r,q)
    if len(r['actions'])==len(living(r)): resolve_nomination(r)

def npc_nominate(r,p):
    others=[q for q in candidates(r) if q!=p]
    if not others: return None
    target=None; delta=None
    if p['role']=='follower':
        kira=byrole(r,'kira')
        if kira and kira['alive'] and kira!=p and random.random()<.5:
            target=kira;delta=-1
        else:
            pool=[q for q in others if q['role']!='kira'];target=random.choice(pool or others);delta=1
    elif p['role']=='watari':
        l=byrole(r,'l')
        if l and l in others and random.random()<.5:
            target=l;delta=-1
        else:
            pool=[q for q in others if q['role']!='l'];target=random.choice(pool or others);delta=1
    elif p['role']=='l' and any(x['result'] for x in p['investigations']):
        targets=[q for q in others if any(x['target']==q['id'] and x['result'] for x in p['investigations'])]
        if targets: target=random.choice(targets);delta=1
    if target is None:
        # ジェバンニも対象自体はランダム。救った相手が選ばれた場合は必ず疑惑度を下げる。
        target=random.choice(others)
        delta=-1 if p['role']=='gevanni' and target['id'] in p['guardedSuccess'] else random.choice([-1,1])
    return {'target':target['id'],'delta':delta}

def resolve_nomination(r):
    power=r['day']
    for pid,act in list(r['actions'].items()):
        if not act:continue
        t=who(r,act['target']);actor=who(r,pid)
        if t and t['alive'] and not t.get('cleared',False) and actor and actor['alive']:
            before=t['suspicion']; t['suspicion']=before+act['delta']*power
            sign=f'+{power}' if act['delta']>0 else f'-{power}'
            r.setdefault('dailyNominations',[]).append({
                'day':r['day'],'round':r['round'],
                'actorId':actor['id'],'actor':actor['name'],
                'targetId':t['id'],'target':t['name'],
                'change':act['delta']*power
            })
            addlog(r,f'{actor["name"]} → {t["name"]}：疑惑度{sign}（{before}→{t["suspicion"]}）')
    r['reveal']={'kind':'nomination','text':f'{r["round"]}回目の指名結果','sub':'指名内容は履歴から確認できます'}
    r['stage']='result';r['next']='discussion' if r['round']<3 else 'arrest';r['deadline']=time.time()+4

def arrest(r):
    a=candidates(r)
    if not a:return
    m=max(p['suspicion'] for p in a)
    t=random.choice([p for p in a if p['suspicion']==m])
    t['alive']=False
    showrole=r['options'].get('revealRolesOnDeath',True)
    role_text=f' ／ 役職：{ROLES[t["role"]]}' if showrole else ''
    r['reveal']={'kind':'arrest','text':f'{t["name"]}を検挙！',
                 'sub':f'疑惑度 {m}{role_text}'}
    if showrole:r['reveal']['team']='kira' if t['role'] in ('kira','follower') else 'l'
    addlog(r,f'【検挙】{t["name"]}（疑惑度{m}{role_text}）')
    if finish_if(r,t,'検挙'): return
    r['stage']='result';r['next']='night';r['deadline']=time.time()+6

def begin_night(r):
    r['stage']='night';r['actions']={};r['reveal']=None;r['deadline']=time.time()+r['options']['night']
    addlog(r,f'{r["day"]}日目 夜開始')
    for p in living(r):
        if p['npc']:
            target=None
            if p['role']=='kira':
                # 50% chance to abstain, otherwise choose a random living target.
                pool=[q for q in living(r) if q!=p]
                target=random.choice(pool)['id'] if pool and random.choice((True,False)) else None
            elif p['role']=='l':
                pool=[q for q in living(r) if q!=p and all(x['target']!=q['id'] for x in p['investigations'])]
                target=random.choice(pool)['id'] if pool else None
            elif p['role']=='gevanni':
                pool=[q for q in living(r) if q['id']!=p['lastGuard']]
                target=random.choice(pool)['id'] if pool else None
            r['actions'][p['id']]={'target':target}
    maybe_night(r)

def maybe_night(r):
    if r['stage']=='night' and all(p['id'] in r['actions'] for p in living(r)):
        resolve_night(r)

def resolve_night(r):
    if r['stage']!='night':return
    kira=byrole(r,'kira');l=byrole(r,'l')
    for p in living(r):
        a=r['actions'].get(p['id'],{})
        t=who(r,a.get('target'))
        if p['role']=='l' and t and t['alive'] and t!=p:
            p['investigations'].append({'target':t['id'],'name':t['name'],'result':t['role']=='kira'})
        if p['role']=='gevanni':p['lastGuard']=t['id'] if t else None
    victim=who(r,r['actions'].get(kira['id'],{}).get('target')) if kira and kira['alive'] else None
    guarded=[p for p in living(r) if p['role']=='gevanni' and r['actions'].get(p['id'],{}).get('target')== (victim['id'] if victim else None)]
    if victim and victim['alive'] and victim!=kira and not guarded:
        victim['alive']=False
        showrole=r['options'].get('revealRolesOnDeath',True)
        role_text=f' ／ 役職：{ROLES[victim["role"]]}' if showrole else ''
        addlog(r,f'【裁き】{victim["name"]}が脱落{role_text}')
        disclosed=None
        if victim['role']!='l':
            # Lを裁けなかった場合、公開できるのは生存中のL陣営だけ。
            # 崇拝者を公開して、誤ってキラ候補から除外してしまわない。
            pool=[p for p in living(r) if p['role'] not in ('kira','follower')]
            unseen=[p for p in pool if not p.get('cleared',False)]
            disclosed=random.choice(unseen or pool) if pool else None
        info=f' ／ 公開情報：{disclosed["name"]}はキラではない' if disclosed else ''
        r['reveal']={'kind':'judgment', 'text':f'{victim["name"]}が裁かれた！',
                     'sub':f'{"役職："+ROLES[victim["role"]] if showrole else "脱落者が発表されました"}{info}'}
        if showrole:r['reveal']['team']='kira' if victim['role'] in ('kira','follower') else 'l'
        if disclosed and not disclosed.get('cleared',False):
            disclosed['cleared']=True
            disclosed['suspicion']=0
            r['publicInfo'].append({'day':r['day'],'playerId':disclosed['id'],
                                    'text':f'{disclosed["name"]}はキラではない（キラ候補から除外・疑惑度0）'})
        if finish_if(r,victim,'裁き'):return
    else:
        if guarded:
            for p in guarded:p['guardedSuccess'].add(victim['id'])
            addlog(r,'【夜の結果】裁きは阻止された')
        else:addlog(r,'【夜の結果】脱落者なし')
        r['reveal']={'kind':'judgment','text':'昨夜の脱落者なし','sub':'裁きが阻止されたか、行われませんでした'}
    r['stage']='result';r['next']='newday';r['deadline']=time.time()+7

def advance(r):
    nxt=r['next'];r['next']=''
    if nxt=='discussion':r['round']+=1;begin_discussion(r)
    elif nxt=='arrest':arrest(r)
    elif nxt=='night':begin_night(r)
    elif nxt=='newday':r['day']+=1;r['round']=1;r['dailyNominations']=[];begin_discussion(r)

def setup(r):
    opt=r['options'];n=opt['size'];humans=[p for p in r['players'] if not p['npc']]
    if len(humans)>n:raise ValueError('参加人数が設定人数を超えています')
    r['players']=humans
    used={p['name'] for p in humans}
    available_names=[name for name in NPC_NAMES if name not in used]
    needed=n-len(humans)
    if len(available_names)<needed:raise ValueError('NPCの名前が足りません')
    for name in random.sample(available_names,needed):
        r['players'].append(makeplayer(uid(),name,True,None))
    roles=['kira','l']+['follower']*opt['follower']+['watari']*opt['watari']+['gevanni']*opt['gevanni']+['investigator']*(n-2-opt['follower']-opt['watari']-opt['gevanni'])
    random.shuffle(roles)
    for p,role in zip(r['players'],roles):
        p.update(role=role,alive=True,suspicion=0,cleared=False,investigations=[],lastGuard=None,guardedSuccess=set())
    r.update(day=1,round=1,winner=None,actions={},reveal=None,publicInfo=[],dailyNominations=[],gameId=uid(8))
    addlog(r,'ゲーム開始。役職を配布しました')
    # The role configuration always ensures at least one investigator.
    r['stage']='role_reveal';r['deadline']=time.time()+12

def makeplayer(id,name,npc,ws):
    return {'id':id,'name':name,'npc':npc,'ws':ws,'alive':True,'role':None,'suspicion':0,'cleared':False,'investigations':[],'lastGuard':None,'guardedSuccess':set()}

async def socket(request):
    ws=web.WebSocketResponse(heartbeat=20,max_msg_size=10000);await ws.prepare(request)
    me=None;room=None
    async for msg in ws:
        if msg.type!=WSMsgType.TEXT:continue
        try:
            data=json.loads(msg.data);kind=data.get('type')
            if kind=='join':
                code=str(data.get('code','')).strip().upper()
                name=str(data.get('name','プレイヤー')).strip()[:20] or 'プレイヤー'
                token=str(data.get('token',''))[:80]
                if not code:
                    code=''.join(random.choices(string.ascii_uppercase+string.digits,k=6))
                    while code in ROOMS:code=''.join(random.choices(string.ascii_uppercase+string.digits,k=6))
                    ROOMS[code]={'code':code,'players':[],'host':None,'stage':'lobby','options':options_from({}),'day':0,'round':0,'deadline':None,'actions':{},'log':[],'publicInfo':[],'dailyNominations':[],'reveal':None,'winner':None,'next':''}
                room=ROOMS.get(code)
                if not room:raise ValueError('部屋が見つかりません')
                me=who(room,token) if token else None
                if me and me['npc']:me=None
                if me:
                    if me['ws'] and me['ws']!=ws:await me['ws'].close()
                    me['ws']=ws
                else:
                    if room['stage']!='lobby':raise ValueError('開始済みの部屋には新規参加できません')
                    if len([p for p in room['players'] if not p['npc']])>=room['options']['size']:raise ValueError('満員です')
                    me=makeplayer(uid(),name,False,ws);room['players'].append(me)
                    if not room['host']:room['host']=me['id']
                await send(ws,{'type':'joined','code':room['code'],'token':me['id']});broadcast(room)
            elif not room or not me:raise ValueError('先に部屋へ参加してください')
            elif kind=='config':
                if room['stage']!='lobby' or room['host']!=me['id']:raise ValueError('設定権限がありません')
                opts=options_from(data.get('options',{}))
                if opts['size']<len(room['players']):raise ValueError('現在の参加者数より少なくできません')
                room['options']=opts;broadcast(room)
            elif kind=='start':
                if room['stage']!='lobby' or room['host']!=me['id']:raise ValueError('開始権限がありません')
                setup(room);broadcast(room)
            elif kind=='end_discussion':
                if room['stage']!='discussion' or room['host']!=me['id']:
                    raise ValueError('議論の手動終了は議論中のホストだけが操作できます')
                addlog(room,f'【進行】ホストが{room["round"]}回目の議論を終了')
                begin_nomination(room);broadcast(room)
            elif kind=='nominate':
                if room['stage']!='nomination' or not me['alive'] or me['id'] in room['actions']:raise ValueError('現在は指名できません')
                target=who(room,data.get('target'));delta=data.get('delta')
                if delta not in [-1,1]:raise ValueError('指名内容が無効です')
                possible=[q for q in candidates(room) if q!=me]
                if not possible and target is None:
                    room['actions'][me['id']]=None
                    if len(room['actions'])==len(living(room)):resolve_nomination(room)
                    broadcast(room);continue
                if not target or target not in possible:raise ValueError('指名対象が無効です')
                room['actions'][me['id']]={'target':target['id'],'delta':delta}
                if len(room['actions'])==len(living(room)):resolve_nomination(room)
                broadcast(room)
            elif kind=='night':
                if room['stage']!='night' or not me['alive'] or me['id'] in room['actions']:raise ValueError('現在は夜行動できません')
                target=who(room,data.get('target'))
                if me['role'] in ('kira','l','gevanni'):
                    # Kira may explicitly pass the night action. Other active roles need a target.
                    if not (me['role']=='kira' and data.get('pass') is True):
                        if not target or not target['alive'] or (target==me and me['role']!='gevanni'):raise ValueError('対象が無効です')
                    elif me['role']=='kira':
                        target=None
                    if me['role']=='gevanni' and target['id']==me['lastGuard']:raise ValueError('連続で同じ対象は守れません')
                else:target=None
                room['actions'][me['id']]={'target':target['id'] if target else None}
                maybe_night(room);broadcast(room)
            elif kind=='return':
                # Only the host can reset the shared game. Available from every stage.
                if room['host']!=me['id']:raise ValueError('待機部屋への全員移動はホストのみ操作できます')
                room['players']=[p for p in room['players'] if not p['npc'] and p['ws'] is not None]
                room.update(stage='lobby',day=0,round=0,gameId=None,winner=None,reveal=None,deadline=None,
                            log=[],publicInfo=[],dailyNominations=[],actions={},next='')
                for p in room['players']:
                    p.update(role=None,alive=True,suspicion=0,cleared=False,investigations=[],lastGuard=None,guardedSuccess=set())
                broadcast(room)
            elif kind=='leave':
                # Leaving the room does not interrupt anyone else's game.
                if room['stage']=='lobby':room['players']=[p for p in room['players'] if p!=me]
                me['ws']=None
                if room['host']==me['id']:
                    replacements=[p for p in room['players'] if not p['npc'] and p['ws'] is not None]
                    room['host']=replacements[0]['id'] if replacements else None
                if room['stage']=='lobby' and not room['players']:ROOMS.pop(room['code'],None)
                else:broadcast(room)
                await send(ws,{'type':'left'})
                room=None;me=None
            else:raise ValueError('操作が無効です')
        except Exception as exc:await send(ws,{'type':'error','message':str(exc)})
    if me and me.get('ws')==ws:
        me['ws']=None
        if room and room['stage']=='lobby':
            room['players']=[p for p in room['players'] if p!=me]
            if room['host']==me['id']:room['host']=room['players'][0]['id'] if room['players'] else None
            if not room['players']:ROOMS.pop(room['code'],None)
            else:broadcast(room)
    return ws

async def loop(app):
    while True:
        await asyncio.sleep(.5)
        now=time.time()
        for r in list(ROOMS.values()):
            if r['deadline'] and now>=r['deadline']:
                if r['stage']=='role_reveal':begin_discussion(r)
                elif r['stage']=='discussion':begin_nomination(r)
                elif r['stage']=='nomination':
                    for p in living(r):
                        if p['id'] not in r['actions']:r['actions'][p['id']]=npc_nominate(r,p)
                    resolve_nomination(r)
                elif r['stage']=='night':resolve_night(r)
                elif r['stage']=='result':advance(r)
                broadcast(r)
async def ctx(app):
    task=asyncio.create_task(loop(app));yield;task.cancel()
async def health(request):return web.json_response({'status':'ok'})
async def index(request):return web.FileResponse(os.path.join(ROOT,'public','index.html'))
app=web.Application();app.add_routes([web.get('/health',health),web.get('/ws',socket),web.get('/',index),web.static('/static',os.path.join(ROOT,'public'))]);app.cleanup_ctx.append(ctx)
if __name__=='__main__':web.run_app(app,port=int(os.environ.get('PORT','8080')),host='0.0.0.0')
