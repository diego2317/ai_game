import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from backend.app.content import POSTS
from backend.app.learning import fit_and_evaluate
from backend.app.models import Assignment, AuditDecision, Participant, Purchase, Room, RoomRules, TeamAccount, TrainingRun
from backend.tests.test_game import auth, join, room, KEY


def setup_game(client, count=1, settings=None):
    result = client.post('/api/rooms', json={'secret':KEY, 'economy': settings or {}})
    assert result.status_code == 201
    code = result.json()['code']
    teacher = auth(result.json()['token'])
    students = [join(client, code, f'Player {n}') for n in range(count)]
    base = f'/api/rooms/{code}'
    client.post(base+'/phase', headers=teacher, json={'phase':'annotation'})
    return base, teacher, students


def label_queue(client, base, student, count=12, invert=False):
    # Alternating labels are intentional test inputs, not reference answers.
    for n in range(count):
        state = client.get(base+'/student', headers=student).json()
        assert state['post'] is not None
        label = ('allow' if n % 2 == 0 else 'remove') if not invert else ('remove' if n % 2 == 0 else 'allow')
        assert client.post(base+'/labels', headers=student, json={'assignment_id':state['post']['assignment_id'],'label':label}).status_code == 200


def state(client, base, student):
    return client.get(base+'/student', headers=student).json()


def buy(client, base, student, action, key=None, team=0):
    return client.post(base+f'/teams/{team}/purchase', headers=student, json={'action':action,'request_id':key or f'request-{action}'})


def train(client, base, credentials, key='training-request-01', team=0):
    return client.post(base+f'/teams/{team}/train', headers=credentials, json={'request_id':key})


def test_real_learning_responds_to_labels_and_never_fits_heldout():
    rows = [{'post_id':i, 'label':'allow' if i%2 else 'remove'} for i in range(20)]
    ms, evaluation, artifact = fit_and_evaluate(rows, 'word')
    opposite = [{'post_id':r['post_id'], 'label':'remove' if r['label']=='allow' else 'allow'} for r in rows]
    _, flipped, _ = fit_and_evaluate(opposite, 'word')
    assert ms > 0 and artifact['coefficients'] and artifact['idf']
    assert 'solvent' not in artifact['vocabulary']  # Held-out-only vocabulary.
    assert len(evaluation['predictions']) == 20
    assert sum(map(sum,evaluation['confusion_matrix'])) == 20
    for a,b in zip(evaluation['predictions'], flipped['predictions']):
        assert a['remove_score'] == pytest.approx(1-b['remove_score'], abs=1e-6)
    assert any(a['prediction']!=b['prediction'] for a,b in zip(evaluation['predictions'], flipped['predictions']))
    with pytest.raises(ValueError, match='Held-out'):
        fit_and_evaluate(rows+[{'post_id':100,'label':'allow'}], 'word')


def test_one_device_training_evaluation_and_idempotency(client):
    base, teacher, (person,) = setup_game(client)
    label_queue(client, base, person)
    # Instructor controls training phase; a student cannot advance it.
    assert client.post(base+'/phase',headers=person,json={'phase':'training'}).status_code==403
    assert train(client,base,person).status_code==409
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    assert train(client,base,teacher,team=1).status_code==409  # Empty team does not train.
    response=train(client,base,person)
    assert response.status_code==200 and response.json()['training_ms']>0
    assert train(client,base,person).json()['duplicate'] is True
    before=state(client,base,person)
    assert before['economy']['runs_used']==1 and before['economy']['runs_remaining']==0
    assert 'evaluation' not in before['economy']['model'] and before['comparison'] is None
    assert train(client,base,person,'training-request-02').status_code==409
    client.post(base+'/phase',headers=teacher,json={'phase':'testing'})
    testing=state(client,base,person)
    comparison=testing['comparison']
    assert len(comparison['posts'])==20
    assert [t['economy']['model'] is None for t in comparison['teams']]==[False,True,True]
    evaluation=testing['economy']['model']['evaluation']
    assert 0<=evaluation['accuracy']<=1
    assert sum(map(sum,evaluation['confusion_matrix']))==20
    assert testing['post'] is None
    assert buy(client,base,person,'compute').status_code==409
    assert 'vocabulary' not in str(comparison)
    assert client.get(base+'/instructor',headers=person).status_code==403
    # Persistence across new requests/sessions is backed by stored run JSON.
    assert state(client,base,person)['economy']['history'][0]['accuracy']==evaluation['accuracy']


def test_small_single_class_and_tied_datasets_do_not_consume_runs(client):
    base, teacher, (person,) = setup_game(client)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    assert '6 distinct' in train(client,base,person).json()['detail']
    for _ in range(7):
        post=state(client,base,person)['post']
        client.post(base+'/labels',headers=person,json={'assignment_id':post['assignment_id'],'label':'allow'})
    failure=train(client,base,person)
    assert failure.status_code==409 and '2 Allow and 2 Remove' in failure.json()['detail']
    assert state(client,base,person)['economy']['runs_remaining']==1


