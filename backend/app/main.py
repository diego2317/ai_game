import asyncio
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from .content import POLICY, POSTS, REFERENCE, assigned_posts, team_posts
from .db import Base, engine, get_db
from .models import Assignment, Participant, Room, now, TeamAccount, TrainingRun, Purchase, AuditDecision
from .economy import EconomySettings, ensure_economy, team_state, team_data, available_configurations, CATALOG, classroom_decision, charges
from .learning import CONFIGURATIONS, fingerprint, fit_and_evaluate, readiness
from .experience import ensure_experience, timing, transition_clock, seed_demo_people, fill_demo_labels, reset_session, reveal_state

TEAMS = ['Copper Collective', 'Cobalt Systems', 'Verdant Labs']


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@asynccontextmanager
async def lifespan(app):
    if len(os.environ.get('INSTRUCTOR_SECRET', '')) < 8:
        raise RuntimeError('INSTRUCTOR_SECRET must have at least 8 characters.')
    for attempt in range(15):
        try:
            Base.metadata.create_all(engine)
            break
        except OperationalError:
            if attempt == 14:
                raise
            await asyncio.sleep(1)
    yield


app = FastAPI(title='The True Cost of AI', lifespan=lifespan)


@app.middleware('http')
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/') or request.url.path in ('/', '/instructor'):
        response.headers['Cache-Control'] = 'no-store'
    return response


class CreateRoom(BaseModel):
    secret: str = Field(max_length=200)
    economy: EconomySettings = Field(default_factory=EconomySettings)
    demo: bool = False


class JoinRoom(BaseModel):
    nickname: str = Field(min_length=1, max_length=24, pattern=r'^[\w .-]+$')


class RoomMutation(BaseModel):
    generation: int = Field(default=0, ge=0)


def require_generation(db, room, generation):
    if ensure_experience(db, room).generation != generation:
        raise HTTPException(409, 'This room was reset. Refresh before submitting a new decision.')


class PhaseChange(RoomMutation):
    omit_untrained: bool = False
    phase: Literal['annotation', 'paused', 'complete', 'training', 'testing', 'reveal']


class MoveTeam(RoomMutation):
    team: int = Field(ge=0, le=2)


class Label(RoomMutation):
    assignment_id: int
    label: Literal['allow', 'remove']


