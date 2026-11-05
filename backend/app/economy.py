"""Fictional accounting rules, unrelated to measured server resource use."""
from collections import Counter, defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select

from .content import POSTS
from .learning import CONFIGURATIONS, fingerprint, readiness
from .models import Assignment, AuditDecision, Participant, Purchase, RoomRules, TeamAccount, TrainingRun


class EconomySettings(BaseModel):
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
    electricity_used = sum(r.electricity for r in runs)
    electricity_remaining = max(0, rules['electricity_limit'] - electricity_used)
    next_electricity = rules['electricity_per_run'] * CONFIGURATIONS[account.configuration]['multiplier']
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
        'team': team, 'balance': account.balance, 'starting_budget': rules['starting_budget'],
        'spent': rules['starting_budget'] - account.balance, 'configuration': account.configuration,
        'configurations': [{'id': key, 'name': CONFIGURATIONS[key]['name']} for key in available_configurations(account)],
        'runs_remaining': 1 + 2 * account.compute_packs - len(runs), 'runs_used': len(runs),
        'usable_posts': len(rows), 'tied_posts_excluded': tied,
        'class_counts': {label: sum(row['label'] == label for row in rows) for label in ('allow','remove')},
        'training_problem': readiness(rows),
        'resource_problem': 'Not enough illustrative electricity remains for this configuration. Choose a lighter option.' if next_electricity > electricity_remaining + 1e-9 else None,
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
        'history': [run_summary(r, include_results=False) | {'accuracy': r.evaluation['accuracy'] if include_results else None} for r in runs],
    }


def run_summary(run, include_results):
    result = {'id': run.id, 'configuration': run.configuration, 'training_ms': round(run.training_ms, 3),
              'training_posts': len(run.snapshot['rows']), 'class_counts': run.snapshot['class_counts']}
    if include_results:
        result['evaluation'] = run.evaluation
    return result
