import asyncio, importlib.util, json, sys
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer

file=Path(__file__).parent.parent / 'server.py'
spec=importlib.util.spec_from_file_location('kira_dx_server_v07', str(file))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

async def next_message(ws, type_name=None):
    for _ in range(30):
        msg=await asyncio.wait_for(ws.receive(),timeout=2)
        if msg.type.name!='TEXT':raise AssertionError(msg)
        data=json.loads(msg.data)
        if type_name is None or data.get('type')==type_name:return data
    raise AssertionError('no message '+str(type_name))

async def next_state(ws, pred=lambda data: True):
    for _ in range(30):
        msg=await next_message(ws)
        if msg['type']=='state' and pred(msg['data']):return msg['data']
    raise AssertionError('No expected state')

async def main():
    async with TestClient(TestServer(m.app)) as client:
        host=await client.ws_connect('/ws')
        await host.send_json({'type':'join','name':'HOST','code':''})
        joined=await next_message(host,'joined');code=joined['code'];host_token=joined['token']
        await next_state(host)
        assert len(m.ROOMS[code]['players'])==1
        audience=await client.ws_connect('/ws')
        await audience.send_json({'type':'join','name':'Viewer','code':code,'spectator':True})
        viewer_join=await next_message(audience,'joined');assert viewer_join['spectator']
        viewstate=await next_state(audience)
        assert viewstate['spectator'] and len(viewstate['players'])==1 and len(viewstate['spectators'])==1
        assert len(m.ROOMS[code]['players'])==1
        await audience.send_json({'type':'start'})
        err=await next_message(audience,'error'); assert '権限' in err['message']
        await host.send_json({'type':'config','options':{'size':5,'follower':1,'watari':0,'gevanni':0,'revealRolesOnDeath':False,'discussion':40,'night':20}})
        await host.send_json({'type':'start'})
        state=await next_state(host,lambda s:s['stage']=='role_reveal')
        watchstate=await next_state(audience,lambda s:s['stage']=='role_reveal')
        assert len(state['players'])==5 and sum('role' in x for x in state['players'])==1+len(state['known']) # follower/watari can initially know one additional role
        assert watchstate['watching'] and len(watchstate['players'])==5
        assert all('role' in x for x in watchstate['players'])
        assert watchstate['myRole'] is None
        await audience.send_json({'type':'nominate','target':state['players'][0]['id'],'delta':1})
        err=await next_message(audience,'error');assert '観戦者' in err['message']
        await audience.send_json({'type':'night','target':state['players'][0]['id']})
        err=await next_message(audience,'error');assert '観戦者' in err['message']
        late=await client.ws_connect('/ws')
        await late.send_json({'type':'join','name':'Late','code':code,'spectator':True})
        j=await next_message(late,'joined');assert j['spectator']
        lateview=await next_state(late)
        assert lateview['spectator'] and len(lateview['players'])==5
        active=m.ROOMS[code]
        hp=next(p for p in active['players'] if p['id']==host_token)
        hp['alive']=False
        active['stage']='nomination'
        active['actions']={}
        m.broadcast(active)
        deadview=await next_state(host,lambda s:s['stage']=='nomination')
        assert deadview['watching'] and not deadview['spectator']
        assert len([x for x in deadview['players'] if 'role' in x])==5
        await host.send_json({'type':'nominate','target':active['players'][1]['id'],'delta':1})
        err=await next_message(host,'error');assert '脱落者' in err['message']
        await host.send_json({'type':'night','target':active['players'][1]['id']})
        err=await next_message(host,'error');assert '脱落者' in err['message']
        await host.send_json({'type':'return'})
        lobby=await next_state(host,lambda s:s['stage']=='lobby')
        lobbyviewer=await next_state(audience,lambda s:s['stage']=='lobby')
        assert not lobby['watching'] and lobbyviewer['spectator'] and len(lobbyviewer['spectators'])==2
        assert len(lobby['players'])==1 and not lobby['players'][0]['npc']
        await late.send_json({'type':'leave'});assert (await next_message(late,'left'))['type']=='left'
        await next_state(audience,lambda s:len(s['spectators'])==1)
        await host.close(); await audience.close();await late.close()
    print('PASS: spectator before/after start, all roles visible only to watchers, dead player watches, actions rejected, spectators excluded from player counts, return lobby preserved')

asyncio.run(main())
