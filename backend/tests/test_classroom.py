from backend.app.content import assigned_posts
from backend.app.learning import readiness
from backend.tests.test_game import join
from backend.tests.test_learning_economy import setup_game, state, label_queue, train, buy
from backend.tests.test_experience import reset


def test_early_policy_anchors_and_readiness():
    for team in range(3):
        queue = assigned_posts(team, 0)
        assert queue[:6] == [0, 6, 1, 7, 2, 3]
        assert 5 in queue[:8]
    assert 'Single-class' in readiness([{'label':'allow'}]*6)
    assert 'one minority' in readiness([{'label':'allow'}]*5+[{'label':'remove'}])


def test_classroom_worker_caps_snapshot_and_reset(client):
    base, teacher, people = setup_game(client, count=4, settings={'classroom':True,'electricity_limit':6,'local_water_limit':6})
    a,b,c,d = people
    label_queue(client,base,a,count=6)
    endpoint=base+'/teams/0'
    decision={'choice':'paid','request_id':'worker-payment-01'}
    assert client.post(endpoint+'/worker',headers=a,json=decision).status_code==409
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    assert train(client,base,a).status_code==409
    assert buy(client,base,a,'compute').status_code==409
    assert client.post(endpoint+'/worker',headers=b,json=decision).status_code==403
    assert client.post(endpoint+'/worker',headers=d,json=decision).status_code==403
    assert client.post(endpoint+'/worker',headers=teacher,json=decision).status_code==403
    pid=client.get(base+'/instructor',headers=teacher).json()['participants'][3]['id']
    assert client.post(endpoint+'/representative',headers=teacher,json={'participant_id':pid}).status_code==200
    assert client.post(endpoint+'/worker',headers=d,json=decision).status_code==200
    assert client.post(endpoint+'/worker',headers=d,json=decision).json()['duplicate']
    e=state(client,base,a)['economy']
    assert e['balance']==80 and e['worker']['credits']==20
    assert train(client,base,a).status_code==200
    original=state(client,base,a)['economy']['model']
    assert original['site']=='air' and original['electricity']==4 and original['water']==1
    assert train(client,base,a).json()['duplicate']
    assert buy(client,base,a,'compute').status_code==200
    assert client.post(endpoint+'/profile',headers=a,json={'profile':'evaporative'}).status_code==200
    assert train(client,base,a,'same-fit-new-profile').status_code==409
    assert state(client,base,a)['economy']['model']==original
    client.post(endpoint+'/configuration',headers=a,json={'configuration':'word_unweighted'})
    assert train(client,base,a,'water-blocked-fit').status_code==409
    client.post(endpoint+'/profile',headers=a,json={'profile':'air'})
    assert train(client,base,a,'electricity-blocked-fit').status_code==409
    e=state(client,base,a)['economy']
    assert e['runs_used']==1 and e['balance']==55 and e['model']['stale']
    assert client.post(base+'/phase',headers=teacher,json={'phase':'testing'}).status_code==409
    assert client.post(base+'/phase',headers=teacher,json={'phase':'testing','omit_untrained':True}).status_code==200
    client.post(base+'/phase',headers=teacher,json={'phase':'reveal'})
    reveal=state(client,base,a)['reveal']
    assert reveal['teams'][0]['economy']['model']['stale']
    assert reveal['teams'][1]['economy']['model'] is None
    assert reset(client,base,teacher).status_code==200
    e=state(client,base,a)['economy']
    assert e['worker']['choice'] is None and e['worker']['credits']==0 and e['balance']==100
    assert client.post(endpoint+'/worker',headers=a,json=decision).status_code==409


def test_classroom_unbilled_and_profiles_trade_off(client):
    base,teacher,(a,)=setup_game(client,settings={'classroom':True})
    label_queue(client,base,a,count=6)
    client.post(base+'/phase',headers=teacher,json={'phase':'training'})
    client.post(base+'/teams/0/worker',headers=a,json={'choice':'unbilled','request_id':'unbilled-shift-01'})
    e=state(client,base,a)['economy']
    assert e['balance']==100 and e['worker']['credits']==0
    assert e['profiles']==[{'profile':'air','electricity':4,'water':1},{'profile':'evaporative','electricity':2,'water':6}]
    assert train(client,base,a).status_code==200
    buy(client,base,a,'compute')
    for config in ('word_unweighted','bigram'):
        client.post(base+'/teams/0/configuration',headers=a,json={'configuration':config})
        assert train(client,base,a,'training-fit-'+config.replace('_','-')).status_code==(409 if config=='bigram' else 200)
    assert state(client,base,a)['economy']['electricity_remaining']==4


def test_classroom_demo_profile_preserves_real_predictions(client):
    from backend.tests.test_experience import dashboard, advance
    from backend.tests.test_game import KEY, auth
    result=client.post('/api/rooms',json={'secret':KEY,'demo':True,'economy':{'classroom':True}}).json()
    base='/api/rooms/'+result['code']
    teacher=auth(result['token'])
    advance(client,base,teacher,'annotation')
    advance(client,base,teacher,'training')
    for team in range(3):
        endpoint=base+f'/teams/{team}'
        assert client.post(endpoint+'/worker',headers=teacher,json={'choice':'paid','request_id':'scripted-worker-shift'}).status_code==200
        assert train(client,base,teacher,team=team).status_code==200
    advance(client,base,teacher,'testing')
    before=dashboard(client,base,teacher)['comparison']['posts']
    advance(client,base,teacher,'training')
    assert client.post(base+'/teams/0/profile',headers=teacher,json={'profile':'evaporative'}).status_code==200
    assert train(client,base,teacher,'profile-only-retry').status_code==409
    advance(client,base,teacher,'testing')
    assert dashboard(client,base,teacher)['comparison']['posts']==before
    advance(client,base,teacher,'reveal')
    assert dashboard(client,base,teacher)['reveal']['demo']
    assert reset(client,base,teacher).status_code==200
    restored=dashboard(client,base,teacher)
    assert all(t['economy']['worker']['choice'] is None for t in restored['teams'])
    assert all(t['economy']['model'] is None for t in restored['teams'])