def test_economy_unlocks_are_real_and_budget_is_server_owned(client):
    base, teacher, (person,) = setup_game(client)
    label_queue(client,base,person)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    original=state(client,base,person)
    # Locked model choices cannot be selected by changing an API request.
    assert client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'character'}).status_code==409
    assert buy(client,base,person,'annotation').status_code==200
    assert buy(client,base,person,'annotation').json()['duplicate'] is True
    after=state(client,base,person)
    assert after['total']==original['total']+10
    assert after['economy']['balance']==75
    assert buy(client,base,person,'compute').status_code==200
    assert buy(client,base,person,'infrastructure').status_code==200
    e=state(client,base,person)['economy']
    assert e['balance']==0 and e['runs_remaining']==3
    assert {c['id'] for c in e['configurations']}=={'word','word_unweighted','bigram','character'}
    assert buy(client,base,person,'audit').status_code==409
    client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'character'})
    assert train(client,base,person).status_code==200
    resources=state(client,base,person)['economy']['resources']
    assert resources['illustrative_electricity_kwh']==6
    assert resources['illustrative_water_liters']==18
    assert resources['illustrative_hardware_units']==2
    assert train(client,base,person,'training-request-02').status_code==409  # Same data/config.
    assert state(client,base,person)['economy']['runs_remaining']==2
    client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'bigram'})
    assert train(client,base,person,'training-request-03').status_code==200
    assert state(client,base,person)['economy']['resources']['illustrative_electricity_kwh']==9
    assert buy(client,base,person,'annotation','new-annotation-request').status_code==409


def test_audits_preserve_labor_votes_and_change_training_data(client):
    base, teacher, students = setup_game(client, count=4)
    a, _, _, d=students
    label_queue(client,base,a,count=8)
    label_queue(client,base,d,count=8,invert=True)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    e=state(client,base,a)['economy']
    assert e['usable_posts']==0 and e['tied_posts_excluded']==8
    assert client.post(base+'/teams/0/audit',headers=a,json={'post_id':0}).status_code==403
    assert buy(client,base,a,'audit').status_code==200
    assert buy(client,base,d,'audit','other-audit-request').status_code==409
    e=state(client,base,a)['economy']
    assert len(e['disputes'])==8
    assert client.post(base+'/teams/0/audit',headers=a,json={'post_id':99}).status_code==409
    assert client.post(base+'/teams/0/audit',headers=a,json={'post_id':0,'label':'allow'}).status_code==409
    for i in range(8):
        assert client.post(base+'/teams/0/audit',headers=a,json={'post_id':i}).status_code==200
        assert client.post(base+'/teams/0/audit',headers=d,json={'post_id':i,'label':'allow' if i%2 else 'remove'}).status_code==200
    e=state(client,base,a)['economy']
    assert e['usable_posts']==8 and e['tied_posts_excluded']==0
    assert e['unresolved_disagreements']==0
    assert client.post(base+'/teams/0/audit',headers=a,json={'post_id':0,'label':'allow'}).status_code==409
    # Original disagreements and original annotation count remain unchanged.
    stats=client.get(base+'/instructor',headers=teacher).json()['teams'][0]
    assert stats['annotations']==16 and stats['disagreements']==8
    assert train(client,base,a).status_code==200
    client.post(base+'/phase',headers=teacher,json={'phase':'testing'})
    assert state(client,base,a)['economy']['model']['training_posts']==8


def test_authorization_configuration_custom_rules_and_expansion_boundary(client):
    assert client.post('/api/rooms',json={'secret':KEY,'economy':{'starting_budget':-1}}).status_code==422
    base, teacher, (person,) = setup_game(client,settings={'starting_budget':200,'annotation_cost':10,'electricity_per_run':4})
    other_code,_=room(client)
    outsider=join(client,other_code)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    assert buy(client,base,outsider,'compute').status_code==403
    assert buy(client,base,person,'compute',team=1).status_code==403
    assert train(client,base,person,team=1).status_code==403
    assert buy(client,base,teacher,'compute').status_code==403  # Teacher does not impersonate spending.
    assert client.post(base+'/teams/0/purchase',headers=person,json={'action':'free-money','request_id':'test-request'}).status_code==422
    for i in range(4):
        assert buy(client,base,person,'annotation',f'annotation-pack-{i}').status_code==200
    assert buy(client,base,person,'annotation','annotation-pack-extra').status_code==409
    assert state(client,base,person)['economy']['balance']==160
    seen=set()
    while (post:=state(client,base,person)['post']) is not None:
        assert post['text'] not in POSTS[100:]
        assert post['text'] not in seen
        seen.add(post['text'])
        client.post(base+'/labels',headers=person,json={'assignment_id':post['assignment_id'],'label':'allow'})
    assert len(seen)==59  # Original solo queue plus 40 expansion posts.
    # Reusing a recorded request id for another action must never charge again.
    assert buy(client,base,person,'compute','annotation-pack-0').status_code==409
    client.post(base+'/phase',headers=teacher,json={'phase':'testing'})
    assert client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'word'}).status_code==409


