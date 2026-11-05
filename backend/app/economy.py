"""Fictional accounting rules, unrelated to measured server resource use."""
from collections import Counter, defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select

from .content import POSTS
from .learning import CONFIGURATIONS, fingerprint, readiness
from .models import Assignment, AuditDecision, Participant, Purchase, RoomRules, TeamAccount, TrainingRun, ClassroomDecision


class EconomySettings(BaseModel):
    classroom: bool = False
    worker_payment: int = Field(default=20, ge=1, le=20)
    local_water_limit: float = Field(default=12, ge=0, le=100000, allow_inf_nan=False)
    starting_budget: int = Field(default=100, ge=20, le=10000)
    annotation_cost: int = Field(default=25, ge=1, le=10000)
    audit_cost: int = Field(default=20, ge=1, le=10000)
    compute_cost: int = Field(default=25, ge=1, le=10000)
    infrastructure_cost: int = Field(default=50, ge=1, le=10000)
    electricity_limit: float = Field(default=12, ge=0, le=100000, allow_inf_nan=False)
    electricity_per_run: float = Field(default=2, ge=0, le=10000, allow_inf_nan=False)
    water_per_kwh: float = Field(default=3, ge=0, le=10000, allow_inf_nan=False)
    labor_credits_per_hour: float = Field(default=12, ge=0, le=10000, allow_inf_nan=False)


CATALOG = {
    'annotation': {'title': 'Additional annotation', 'description': 'Unlock 10 new posts, shared across your annotators. More data can introduce new biases. Up to 4 packs.', 'cost_key': 'annotation_cost'},
    'audit': {'title': 'Dataset auditing', 'description': 'Review disputed posts and agree on a team label. Preserves the original votes. Buy once.', 'cost_key': 'audit_cost'},
    'compute': {'title': 'Computing investment', 'description': 'Add 2 training runs and unlock word-pair features. Does not replenish illustrative electricity. Different features may help or hurt.', 'cost_key': 'compute_cost'},
    'infrastructure': {'title': 'Infrastructure upgrade', 'description': 'Unlock character-fragment features. Uses 3× the illustrative electricity per run. No extra training runs. Buy once.', 'cost_key': 'infrastructure_cost'},
}


def ensure_economy(db, room, settings=None):
    """Caller holds the room lock, including when initializing old rooms."""
    rules = db.get(RoomRules, room.code)
    if rules is None:
        rules = RoomRules(room_code=room.code, settings=(settings or EconomySettings()).model_dump())
        db.add(rules)
        db.flush()
    defaults = EconomySettings.model_validate(rules.settings).model_dump()
    if rules.settings != defaults:
        rules.settings = defaults
    for team in range(3):
        if db.get(TeamAccount, (room.code, team)) is None:
            db.add(TeamAccount(room_code=room.code, team=team, balance=rules.settings['starting_budget']))
    db.flush()
    return rules.settings


def team_data(db, code, team):
    tasks = list(db.scalars(select(Assignment).join(Participant).where(Participant.room_code == code, Participant.team == team)))
    audits = list(db.scalars(select(AuditDecision).where(AuditDecision.room_code == code, AuditDecision.team == team)))
    decisions = {a.post_id: a for a in audits}
    votes = defaultdict(list)
    for task in tasks:
        if task.label is not None:
            votes[task.post_id].append(task.label)
    rows, disputed, tied = [], [], 0
    for post, labels in sorted(votes.items()):
        counts = Counter(labels)
        audit = decisions.get(post)
        resolved = audit.label if audit else None
        if len(counts) > 1:
            disputed.append({'post_id': post, 'text': POSTS[post], 'allow': counts['allow'], 'remove': counts['remove'],
                             'label': resolved, 'opened': audit is not None})
        if resolved:
            label = resolved
        elif counts['allow'] == counts['remove']:
            tied += 1
            continue
        else:
            label = counts.most_common(1)[0][0]
        rows.append({'post_id': post, 'label': label})
    return rows, disputed, tied, tasks, audits


def available_configurations(account):
    return ['word', 'word_unweighted'] + (['bigram'] if account.compute_packs else []) + (['character'] if account.upgraded else [])


