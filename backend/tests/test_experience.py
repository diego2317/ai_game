from contextlib import contextmanager
from datetime import timedelta
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from backend.app.db import get_db
from backend.app.main import app
from backend.app.models import Participant, RoomExperience, TrainingRun, now
from backend.tests.test_game import KEY, auth, join, room
from backend.tests.test_learning_economy import buy, label_queue, setup_game, state, train


def demo_room(client):
    result=client.post('/api/rooms',json={'secret':KEY,'demo':True})
    assert result.status_code==201
    code=result.json()['code']
    return f'/api/rooms/{code}', auth(result.json()['token'])


def dashboard(client,base,teacher):
    return client.get(base+'/instructor',headers=teacher).json()


def advance(client,base,teacher,phase,generation=0):
    response=client.post(base+'/phase',headers=teacher,json={'phase':phase,'generation':generation,'omit_untrained':phase=='testing'})
    assert response.status_code==200,response.text


def reset(client,base,teacher,generation=0,key='reset-classroom-request'):
    return client.post(base+'/reset',headers=teacher,json={'confirmation':base.split('/')[-1],'generation':generation,'request_id':key})


def test_demo_is_separate_scripted_ready_to_train_and_repeatable(client):
    base,teacher=demo_room(client)
    original=dashboard(client,base,teacher)
    assert original['demo'] is True and original['phase']=='lobby'
    assert original['reveal'] is None
    assert len(original['participants'])==15
    assert all(p['simulated'] and not p['online'] for p in original['participants'])
    assert [t['annotations'] for t in original['teams']]==[92,92,92]
    assert all(t['economy']['training_problem'] is None for t in original['teams'])
    assert client.post(base+'/join',json={'nickname':'Real visitor'}).status_code==409
    advance(client,base,teacher,'annotation')
    assert client.post(base+'/demo/annotate',headers=teacher,json={}).json()['simulated_annotations']==0
    advance(client,base,teacher,'training')
    for team in range(3):
        assert train(client,base,teacher,team=team).status_code==200
    advance(client,base,teacher,'testing')
    testing=dashboard(client,base,teacher)
    assert all(t['economy']['model'] for t in testing['teams'])
    advance(client,base,teacher,'reveal')
    final=dashboard(client,base,teacher)
    assert final['reveal']['demo'] is True
    assert sum(t['annotations'] for t in final['reveal']['teams'])==276
    assert sum(t['economy']['runs_used'] for t in final['reveal']['teams'])==3
    assert reset(client,base,teacher).status_code==200
    restored=dashboard(client,base,teacher)
    assert restored['phase']=='lobby' and restored['demo'] is True and restored['generation']==1
    assert [t['annotations'] for t in restored['teams']]==[92,92,92]
    assert all(t['economy']['model'] is None and t['economy']['balance']==100 for t in restored['teams'])


def test_demo_investments_audit_and_new_annotations_use_real_paths(client):
    base,teacher=demo_room(client)
    advance(client,base,teacher,'annotation')
    advance(client,base,teacher,'training')
    assert buy(client,base,teacher,'annotation').status_code==200
    assert client.post(base+'/demo/annotate',headers=teacher,json={}).json()['simulated_annotations']==10
    assert buy(client,base,teacher,'audit').status_code==200
    e=dashboard(client,base,teacher)['teams'][0]['economy']
    dispute=e['disputes'][0]
    assert client.post(base+'/teams/0/audit',headers=teacher,json={'post_id':dispute['post_id']}).status_code==200
    assert client.post(base+'/teams/0/audit',headers=teacher,json={'post_id':dispute['post_id'],'label':'allow'}).status_code==200
    updated=dashboard(client,base,teacher)['teams'][0]
    assert updated['annotations']==102
    assert updated['economy']['balance']==55
    assert updated['economy']['unresolved_disagreements']==e['unresolved_disagreements']-1
    assert train(client,base,teacher).status_code==200


def test_live_reveal_is_instructor_controlled_and_freezes_all_decisions(client):
    base,teacher,(person,)=setup_game(client)
    label_queue(client,base,person)
    assert state(client,base,person)['reveal'] is None
    assert client.post(base+'/phase',headers=teacher,json={'phase':'reveal'}).status_code==409
    advance(client,base,teacher,'training')
    train(client,base,person)
    advance(client,base,teacher,'testing')
    assert state(client,base,person)['reveal'] is None
    assert client.post(base+'/phase',headers=person,json={'phase':'reveal'}).status_code==403
    advance(client,base,teacher,'reveal')
    response=client.get(base+'/student',headers=person)
    assert response.headers['cache-control']=='no-store'
    current=response.json()
    assert current['post'] is None and current['reveal']['demo'] is False
    t=current['reveal']['teams'][0]
    assert t['annotations']==12 and t['members']==1
    assert t['economy']['model']['evaluation']['test_count']==20
    assert t['economy']['resources']['training_ms']>0
    assert t['economy']['resources']['illustrative_electricity_kwh']==2
    assert t['economy']['resources']['illustrative_water_liters']==6
    assert 'illustrative game quantities' in current['reveal']['resource_note']
    assert buy(client,base,person,'compute').status_code==409
    assert train(client,base,person,'late-training-request').status_code==409
    assert client.post(base+'/labels',headers=person,json={'assignment_id':1,'label':'allow'}).status_code==409
    assert client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'word'}).status_code==409
    assert client.post(base+'/teams/0/audit',headers=person,json={'post_id':0}).status_code==409
    advance(client,base,teacher,'testing')
    assert state(client,base,person)['reveal'] is None


