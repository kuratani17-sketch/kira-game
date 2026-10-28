"""Run with: python tests/test_believer.py"""
import asyncio, importlib.util, json, random
from collections import Counter
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer

spec=importlib.util.spec_from_file_location('dx', Path(__file__).resolve().parents[1]/'server.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def make_room(size=5, believer=1, follower=0, watari=0, gevanni=0):
    options=m.options_from({'size':size,'believer':believer,'follower':follower,'watari':watari,'gevanni':gevanni})
    human=m.makeplayer('human','Human',False,None)
    room={'code':'TEST','players':[human],'spectators':[],'host':human['id'],'stage':'lobby',
        'options':options,'day':0,'round':0,'deadline':None,'actions':{},'log':[],
        'publicInfo':[],'dailyNominations':[],'reveal':None,'winner':None,'next':''}
    random.seed(19)
    m.setup(room)
    return room

def test_roles_and_rules():
    assert m.ROLES['believer']=='信者' and m.VERSION=='0.8.2'
    r=make_room()
    assert Counter(p['role'] for p in r['players'])==Counter({'kira':1,'l':1,'believer':1,'investigator':2})
    believer=next(p for p in r['players'] if p['role']=='believer')
    view=m.view(r,believer)
    assert view['myRole']=='believer'
    assert [q['id'] for q in r['players'] if q['role']=='kira'][0] not in view['known'], 'Believer must not learn Kira'
    assert all('role' not in p or p['id']==believer['id'] for p in view['players']), 'Believer must not learn other roles'
    # The designated nominee and +/- are random, exactly as for investigator.
    believer['npc']=True
    choices={-1:0,1:0}
    for _ in range(200):
        a=m.npc_nominate(r,believer)
        assert a and a['target']!=believer['id'] and a['delta'] in (-1,1)
        choices[a['delta']]+=1
    assert choices[-1]>0 and choices[1]>0
    # Believer has no night action, even if present as an NPC.
    m.begin_night(r)
    assert r['actions'][believer['id']]=={'target':None}
    # Public-info rule inherited from v0.7.1: the only exclusions are Kira and follower.
    assert believer['role'] not in ('kira','follower')
    assert believer in [p for p in m.living(r) if p['role'] not in ('kira','follower')]
    # Losing a believer alone must not end the game, no matter their faction.
    r=make_room()
    believer=next(p for p in r['players'] if p['role']=='believer')
    believer['alive']=False
    assert not m.finish_if(r,believer,'検挙')
    assert r['winner'] is None
    # Existing role sets without believer remain supported.
    assert m.options_from({'size':7,'follower':1,'watari':1,'gevanni':1})['believer']==0
    assert m.options_from({'size':7,'follower':1,'believer':1,'watari':1,'gevanni':1})['believer']==1
    try: m.options_from({'size':5,'follower':1,'believer':2,'watari':0,'gevanni':0})
    except ValueError as exc: assert '捜査員' in str(exc)
    else: raise AssertionError('must retain at least one investigator')
    # Role guide has both descriptions and picture, and the config/presets reflect new field.
    html=(Path(__file__).resolve().parents[1]/'public/index.html').read_text()
    for x in ('id="believer"','信者 <small>｜キラ陣営','/static/roles/believer.webp','const CLIENT_VERSION=\'0.8.2\'','<th class="kira">信者</th>'):
        assert x in html, x
    assert (Path(__file__).resolve().parents[1]/'public/roles/believer.webp').exists()

async def recv_until(ws, wanted):
    for _ in range(30):
        m0=await asyncio.wait_for(ws.receive_json(),2)
        if m0.get('type')==wanted: return m0
    raise AssertionError(wanted)

async def socket_test():
    async with TestClient(TestServer(m.app)) as client:
        h=await client.ws_connect('/ws')
        await h.send_json({'type':'join','name':'Host','code':''})
        joined=await recv_until(h,'joined');code=joined['code']
        await recv_until(h,'state')
        await h.send_json({'type':'config','options':{'size':6,'follower':0,'believer':2,'watari':0,'gevanni':0,'discussion':40,'night':20}})
        state=(await recv_until(h,'state'))['data']
        assert state['options']['believer']==2 and state['options']['size']==6
        await h.send_json({'type':'start'})
        while True:
            state=(await recv_until(h,'state'))['data']
            if state['stage']=='role_reveal':break
        assert Counter(p['role'] for p in m.ROOMS[code]['players'])==Counter({'kira':1,'l':1,'believer':2,'investigator':2})
        assert state['version']=='0.8.2'
        assert sum('role' in p for p in state['players'])==1, 'Other roles stay hidden'
        await h.send_json({'type':'return'})
        while True:
            state=(await recv_until(h,'state'))['data']
            if state['stage']=='lobby':break
        assert state['options']['believer']==2
        await h.close()
    m.ROOMS.clear()

if __name__=='__main__':
    test_roles_and_rules()
    asyncio.run(socket_test())
    print('PASS: Believer, setup, faction, nomination, no Kira knowledge, night idle, lobby config, hidden roles')