def team_state(db, code, team, rules, include_results=False):
    account = db.get(TeamAccount, (code, team))
    rows, disputes, tied, tasks, audits = team_data(db, code, team)
    runs = list(db.scalars(select(TrainingRun).where(TrainingRun.room_code == code, TrainingRun.team == team).order_by(TrainingRun.id)))
    purchases = list(db.scalars(select(Purchase).where(Purchase.room_code == code, Purchase.team == team).order_by(Purchase.id)))
    buyers = {p.id:p.nickname for p in db.scalars(select(Participant).where(Participant.room_code == code))} if purchases else {}
    latest = runs[-1] if runs else None
    decision = classroom_decision(db, code, team) if rules['classroom'] else None
    people = {p.id: p.nickname for p in db.scalars(select(Participant).where(Participant.room_code == code, Participant.team == team))}
    profiles = [dict(profile=profile, **charges(rules, account.configuration, profile)) for profile in ('air', 'evaporative')] if decision else []
    water_remaining = max(0, rules['local_water_limit'] - sum(r.water for r in runs))
    electricity_used = sum(r.electricity for r in runs)
    electricity_remaining = max(0, rules['electricity_limit'] - electricity_used)
    next_cost = charges(rules, account.configuration, decision.profile if decision else 'legacy')
    next_electricity = next_cost['electricity']
    feasible = [(charges(rules, c, p)['electricity'], c, p) for c in available_configurations(account) for p in (('air', 'evaporative') if decision else ('legacy',)) if charges(rules, c, p)['electricity'] <= electricity_remaining + 1e-9 and (not decision or charges(rules, c, p)['water'] <= water_remaining + 1e-9)]
    labor_seconds = sum(t.duration_ms or 0 for t in tasks) / 1000
    audit_seconds = sum(a.duration_ms or 0 for a in audits) / 1000
    options = []
    for action, spec in CATALOG.items():
        reason = None
        if action == 'annotation' and account.annotation_packs >= 4:
            reason = 'All 40 expansion posts have been unlocked.'
        if action == 'audit' and account.audit_enabled:
            reason = 'Auditing is already unlocked.'
        if action == 'infrastructure' and account.upgraded:
            reason = 'Infrastructure is already upgraded.'
        cost = rules[spec['cost_key']]
        if not reason and account.balance < cost:
            reason = 'Not enough shared credits.'
        options.append({'action': action, 'title': spec['title'], 'description': spec['description'], 'cost': cost, 'unavailable': reason})
    return {
        'classroom': rules['classroom'],
        'worker': None if decision is None else {'representative_id': decision.representative_id, 'representative': people.get(decision.representative_id), 'actor': people.get(decision.actor_id), 'choice': decision.choice, 'credits': decision.worker_credits, 'payment': rules['worker_payment'], 'recipient': 'Team worker collective; fictional shift compensation, not personal pay'},
        'decision_problem': 'Next: worker representative must choose shift compensation before procurement or training.' if decision and not decision.choice else None,
        'profile': decision.profile if decision else 'legacy', 'profiles': profiles,
        'water_remaining': water_remaining, 'water_limit': rules['local_water_limit'],
        'shortfalls': {'posts': max(0, 6-len(rows)), **{label:max(0, 2-sum(r['label']==label for r in rows)) for label in ('allow','remove')}},
        'cheapest_feasible': None if not feasible else dict(zip(('electricity','configuration','profile'), min(feasible))),
        'team': team, 'balance': account.balance, 'starting_budget': rules['starting_budget'],
        'spent': rules['starting_budget'] - account.balance, 'configuration': account.configuration,
        'configurations': [{'id': key, 'name': CONFIGURATIONS[key]['name']} for key in available_configurations(account)],
        'runs_remaining': 1 + 2 * account.compute_packs - len(runs), 'runs_used': len(runs),
        'usable_posts': len(rows), 'tied_posts_excluded': tied,
        'class_counts': {label: sum(row['label'] == label for row in rows) for label in ('allow','remove')},
        'training_problem': readiness(rows),
        'resource_problem': 'Not enough illustrative electricity remains for this configuration. Choose a lighter option.' if next_electricity > electricity_remaining + 1e-9 else 'Not enough local cooling water remains for this profile.' if decision and next_cost['water'] > water_remaining + 1e-9 else None,
        'electricity_limit': rules['electricity_limit'], 'electricity_remaining': electricity_remaining, 'next_run_electricity': next_electricity, 'audit_enabled': account.audit_enabled,
        'disputes': disputes if account.audit_enabled else [],
        'unresolved_disagreements': sum(d['label'] is None for d in disputes),
        'catalog': options,
        'purchases': [{'action': p.action, 'title': CATALOG[p.action]['title'], 'cost': p.cost, 'buyer': buyers.get(p.actor_id, 'Teammate')} for p in purchases],
        'resources': {'training_ms': round(sum(r.training_ms for r in runs), 3),
                      'illustrative_electricity_kwh': sum(r.electricity for r in runs),
                      'illustrative_water_liters': sum(r.water for r in runs),
                      'illustrative_hardware_units': 2 if account.upgraded else 1,
                      'annotation_seconds': labor_seconds, 'audit_seconds': audit_seconds,
                      'illustrative_unpaid_labor_credits': round((labor_seconds + audit_seconds)/3600*rules['labor_credits_per_hour'], 2)},
        'model': None if latest is None else run_summary(latest, include_results) | {'stale': latest.fingerprint != fingerprint(rows, account.configuration)},
        'history': [run_summary(r, include_results=False) | {'stale': r.fingerprint != fingerprint(rows, account.configuration), 'accuracy': r.evaluation['accuracy'] if include_results else None} for r in runs],
    }


def run_summary(run, include_results):
    result = {'id': run.id, 'configuration': run.configuration, 'training_ms': round(run.training_ms, 3),
              'training_posts': len(run.snapshot['rows']), 'class_counts': run.snapshot['class_counts'], 'site': run.snapshot.get('site', 'Legacy facility'), 'hardware': run.snapshot.get('hardware', 'Legacy hardware capacity'), 'electricity': run.electricity, 'water': run.water, 'contributors': run.snapshot.get('contributors', []), 'lifecycle': run.snapshot.get('lifecycle', 'Lifecycle obligations were not recorded for this legacy run.')}
    if include_results:
        result['evaluation'] = run.evaluation
    return result


def classroom_decision(db, code, team):
    decision = db.get(ClassroomDecision, (code, team))
    if decision is None:
        decision = ClassroomDecision(room_code=code, team=team)
        db.add(decision)
        db.flush()
    representative = db.get(Participant, decision.representative_id) if decision.representative_id else None
    if representative is None or representative.room_code != code or representative.team != team:
        decision.representative_id = db.scalar(select(Participant.id).where(Participant.room_code == code, Participant.team == team).order_by(Participant.id).limit(1))
    return decision


def charges(rules, configuration, profile):
    base = rules['electricity_per_run'] * CONFIGURATIONS[configuration]['multiplier']
    if rules['classroom']:
        return {'electricity': base * (2 if profile == 'air' else 1), 'water': base * (0.5 if profile == 'air' else 3)}
    return {'electricity': base, 'water': base * rules['water_per_kwh']}
