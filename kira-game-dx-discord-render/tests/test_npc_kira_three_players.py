"""Ver.0.7.1: NPC Kira must judge when exactly three players remain."""
import importlib.util, random
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('kira_game_dx',Path(__file__).resolve().parents[1]/'server.py')
srv=importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

def make_room(alive_count):
    # Kira NPC, L human, one other human to hold night open; the rest NPC.
    roles=['kira','l','investigator','investigator','investigator']
    players=[]
    for i,role in enumerate(roles):
        p=srv.makeplayer(str(i),f'P{i}',i==0 or i>=3,None)
        p['role']=role
        p['alive']=i<alive_count
        players.append(p)
    return {'players':players,'actions':{},'log':[],
            'stage':'discussion','deadline':None,'reveal':None,'options':srv.options_from({}),
            'day':1,'round':1,'winner':None,'next':'','publicInfo':[]}

def run():
    for count in (3,):
        r=make_room(count)
        # Adversarial choice always returns False for a bool pair; it must NOT allow a pass at 3.
        with patch.object(srv.random,'choice',side_effect=lambda arr: arr[-1]):
            srv.begin_night(r)
        target=r['actions']['0']['target']
        assert target is not None, 'NPC Kira incorrectly skipped judgment at 3 survivors'
        assert target in ('1','2'),target
        assert len(srv.living(r))==3
    # For four or five survivors the existing 50% pass behavior is still available.
    for count in (4,5):
        r=make_room(count)
        with patch.object(srv.random,'choice',side_effect=lambda arr: arr[-1]):
            srv.begin_night(r)
        assert r['actions']['0']['target'] is None, '4+ should still allow pass'
        r=make_room(count)
        with patch.object(srv.random,'choice',side_effect=lambda arr: arr[0]):
            srv.begin_night(r)
        assert r['actions']['0']['target'] is not None, '4+ should still allow cast'
    assert srv.VERSION=='0.8.2'
    print('PASS: 3 survivors always cast, 4-5 survivors retain both possible behaviors, version 0.8.2')

if __name__=='__main__':run()