def test_live_reset_keeps_sessions_settings_and_rejects_delayed_writes(client):
    base,teacher,(person,)=setup_game(client,settings={'starting_budget':175})
    label_queue(client,base,person)
    old_task=state(client,base,person)['post']['assignment_id']
    advance(client,base,teacher,'training')
    train(client,base,person)
    buy(client,base,person,'compute')
    assert reset(client,base,person).status_code==403
    assert client.post(base+'/reset',headers=teacher,json={'confirmation':'WRONG','generation':0,'request_id':'reset-classroom-request'}).status_code==422
    assert reset(client,base,teacher).status_code==200
    assert reset(client,base,teacher).json()['duplicate'] is True
    cleared=state(client,base,person)
    assert cleared['completed']==0 and cleared['phase']=='lobby' and cleared['generation']==1
    assert cleared['economy']['balance']==175 and cleared['economy']['purchases']==[]
    assert cleared['economy']['model'] is None and cleared['economy']['history']==[]
    assert cleared['economy']['runs_remaining']==1
    assert reset(client,base,teacher,key='another-stale-reset').status_code==409
    # Stale phase/config/purchase requests must not spend or advance the fresh round.
    assert client.post(base+'/phase',headers=teacher,json={'phase':'annotation'}).status_code==409
    advance(client,base,teacher,'annotation',generation=1)
    assert client.post(base+'/labels',headers=person,json={'assignment_id':old_task,'label':'allow'}).status_code==409
    assert client.post(base+'/labels',headers=person,json={'assignment_id':state(client,base,person)['post']['assignment_id'],'label':'allow','generation':1}).status_code==200
    advance(client,base,teacher,'training',generation=1)
    assert buy(client,base,person,'compute','old-purchase-retry').status_code==409
    assert train(client,base,person,'old-training-retry').status_code==409
    assert client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'word'}).status_code==409
    assert state(client,base,person)['economy']['balance']==175
    assert client.post(base+'/teams/0/purchase',headers=person,json={'action':'compute','request_id':'fresh-purchase-request','generation':1}).status_code==200


def test_demo_and_reset_room_isolation(client):
    base,teacher,(person,)=setup_game(client)
    other,other_teacher=demo_room(client)
    assert client.post(base+'/demo/annotate',headers=teacher,json={}).status_code==409
    assert client.post(other+'/demo/annotate',headers=person,json={}).status_code==403
    assert reset(client,other,teacher).status_code==403
    assert client.post(other+'/phase',headers=teacher,json={'phase':'annotation'}).status_code==403
    assert dashboard(client,other,other_teacher)['generation']==0
    # A live instructor cannot manufacture votes or spend as a student.
    advance(client,base,teacher,'training')
    assert buy(client,base,teacher,'audit').status_code==403
    assert client.post(base+'/teams/0/audit',headers=teacher,json={'post_id':0}).status_code==403


def test_phase_clock_pause_resume_and_advisory_pacing(client):
    base,teacher,(person,)=setup_game(client)
    code=base.split('/')[-1]
    with contextmanager(app.dependency_overrides[get_db])() as db:
        meta=db.get(RoomExperience,code)
        meta.phase_started_at=now()-timedelta(seconds=350)
        db.commit()
    clock=state(client,base,person)['timing']
    assert clock['recommended_seconds']==300 and clock['elapsed_seconds']>=350
    assert state(client,base,person)['phase']=='annotation'  # Never auto-advances.
    advance(client,base,teacher,'paused')
    paused=state(client,base,person)['timing']
    assert paused['paused'] is True and paused['elapsed_seconds']>=350
    advance(client,base,teacher,'annotation')
    assert state(client,base,person)['timing']['elapsed_seconds']>=350
    advance(client,base,teacher,'training')
    assert state(client,base,person)['timing']['elapsed_seconds']<5
    assert state(client,base,person)['timing']['recommended_seconds']==240


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL','').startswith('postgresql'),reason='Requires PostgreSQL row locks.')
def test_concurrent_reset_requests_reset_exactly_once(client):
    base,teacher,students=setup_game(client,count=4)
    label_queue(client,base,students[0],count=8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:reset(client,base,teacher),range(2)))
    assert all(r.status_code==200 for r in outcomes)
    assert sum(r.json().get('duplicate',False) for r in outcomes)==1
    assert dashboard(client,base,teacher)['generation']==1
    assert len(dashboard(client,base,teacher)['participants'])==4
    assert all(state(client,base,p)['completed']==0 for p in students)
