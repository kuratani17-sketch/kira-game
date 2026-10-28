"""Run with: python tests/test_private_investigation.py"""
import importlib.util
from pathlib import Path

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('kira_dx',root/'server.py')
srv=importlib.util.module_from_spec(spec);spec.loader.exec_module(srv)

def main():
    players=[]
    for i,role in enumerate(('l','kira','investigator','believer','gevanni')):
        p=srv.makeplayer(f'p{i}',f'P{i}',False,None)
        p.update(role=role,alive=True)
        players.append(p)
    room={
        'code':'TEST','players':players,'spectators':[],'host':'p0','stage':'night',
        'options':srv.options_from({'size':5,'follower':0,'believer':1,'gevanni':1,'revealRolesOnDeath':False}),
        'day':1,'round':3,'deadline':None,'actions':{},'log':[],'publicInfo':[],
        'dailyNominations':[],'winner':None,'reveal':None,'next':'', 'gameId':'testing'
    }
    room['actions']={'p0':{'target':'p1'},'p1':{'target':None},'p2':{'target':None},'p3':{'target':None},'p4':{'target':'p2'}}
    srv.resolve_night(room)
    lstate=srv.view(room,players[0]); assert lstate['investigations']==[{'target':'p1','name':'P1','result':True}]
    assert lstate['myRole']=='l' and lstate['watching']==False
    for p in players[1:]:
        other=srv.view(room,p)
        assert other['investigations']==[],f'{p["role"]} received L investigation'
    viewer=srv.makeplayer('viewer','viewer',False,None,spectator=True)
    assert srv.view(room,viewer)['investigations']==[]
    # The next night L investigates an innocent, giving a private non-Kira result.
    room['stage']='night'
    room['actions']={'p0':{'target':'p2'},'p1':{'target':None},'p2':{'target':None},'p3':{'target':None},'p4':{'target':'p0'}}
    srv.resolve_night(room)
    records=srv.view(room,players[0])['investigations']
    assert len(records)==2 and records[0]['result'] is True and records[1]['result'] is False
    assert not srv.view(room,players[2])['investigations']
    html=(root/'public'/'index.html').read_text(encoding='utf-8')
    assert 'id="investigationOverlay"' in html
    assert "S.myRole!=='l'" in html
    assert "report.result?'キラである':'キラではない'" in html
    assert 'showPrivateInvestigation();' in html
    print('PASS: private L reports positive/negative, server excludes investigators/spectators, center UI available')

if __name__=='__main__': main()
