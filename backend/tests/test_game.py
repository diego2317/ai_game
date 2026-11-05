from backend.app.content import POSTS, assigned_posts, team_posts

KEY = 'classroom-test-instructor-key'


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def room(client):
    r = client.post('/api/rooms', json={'secret': KEY})
    assert r.status_code == 201
    data = r.json()
    return data['code'], auth(data['token'])


def join(client, code, name='Maya'):
    r = client.post(f'/api/rooms/{code}/join', json={'nickname': name})
    assert r.status_code == 201
    return auth(r.json()['token'])


def test_instructor_security_and_validation(client):
    assert client.post('/api/rooms', json={'secret': 'wrong'}).status_code == 403
    code, teacher = room(client)
    assert client.get(f'/api/rooms/{code}/instructor').status_code == 401
    person = join(client, code)
    assert client.get(f'/api/rooms/{code}/instructor', headers=person).status_code == 403
    assert client.post(f'/api/rooms/{code}/phase', headers=person, json={'phase':'annotation'}).status_code == 403
    assert client.post(f'/api/rooms/{code}/join', json={'nickname':'  '}).status_code == 422
    assert client.post(f'/api/rooms/{code}/join', json={'nickname':'maya'}).status_code == 409
    assert client.post('/api/rooms/XXXXXX/join', json={'nickname':'Lee'}).status_code == 404


def test_balanced_teams_variable_attendance_and_isolation(client):
    code, teacher = room(client)
    students = []
    for n in range(23):
        students.append(join(client, code, f'Student {n}'))
        state = client.get(f'/api/rooms/{code}/instructor', headers=teacher).json()
        sizes = [t['members'] for t in state['teams']]
        assert sum(sizes) == n + 1
        assert max(sizes) - min(sizes) <= 1
    # Teams larger than five still get complete, nonduplicate annotation queues.
    client.post(f'/api/rooms/{code}/phase', headers=teacher, json={'phase':'annotation'})
    for person in students:
        state = client.get(f'/api/rooms/{code}/student', headers=person).json()
        assert state['total'] in (18, 19) and state['post'] is not None
    late = join(client, code, 'Late arrival')
    assert client.get(f'/api/rooms/{code}/student', headers=late).json()['team'] == 2
    other, _ = room(client)
    assert client.get(f'/api/rooms/{other}/student', headers=students[0]).status_code == 403
    assert client.get(f'/api/rooms/{other}/instructor', headers=teacher).status_code == 403


def test_annotation_pause_duplicates_metrics_and_ownership(client):
    code, teacher = room(client)
    a = join(client, code, 'A')
    join(client, code, 'B')
    join(client, code, 'C')
    d = join(client, code, 'D')  # Same team as A; first anchor overlaps.
    prefix = f'/api/rooms/{code}'
    assert client.get(prefix+'/student', headers=a).json()['post'] is None
    assert client.post(prefix+'/phase', headers=teacher, json={'phase':'annotation'}).status_code == 200
    state = client.get(prefix+'/student', headers=a).json()
    task = state['post']['assignment_id']
    assert 'reference' not in state['post']
    assert client.post(prefix+'/labels', headers=d, json={'assignment_id':task,'label':'allow'}).status_code == 409
    assert client.post(prefix+'/labels', headers=a, json={'assignment_id':task,'label':'allow'}).status_code == 200
    assert client.post(prefix+'/labels', headers=a, json={'assignment_id':task,'label':'remove'}).status_code == 409
    shared = client.get(prefix+'/student', headers=d).json()['post']
    assert shared['text'] == state['post']['text']
    assert client.post(prefix+'/labels', headers=d, json={'assignment_id':shared['assignment_id'],'label':'remove'}).status_code == 200
    stats = client.get(prefix+'/instructor', headers=teacher).json()['teams'][0]
    assert stats['annotations'] == 2 and stats['disagreements'] == 1
    assert stats['allow'] == 1 and stats['remove'] == 1
    assert stats['labor_seconds'] >= 0 and stats['seconds_per_label'] is not None
    task2 = client.get(prefix+'/student', headers=a).json()['post']['assignment_id']
    client.post(prefix+'/phase', headers=teacher, json={'phase':'paused'})
    assert client.post(prefix+'/labels', headers=a, json={'assignment_id':task2,'label':'allow'}).status_code == 409
    assert client.get(prefix+'/student', headers=a).json()['post'] is None
    client.post(prefix+'/phase', headers=teacher, json={'phase':'annotation'})
    assert client.get(prefix+'/student', headers=a).json()['post']['assignment_id'] == task2
    client.post(prefix+'/phase', headers=teacher, json={'phase':'complete'})
    assert client.post(prefix+'/phase', headers=teacher, json={'phase':'annotation'}).status_code == 409
    assert client.post(prefix+'/join', json={'nickname':'Late'}).status_code == 409