def test_improvement_round_stale_snapshot_and_no_test_label_leak(client):
    base,teacher,(person,)=setup_game(client)
    label_queue(client,base,person)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    train(client,base,person)
    client.post(base+'/phase',headers=teacher,json={'phase':'testing'})
    first=state(client,base,person)['economy']['model']
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    buy(client,base,person,'compute')
    # Changing training data marks the old model stale; its test results stay hidden.
    label_queue(client,base,person,count=1)
    current=state(client,base,person)
    assert current['economy']['model']['stale'] is True
    assert 'evaluation' not in current['economy']['model']
    assert train(client,base,person,'improved-training-request').status_code==200
    client.post(base+'/phase',headers=teacher,json={'phase':'testing'})
    improved=state(client,base,person)['economy']
    assert improved['model']['id']!=first['id'] and improved['model']['training_posts']==13
    assert len(improved['history'])==2 and improved['runs_used']==2


def test_existing_room_gets_default_economy_without_losing_labels(client):
    from backend.app.db import get_db
    from backend.app.main import app
    base,teacher,(person,)=setup_game(client)
    label_queue(client,base,person,count=2)
    code=base.split('/')[-1]
    # Emulate an existing M1 room: only original tables have records.
    from contextlib import contextmanager
    with contextmanager(app.dependency_overrides[get_db])() as db:
        for account in db.scalars(select(TeamAccount).where(TeamAccount.room_code==code)):
            db.delete(account)
        db.delete(db.get(RoomRules,code))
        db.commit()
    restored=state(client,base,person)
    assert restored['completed']==2 and restored['economy']['balance']==100


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL','').startswith('postgresql'),reason='Requires PostgreSQL row locking.')
def test_concurrent_team_purchases_and_training_cannot_double_spend(client):
    base,teacher,students=setup_game(client,count=4,settings={'starting_budget':25})
    a,_,_,d=students
    label_queue(client,base,a,count=12)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda args:buy(client,base,args[0],'compute',args[1]),[(a,'concurrent-purchase-a'),(d,'concurrent-purchase-b')]))
    assert sorted(r.status_code for r in results)==[200,409]
    e=state(client,base,a)['economy']
    assert e['balance']==0 and len(e['purchases'])==1 and e['runs_remaining']==3
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda credentials:train(client,base,credentials,'same-training-request'),[a,d]))
    assert all(r.status_code==200 for r in results)
    assert sum(r.json().get('duplicate',False) for r in results)==1
    assert state(client,base,a)['economy']['runs_used']==1


def test_three_models_compare_the_same_reference_and_show_real_disagreements(client):
    base,teacher,students=setup_game(client,count=3)
    for index,person in enumerate(students):
        label_queue(client,base,person,count=12,invert=index==1)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    for team,person in enumerate(students):
        assert train(client,base,person,team=team).status_code==200
    client.post(base+'/phase',headers=teacher,json={'phase':'testing'})
    comparison=state(client,base,students[0])['comparison']
    assert all(len(p['predictions'])==3 for p in comparison['posts'])
    assert any(p['disagreement'] for p in comparison['posts'])
    assert all(t['economy']['model']['evaluation']['test_count']==20 for t in comparison['teams'])
    for post in comparison['posts']:
        assert post['disagreement']==(len({p['prediction'] for p in post['predictions']})>1)


def test_illustrative_electricity_limit_is_enforced_without_consuming_a_run(client):
    base,teacher,(person,)=setup_game(client,settings={'electricity_limit':4})
    label_queue(client,base,person)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    buy(client,base,person,'compute')
    buy(client,base,person,'infrastructure')
    client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'character'})
    result=train(client,base,person)
    assert result.status_code==409 and 'illustrative electricity' in result.json()['detail']
    assert state(client,base,person)['economy']['runs_used']==0
    client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'word'})
    assert train(client,base,person).status_code==200
    client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'word_unweighted'})
    assert train(client,base,person,'unweighted-training-request').status_code==200
    e=state(client,base,person)['economy']
    assert e['electricity_remaining']==0 and e['runs_remaining']==1
    client.post(base+'/teams/0/configuration',headers=person,json={'configuration':'bigram'})
    assert train(client,base,person,'bigram-training-request').status_code==409
    assert state(client,base,person)['economy']['runs_remaining']==1