def token(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Session required. Please rejoin.')
    return digest(authorization[7:])


def get_room(code: str, db: Session, lock=False):
    stmt = select(Room).where(Room.code == code.upper())
    room = db.scalar(stmt.with_for_update() if lock else stmt)
    if not room:
        raise HTTPException(404, 'Room not found. Check the six-character code.')
    return room


def instructor(code, db, credential, lock=False):
    room = get_room(code, db, lock)
    if not secrets.compare_digest(room.instructor_hash, credential):
        raise HTTPException(403, 'Instructor session required.')
    return room


def student(code, db, credential):
    person = db.scalar(select(Participant).where(Participant.room_code == code.upper(), Participant.token_hash == credential))
    if not person:
        raise HTTPException(403, 'Student session not found. Please rejoin.')
    return person


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@app.get('/api/health')
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {'status': 'ok', 'milestone': 5}


@app.post('/api/rooms', status_code=201)
def create_room(body: CreateRoom, db: Session = Depends(get_db)):
    configured = os.environ.get('INSTRUCTOR_SECRET', '')
    if len(configured) < 8 or not secrets.compare_digest(digest(body.secret), digest(configured)):
        raise HTTPException(403, 'Incorrect instructor access key.')
    key = secrets.token_urlsafe(32)
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    for _ in range(10):
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        if db.get(Room, code) is None:
            break
    else:
        raise HTTPException(503, 'Could not allocate a room code. Try again.')
    room = Room(code=code, instructor_hash=digest(key))
    db.add(room)
    db.flush()
    ensure_economy(db, room, body.economy)
    meta = ensure_experience(db, room)
    meta.demo = body.demo
    if body.demo:
        seed_demo_people(db, room)
    db.commit()
    return {'code': code, 'token': key}


@app.post('/api/rooms/{code}/join', status_code=201)
def join(code: str, body: JoinRoom, db: Session = Depends(get_db)):
    room = get_room(code, db, lock=True)
    if ensure_experience(db, room).demo:
        raise HTTPException(409, 'This is a demonstration room with simulated participants. Use a live room to join.')
    if room.phase not in ('lobby', 'annotation', 'paused'):
        raise HTTPException(409, 'This annotation session has ended.')
    people = list(db.scalars(select(Participant).where(Participant.room_code == room.code)))
    name = body.nickname.strip()
    if not name:
        raise HTTPException(422, 'Enter a nickname.')
    if any(p.nickname.casefold() == name.casefold() for p in people):
        raise HTTPException(409, 'That nickname is already in use. Choose another.')
    team = min(range(3), key=lambda t: sum(p.team == t for p in people))
    seat = sum(p.team == team for p in people)
    key = secrets.token_urlsafe(32)
    person = Participant(room_code=room.code, nickname=name, team=team, token_hash=digest(key))
    db.add(person)
    db.flush()
    for index, post in enumerate(assigned_posts(team, seat)):
        db.add(Assignment(participant_id=person.id, post_id=post, position=index))
    db.commit()
    return {'token': key, 'code': room.code}


@app.get('/api/rooms/{code}/student')
def student_state(code: str, credential=Depends(token), db: Session = Depends(get_db)):
    room = get_room(code, db, lock=True)
    person = student(code, db, credential)
    meta = ensure_experience(db, room)
    person.last_seen = now()
    tasks = list(db.scalars(select(Assignment).where(Assignment.participant_id == person.id).order_by(Assignment.position)))
    pending = next((a for a in tasks if a.label is None), None)
    post = None
    rules = ensure_economy(db, room)
    economy = team_state(db, room.code, person.team, rules, room.phase in ('testing', 'reveal'))
    if economy['worker']:
        economy['worker']['can_decide'] = economy['worker']['representative_id'] == person.id
    comparison = comparison_state(db, room.code, rules) if room.phase in ('testing', 'reveal') else None
    if pending and room.phase in ('annotation', 'training'):
        if pending.issued_at is None:
            pending.issued_at = now()
        post = {'assignment_id': pending.id, 'text': POSTS[pending.post_id]}
    reveal = reveal_state(db, room, meta, rules, TEAMS) if room.phase == 'reveal' else None
    clock = timing(meta, room.phase, rules['classroom'])
    db.commit()
    return {'code': room.code, 'phase': room.phase, 'demo':meta.demo, 'generation':meta.generation, 'timing':clock, 'reveal':reveal, 'nickname': person.nickname,
            'team': person.team, 'team_name': TEAMS[person.team], 'policy': POLICY,
            'completed': sum(a.label is not None for a in tasks), 'total': len(tasks), 'post': post,
            'economy': economy, 'comparison': comparison}


@app.post('/api/rooms/{code}/labels')
def submit_label(code: str, body: Label, credential=Depends(token), db: Session = Depends(get_db)):
    room = get_room(code, db, lock=True)
    person = student(code, db, credential)
    require_generation(db, room, body.generation)
    if room.phase not in ('annotation', 'training'):
        raise HTTPException(409, 'Annotation is paused or closed. Your label was not submitted.')
    task = db.scalar(select(Assignment).where(Assignment.id == body.assignment_id, Assignment.participant_id == person.id).with_for_update())
    if not task or task.issued_at is None:
        raise HTTPException(409, 'Open an assigned post before labeling it.')
    if task.label is not None:
        raise HTTPException(409, 'This post has already been submitted.')
    task.label = body.label
    task.duration_ms = min(1_800_000, max(0, int((now() - utc(task.issued_at)).total_seconds() * 1000)))
    person.last_seen = now()
    db.commit()
    return {'saved': True}


@app.get('/api/rooms/{code}/instructor')
def instructor_state(code: str, credential=Depends(token), db: Session = Depends(get_db)):
    room = instructor(code, db, credential, lock=True)
    rules = ensure_economy(db, room)
    meta = ensure_experience(db, room)
    people = list(db.scalars(select(Participant).where(Participant.room_code == room.code).order_by(Participant.id)))
    assignments = list(db.scalars(select(Assignment).join(Participant).where(Participant.room_code == room.code)))
    teams = []
    for t, name in enumerate(TEAMS):
        ids = {p.id for p in people if p.team == t}
        tasks = [a for a in assignments if a.participant_id in ids]
        labels = [a for a in tasks if a.label is not None]
        votes = {}
        for a in labels:
            votes.setdefault(a.post_id, set()).add(a.label)
        elapsed = sum(a.duration_ms or 0 for a in labels)
        teams.append({'id': t, 'name': name, 'members': len(ids), 'annotations': len(labels),
                      'assigned': len(tasks), 'unique_posts': len(votes),
                      'disagreements': sum(len(v) > 1 for v in votes.values()),
                      'allow': sum(a.label == 'allow' for a in labels),
                      'remove': sum(a.label == 'remove' for a in labels),
                      'labor_seconds': round(elapsed / 1000, 1),
                      'seconds_per_label': round(elapsed / 1000 / len(labels), 1) if labels else None})
    for t in teams:
        t['economy'] = team_state(db, room.code, t['id'], rules, room.phase in ('testing', 'reveal'))
        if t['economy']['worker']:
            t['economy']['worker']['can_decide'] = meta.demo
    comparison = comparison_state(db, room.code, rules) if room.phase in ('testing', 'reveal') else None
    reveal = reveal_state(db, room, meta, rules, TEAMS) if room.phase == 'reveal' else None
    clock = timing(meta, room.phase, rules['classroom'])
    db.commit()
    return {'code': room.code, 'phase': room.phase, 'demo':meta.demo, 'generation':meta.generation, 'timing':clock, 'reveal':reveal, 'teams': teams, 'policy': POLICY, 'economy_rules': rules, 'comparison': comparison,
            'participants': [{'id': p.id, 'nickname': p.nickname, 'team': p.team,
                              'simulated': meta.demo, 'online': not meta.demo and (now() - utc(p.last_seen)).total_seconds() < 15} for p in people]}


@app.post('/api/rooms/{code}/phase')
def change_phase(code: str, body: PhaseChange, credential=Depends(token), db: Session = Depends(get_db)):
    room = instructor(code, db, credential, lock=True)
    require_generation(db, room, body.generation)
    transitions = {'lobby': {'annotation'}, 'annotation': {'paused', 'complete', 'training'},
                   'paused': {'annotation', 'complete', 'training'}, 'complete': {'training'},
                   'training': {'testing'}, 'testing': {'training', 'reveal'}, 'reveal': {'testing'}}
    if body.phase not in transitions[room.phase]:
        raise HTTPException(409, 'That phase transition is not available.')
    if body.phase == 'testing' and not body.omit_untrained:
        trained = {r.team for r in db.scalars(select(TrainingRun).where(TrainingRun.room_code == room.code))}
        if len(trained) < 3:
            raise HTTPException(409, 'Comparison omits untrained teams. Instructor must explicitly override.')
    meta = ensure_experience(db, room)
    transition_clock(meta, room.phase, body.phase)
    room.phase = body.phase
    if body.phase in ('paused', 'complete', 'training', 'testing', 'reveal'):
        ids = select(Participant.id).where(Participant.room_code == room.code)
        db.execute(update(Assignment).where(Assignment.participant_id.in_(ids), Assignment.label.is_(None)).values(issued_at=None))
    db.commit()
    return {'phase': room.phase}


@app.post('/api/rooms/{code}/participants/{person_id}/team')
def move_team(code: str, person_id: int, body: MoveTeam, credential=Depends(token), db: Session = Depends(get_db)):
    room = instructor(code, db, credential, lock=True)
    require_generation(db, room, body.generation)
    if ensure_experience(db, room).demo:
        raise HTTPException(409, 'Demonstration teams use fixed scripted participants.')
    if room.phase != 'lobby':
        raise HTTPException(409, 'Teams can only change before annotation starts.')
    person = db.get(Participant, person_id)
    if not person or person.room_code != room.code:
        raise HTTPException(404, 'Student not found.')
    if person.team == body.team:
        return {'saved': True}
    person.team = body.team
    # Rebuild all lobby assignments so each team keeps distinct seats after moves.
    people = list(db.scalars(select(Participant).where(Participant.room_code == room.code).order_by(Participant.id)))
    for team in range(3):
        for seat, member in enumerate(p for p in people if p.team == team):
            for task in db.scalars(select(Assignment).where(Assignment.participant_id == member.id)):
                db.delete(task)
            db.flush()
            for index, post in enumerate(assigned_posts(team, seat)):
                db.add(Assignment(participant_id=member.id, post_id=post, position=index))
    db.commit()
    return {'saved': True}




class PurchaseRequest(RoomMutation):
    action: Literal['annotation', 'audit', 'compute', 'infrastructure']
    request_id: str = Field(min_length=8, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')


class ConfigurationRequest(RoomMutation):
    configuration: Literal['word', 'word_unweighted', 'bigram', 'character']


class TrainRequest(RoomMutation):
    request_id: str = Field(min_length=8, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')


class AuditRequest(RoomMutation):
    post_id: int = Field(ge=0, lt=100)
    label: Literal['allow', 'remove'] | None = None


def team_access(code, team, db, credential, allow_instructor=False, generation=0):
    room = get_room(code, db, lock=True)
    if team not in range(3):
        raise HTTPException(404, 'Team not found.')
    if allow_instructor and secrets.compare_digest(room.instructor_hash, credential):
        person = None
    else:
        person = student(code, db, credential)
        if person.team != team:
            raise HTTPException(403, 'You can only act for your own team.')
    require_generation(db, room, generation)
    if room.phase != 'training':
        raise HTTPException(409, 'These decisions are available during the Training phase only.')
    rules = ensure_economy(db, room)
    return room, person, db.get(TeamAccount, (room.code, team)), rules


def spending_actor(db, room, team, person):
    if person is not None:
        return person
    if not ensure_experience(db, room).demo:
        raise HTTPException(403, 'Team purchases and audit decisions require a student session in live rooms.')
    return db.scalar(select(Participant).where(Participant.room_code == room.code, Participant.team == team).order_by(Participant.id))


@app.post('/api/rooms/{code}/teams/{team}/purchase')
def purchase(code: str, team: int, body: PurchaseRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room, person, account, rules = team_access(code, team, db, credential, allow_instructor=True, generation=body.generation)
    person = spending_actor(db, room, team, person)
    previous = db.scalar(select(Purchase).where(Purchase.room_code == room.code, Purchase.team == team, Purchase.request_id == body.request_id))
    if previous:
        if previous.action != body.action:
            raise HTTPException(409, 'This request identifier was already used for another purchase.')
        return {'saved': True, 'duplicate': True}
    if rules['classroom'] and not classroom_decision(db, room.code, team).choice:
        raise HTTPException(409, 'Worker compensation decision is pending.')
    cost = rules[CATALOG[body.action]['cost_key']]
    if account.balance < cost:
        raise HTTPException(409, 'Not enough shared credits.')
    if body.action == 'audit':
        if account.audit_enabled:
            raise HTTPException(409, 'Auditing is already unlocked.')
        account.audit_enabled = True
    elif body.action == 'infrastructure':
        if account.upgraded:
            raise HTTPException(409, 'Infrastructure is already upgraded.')
        account.upgraded = True
    elif body.action == 'compute':
        account.compute_packs += 1
    else:
        if account.annotation_packs >= 4:
            raise HTTPException(409, 'All expansion posts have been unlocked.')
        people = list(db.scalars(select(Participant).where(Participant.room_code == room.code, Participant.team == team).order_by(Participant.id)))
        candidates = [post for post in range(100) if post not in team_posts(team)]
        posts = candidates[account.annotation_packs*10:(account.annotation_packs+1)*10]
        for index, post in enumerate(posts):
            owner = people[index % len(people)]
            last = db.scalar(select(Assignment.position).where(Assignment.participant_id == owner.id).order_by(Assignment.position.desc()).limit(1))
            db.add(Assignment(participant_id=owner.id, post_id=post, position=(last or 0)+1))
            db.flush()
        account.annotation_packs += 1
    account.balance -= cost
    db.add(Purchase(room_code=room.code, team=team, actor_id=person.id, action=body.action, cost=cost, request_id=body.request_id))
    db.commit()
    return {'saved': True, 'balance': account.balance}


@app.post('/api/rooms/{code}/teams/{team}/configuration')
def configuration(code: str, team: int, body: ConfigurationRequest, credential=Depends(token), db: Session = Depends(get_db)):
    _, _, account, _ = team_access(code, team, db, credential, allow_instructor=True, generation=body.generation)
    if body.configuration not in available_configurations(account):
        raise HTTPException(409, 'Purchase the required computing or infrastructure access first.')
    account.configuration = body.configuration
    db.commit()
    return {'saved': True}


@app.post('/api/rooms/{code}/teams/{team}/audit')
def audit(code: str, team: int, body: AuditRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room, person, account, _ = team_access(code, team, db, credential, allow_instructor=True, generation=body.generation)
    person = spending_actor(db, room, team, person)
    if not account.audit_enabled:
        raise HTTPException(403, 'Unlock dataset auditing first.')
    _, disputes, _, _, _ = team_data(db, room.code, team)
    if body.post_id not in {d['post_id'] for d in disputes}:
        raise HTTPException(409, 'Only posts with conflicting student labels can be audited.')
    decision = db.scalar(select(AuditDecision).where(AuditDecision.room_code == room.code, AuditDecision.team == team, AuditDecision.post_id == body.post_id))
    if decision and decision.label is not None:
        raise HTTPException(409, 'This post already has a final team decision.')
    if body.label is None:
        if decision is None:
            db.add(AuditDecision(room_code=room.code, team=team, post_id=body.post_id, actor_id=person.id))
    else:
        if decision is None:
            raise HTTPException(409, 'Open the review before submitting a team decision.')
        decision.label = body.label
        decision.actor_id = person.id
        decision.duration_ms = min(1_800_000, max(0, int((now()-utc(decision.started_at)).total_seconds()*1000)))
    db.commit()
    return {'saved': True}


@app.post('/api/rooms/{code}/teams/{team}/train')
def train(code: str, team: int, body: TrainRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room, _, account, rules = team_access(code, team, db, credential, allow_instructor=True, generation=body.generation)
    previous = db.scalar(select(TrainingRun).where(TrainingRun.room_code == room.code, TrainingRun.team == team, TrainingRun.request_id == body.request_id))
    if previous:
        return {'saved': True, 'run_id': previous.id, 'duplicate': True}
    decision = classroom_decision(db, room.code, team) if rules['classroom'] else None
    if decision and not decision.choice:
        raise HTTPException(409, 'Worker compensation decision is pending.')
    rows, _, tied, tasks, _ = team_data(db, room.code, team)
    problem = readiness(rows)
    if problem:
        raise HTTPException(409, problem)
    runs = list(db.scalars(select(TrainingRun).where(TrainingRun.room_code == room.code, TrainingRun.team == team)))
    if len(runs) >= 1 + 2*account.compute_packs:
        raise HTTPException(409, 'No training runs remain. Invest in computing to unlock two more.')
    signature = fingerprint(rows, account.configuration)
    if any(r.fingerprint == signature for r in runs):
        raise HTTPException(409, 'These labels and this configuration have already been trained. Change data or configuration before spending a run.')
    cost = charges(rules, account.configuration, decision.profile if decision else 'legacy')
    electricity = cost['electricity']
    if decision and sum(r.water for r in runs) + cost['water'] > rules['local_water_limit'] + 1e-9:
        raise HTTPException(409, 'Not enough local cooling water remains for this profile.')
    if sum(r.electricity for r in runs) + electricity > rules['electricity_limit'] + 1e-9:
        raise HTTPException(409, 'Not enough illustrative electricity remains for this configuration. Choose a lighter option.')
    training_ms, evaluation, artifact = fit_and_evaluate(rows, account.configuration)
    run = TrainingRun(room_code=room.code, team=team, request_id=body.request_id, fingerprint=signature,
                      configuration=account.configuration, training_ms=training_ms, electricity=electricity,
                      water=cost['water'],
                      snapshot={'site': decision.profile if decision else 'Legacy facility', 'contributors': [p.nickname for p in db.scalars(select(Participant).where(Participant.room_code == room.code, Participant.team == team, Participant.id.in_({t.participant_id for t in tasks if t.label is not None})))], 'lifecycle': 'Company funds maintenance and safe retirement; local maintenance and recycling workers bear handling burdens.', 'hardware': '2 fictional capacity units' if account.upgraded else '1 fictional capacity unit', 'rows': rows, 'tied_posts_excluded': tied, 'class_counts': {label:sum(r['label']==label for r in rows) for label in ('allow','remove')}},
                      evaluation=evaluation, artifact=artifact)
    db.add(run)
    db.commit()
    return {'saved': True, 'run_id': run.id, 'training_ms': training_ms}


class WorkerRequest(TrainRequest):
    choice: Literal['paid', 'unbilled']


class RepresentativeRequest(RoomMutation):
    participant_id: int


class ProfileRequest(RoomMutation):
    profile: Literal['air', 'evaporative']


@app.post('/api/rooms/{code}/teams/{team}/representative')
def representative(code: str, team: int, body: RepresentativeRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room = instructor(code, db, credential, lock=True)
    require_generation(db, room, body.generation)
    if team not in range(3) or not ensure_economy(db, room)['classroom'] or room.phase not in ('lobby', 'annotation', 'paused', 'complete', 'training'):
        raise HTTPException(409, 'Representative changes are closed.')
    person = db.get(Participant, body.participant_id)
    if not person or person.room_code != room.code or person.team != team:
        raise HTTPException(403, 'Choose a worker from this team and room.')
    classroom_decision(db, room.code, team).representative_id = person.id
    db.commit()
    return {'saved': True}


@app.post('/api/rooms/{code}/teams/{team}/worker')
def compensate(code: str, team: int, body: WorkerRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room, person, account, rules = team_access(code, team, db, credential, allow_instructor=True, generation=body.generation)
    person = spending_actor(db, room, team, person)
    if not rules['classroom']:
        raise HTTPException(409, 'Classroom mode required.')
    decision = classroom_decision(db, room.code, team)
    if person.id != decision.representative_id:
        raise HTTPException(403, 'Only the designated worker representative can decide.')
    if decision.choice:
        if decision.request_id == body.request_id and decision.choice == body.choice:
            return {'saved': True, 'duplicate': True}
        raise HTTPException(409, 'The shift decision is already recorded.')
    amount = rules['worker_payment'] if body.choice == 'paid' else 0
    if account.balance < amount:
        raise HTTPException(409, 'Not enough company credits.')
    account.balance -= amount
    decision.choice, decision.actor_id, decision.request_id = body.choice, person.id, body.request_id
    decision.worker_credits = amount
    db.commit()
    return {'saved': True}


@app.post('/api/rooms/{code}/teams/{team}/profile')
def cooling_profile(code: str, team: int, body: ProfileRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room, _, _, rules = team_access(code, team, db, credential, allow_instructor=True, generation=body.generation)
    if not rules['classroom']:
        raise HTTPException(409, 'Classroom mode required.')
    classroom_decision(db, room.code, team).profile = body.profile
    db.commit()
    return {'saved': True}


def comparison_state(db, code, rules):
    teams = [{'id': team, 'name': name, 'economy': team_state(db, code, team, rules, include_results=True)} for team, name in enumerate(TEAMS)]
    posts = []
    for i, (reference, rationale) in enumerate(REFERENCE):
        predictions = []
        for team in teams:
            model = team['economy']['model']
            if model:
                prediction = model['evaluation']['predictions'][i]
                predictions.append({'team': team['id'], **prediction})
        posts.append({'post_id': 100+i, 'text': POSTS[100+i], 'reference': reference, 'rationale': rationale,
                      'predictions': predictions, 'disagreement': len({p['prediction'] for p in predictions}) > 1})
    return {'teams': teams, 'posts': posts,
            'note': 'Reference labels apply Common Ground policy v1; they are a curated standard, not universal moral truth. These 20 examples were excluded from all annotation queues. Repeated testing can guide choices toward this small test set, so later scores are exploratory rather than independent evidence.'}


class ResetRequest(BaseModel):
    confirmation: str = Field(max_length=6)
    generation: int = Field(ge=0)
    request_id: str = Field(min_length=8, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')


@app.post('/api/rooms/{code}/reset')
def reset_room(code: str, body: ResetRequest, credential=Depends(token), db: Session = Depends(get_db)):
    room = instructor(code, db, credential, lock=True)
    meta = ensure_experience(db, room)
    if body.confirmation != room.code:
        raise HTTPException(422, 'Type the room code exactly to confirm reset.')
    if meta.last_reset_id == body.request_id:
        return {'saved':True, 'duplicate':True, 'generation':meta.generation}
    if body.generation != meta.generation:
        raise HTTPException(409, 'This room has already been reset. Refresh before starting another reset.')
    reset_session(db, room, meta, body.request_id)
    db.commit()
    return {'saved':True, 'generation':meta.generation}


@app.post('/api/rooms/{code}/demo/annotate')
def demo_annotate(code: str, body: RoomMutation, credential=Depends(token), db: Session = Depends(get_db)):
    room = instructor(code, db, credential, lock=True)
    require_generation(db, room, body.generation)
    if not ensure_experience(db, room).demo:
        raise HTTPException(409, 'Simulated labels are restricted to demonstration rooms.')
    if room.phase not in ('annotation', 'training'):
        raise HTTPException(409, 'Open Annotation or Training before simulating more labels.')
    count = fill_demo_labels(db, room)
    db.commit()
    return {'saved':True, 'simulated_annotations':count}


# One production origin; Vite proxies /api during local development.
static = Path(os.environ.get('STATIC_DIR', Path(__file__).resolve().parents[2] / 'frontend' / 'dist'))
if static.is_dir():
    app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')

    @app.get('/')
    @app.get('/instructor')
    def index():
        return FileResponse(static / 'index.html')