def test_team_changes_rebuild_assignments_only_in_lobby(client):
    code, teacher = room(client)
    a = join(client, code)
    prefix = f'/api/rooms/{code}'
    person = client.get(prefix+'/instructor', headers=teacher).json()['participants'][0]
    assert client.post(prefix+f'/participants/{person["id"]}/team', headers=teacher, json={'team':2}).status_code == 200
    assert client.get(prefix+'/student', headers=a).json()['team'] == 2
    client.post(prefix+'/phase', headers=teacher, json={'phase':'annotation'})
    assert client.post(prefix+f'/participants/{person["id"]}/team', headers=teacher, json={'team':1}).status_code == 409


def test_all_queues_finish_and_labels_persist(client):
    code, teacher = room(client)
    student = join(client, code)
    prefix = f'/api/rooms/{code}'
    client.post(prefix+'/phase', headers=teacher, json={'phase':'annotation'})
    seen = []
    while True:
        state = client.get(prefix+'/student', headers=student).json()
        if not state['post']:
            break
        post = state['post']
        seen.append(post['text'])
        response = client.post(prefix+'/labels', headers=student, json={'assignment_id':post['assignment_id'],'label':'allow'})
        assert response.status_code == 200
    assert len(seen) == state['total'] == state['completed']
    assert len(seen) == len(set(seen))
    assert set(seen).isdisjoint(POSTS[100:])
    stats = client.get(prefix+'/instructor', headers=teacher).json()['teams'][0]
    assert stats['annotations'] == state['total'] and stats['remove'] == 0


def test_dataset_overlap_and_heldout_boundary():
    assert len(POSTS) == 120 and len(set(POSTS)) == 120
    pools = [set(team_posts(t)) for t in range(3)]
    assert all(len(pool)==60 for pool in pools)
    assert pools[0] != pools[1] != pools[2]
    for team in range(3):
        assignments = [assigned_posts(team, seat) for seat in range(12)]
        assert all(len(a) == len(set(a)) and len(a) >= 18 for a in assignments)
        assert set.union(*(set(a) for a in assignments)) == pools[team]
        assert all(set(a).issubset(set(range(100))) for a in assignments)
        assert len(set.intersection(*(set(a) for a in assignments))) == 8


def test_concurrent_joins_and_duplicate_submission_on_postgres(client):
    """Production locking must survive simultaneous requests from phones."""
    import os
    from concurrent.futures import ThreadPoolExecutor
    import pytest
    if not os.environ.get('TEST_DATABASE_URL', '').startswith('postgresql'):
        pytest.skip('Requires PostgreSQL row locks; set TEST_DATABASE_URL.')
    code, teacher = room(client)
    prefix = f'/api/rooms/{code}'
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda n: client.post(prefix+'/join', json={'nickname':f'Concurrent {n}'}), range(16)))
    assert all(r.status_code == 201 for r in responses)
    state = client.get(prefix+'/instructor', headers=teacher).json()
    assert [t['members'] for t in state['teams']] == [6, 5, 5]
    person = auth(next(r.json()['token'] for r in responses if r.status_code == 201))
    client.post(prefix+'/phase', headers=teacher, json={'phase':'annotation'})
    task = client.get(prefix+'/student', headers=person).json()['post']['assignment_id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        labels = list(pool.map(lambda _: client.post(prefix+'/labels', headers=person, json={'assignment_id':task,'label':'allow'}), range(2)))
    assert sorted(r.status_code for r in labels) == [200, 409]
    state = client.get(prefix+'/instructor', headers=teacher).json()
    assert sum(t['annotations'] for t in state['teams']) == 1
