"""Classroom timing, explicit demonstration data, and reveal accounting."""
import hashlib
import secrets
from datetime import timezone

from sqlalchemy import delete, select

from .content import assigned_posts
from .economy import ensure_economy, team_state
from .models import Assignment, AuditDecision, Participant, Purchase, RoomExperience, TeamAccount, TrainingRun, ClassroomDecision, now

DURATIONS = {'annotation': 300, 'paused': 300, 'training': 240, 'testing': 300, 'reveal': 300}

# Original scripted training decisions, never taken from held-out reference data.
# These are illustrative annotator choices, NOT an answer key for the training set.
DEMO_REMOVE = {6,7,8,9,10,11,16,19,24,27,29,32,35,37,39,42,47,49,52,55,57,61,62,67,69,73,76,78,81,83,84,90,95,98}
DEMO_AMBIGUOUS = {4,5,15,18,23,43,58,59,66,82,88,92}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def ensure_experience(db, room):
    meta = db.get(RoomExperience, room.code)
    if meta is None:
        meta = RoomExperience(room_code=room.code)
        db.add(meta)
        db.flush()
    return meta


def timing(meta, phase, classroom=False):
    elapsed = meta.elapsed_before_pause
    if phase != 'paused':
        elapsed += max(0, (now() - utc(meta.phase_started_at)).total_seconds())
    return {'elapsed_seconds': round(elapsed, 1), 'recommended_seconds': ({**DURATIONS, 'training': 360, 'testing': 120} if classroom else DURATIONS).get(phase), 'paused': phase == 'paused'}


def transition_clock(meta, old_phase, new_phase):
    if old_phase == 'annotation' and new_phase == 'paused':
        meta.elapsed_before_pause += max(0, (now() - utc(meta.phase_started_at)).total_seconds())
    elif not (old_phase == 'paused' and new_phase == 'annotation'):
        meta.elapsed_before_pause = 0
    meta.phase_started_at = now()


def seed_demo_people(db, room):
    for seat in range(5):
        for team in range(3):
            token = secrets.token_urlsafe(32)
            person = Participant(room_code=room.code, nickname=f'Demo {team+1}.{seat+1}', team=team,
                                 token_hash=hashlib.sha256(token.encode()).hexdigest())
            db.add(person)
            db.flush()
            for position, post in enumerate(assigned_posts(team, seat)):
                db.add(Assignment(participant_id=person.id, post_id=post, position=position))
    db.flush()
    if not ensure_economy(db, room)['classroom']:
        fill_demo_labels(db, room)


def fill_demo_labels(db, room):
    people = list(db.scalars(select(Participant).where(Participant.room_code == room.code).order_by(Participant.id)))
    seats = {}
    for team in range(3):
        seats.update({person.id: seat for seat, person in enumerate(p for p in people if p.team == team)})
    by_id = {p.id:p for p in people}
    tasks = list(db.scalars(select(Assignment).where(Assignment.participant_id.in_(by_id), Assignment.label.is_(None))))
    rules = ensure_economy(db, room)
    from .economy import classroom_decision
    tasks = [t for t in tasks if not rules['classroom'] or classroom_decision(db, room.code, by_id[t.participant_id].team).choice]
    for task in tasks:
        person = by_id[task.participant_id]
        label = 'remove' if task.post_id in DEMO_REMOVE else 'allow'
        # Scripted differences illustrate interpretive choices without evaluating
        # those choices against the held-out reference labels.
        if person.team == 1 and task.post_id in {1,20,21,43,54,65,70,71,94}:
            label = 'remove'
        if task.post_id in DEMO_AMBIGUOUS and (seats[person.id]+person.team) % 2:
            label = 'remove' if label == 'allow' else 'allow'
        task.label = label
        task.duration_ms = (8 + (task.post_id + seats[person.id]) % 9) * 1000
    db.flush()
    return len(tasks)


def reset_session(db, room, meta, request_id):
    """Caller holds the room lock. Keep credentials, room code, and settings."""
    people = list(db.scalars(select(Participant).where(Participant.room_code == room.code).order_by(Participant.id)))
    for model in (TrainingRun, Purchase, AuditDecision, ClassroomDecision, TeamAccount):
        db.execute(delete(model).where(model.room_code == room.code))
    db.execute(delete(Assignment).where(Assignment.participant_id.in_([p.id for p in people])))
    for index, person in enumerate(people):
        person.team = index % 3
        seat = index // 3
        for position, post in enumerate(assigned_posts(person.team, seat)):
            db.add(Assignment(participant_id=person.id, post_id=post, position=position))
    room.phase = 'lobby'
    meta.generation += 1
    meta.last_reset_id = request_id
    meta.phase_started_at = now()
    meta.elapsed_before_pause = 0
    db.flush()
    ensure_economy(db, room)
    if meta.demo and not ensure_economy(db, room)['classroom']:
        fill_demo_labels(db, room)


def reveal_state(db, room, meta, rules, team_names):
    teams = []
    for team, name in enumerate(team_names):
        economy = team_state(db, room.code, team, rules, include_results=True)
        people = list(db.scalars(select(Participant).where(Participant.room_code == room.code, Participant.team == team)))
        tasks = list(db.scalars(select(Assignment).where(Assignment.participant_id.in_([p.id for p in people]))))
        labels = [a for a in tasks if a.label is not None]
        teams.append({'id':team, 'name':name, 'members':len(people), 'annotations':len(labels),
                      'seconds_per_label': round(sum(a.duration_ms or 0 for a in labels)/1000/len(labels), 1) if labels else None,
                      'economy':economy})
    return {'demo': meta.demo, 'teams': teams, 'rules':rules,
            'note': 'Demo annotation counts and annotation times are scripted. Shared review and training durations measure interface activity, not student labor.' if meta.demo else 'Annotation and shared review times are recorded elapsed interface time, including idle time; they do not measure all human attention.',
            'resource_note': 'Electricity, water, hardware units, and labor credits are illustrative game quantities, not real measurements or scientifically validated footprint estimates. Extraction, manufacturing, transport, and disposal are discussed qualitatively; this app does not measure them.'}
