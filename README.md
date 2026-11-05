# The True Cost of AI

A live classroom simulation with three teams and flexible attendance. Students supply the decisions that will become a content moderation model’s training data.

**Milestones 1–5 are implemented:** live rooms, annotation, real scikit-learn training, held-out evaluation, shared budgets, an interactive infrastructure reveal, a separate demonstration mode, safe room reset, and automated deployment checks. You can test live training with one student device, or demonstrate all three companies from the instructor interface without any student devices. Railway configuration is ready; a live Railway deployment still requires your project/account and variables.


## Focused 20-minute seminar (15 students, three teams of five)

New rooms created through the instructor interface default to focused classroom mode. Uncheck **Focused 20-minute classroom mode** to retain the advanced activity. API requests and existing rooms default explicitly to `classroom: false`; no existing labels, assignments, resource accounting or model artifacts are migrated. Settings normalize additively. A new `classroom_decisions` table holds each team's representative, one shift decision, matching worker credit ledger and cooling selection. Reset clears this ledger and restores the same room settings and student sessions.

Everyone annotates. The first team arrival is the default worker representative; the instructor's **Worker representative** selector can replace an absent student. Before anyone on the team labels data, the representative chooses **0, 10 or 20 fictional company credits for the worker collective**. Zero keeps the standard 18–19-post queue; 10 adds five posts per person; 20 adds ten. This is one company payment, not a per-person rate. Late joiners receive the same extra allocation. Extra queues draw from 50 new training posts (IDs 120–169); annotation purchases use unassigned candidates and never repeat a person’s posts. Standard queue sizes stay unchanged. This is collective shift compensation, never personal pay or a reward for speed, labels or accuracy. The company debit and matching worker ledger commit once under the room lock. Labeling, procurement and fitting wait for this decision. Existing rooms with a previously recorded payment keep their assignments. Demo worker actions are instructor-scripted through simulated representatives; labels and annotation times are scripted, while fitting and interface time are measured.

All facility assumptions below are invented classroom inputs, independent of measured training milliseconds. Defaults are 100 company credits, one fit, 12 fictional kWh electricity and 12 L local cooling water per team. For the same word fit, air cooling charges **4 kWh / 1 L** and evaporative cooling charges **2 kWh / 6 L**. Word pairs multiply both by 1.5 and character fragments by 3. Both profiles can run once initially. Three distinct word/word-pair fits cost 14 kWh / 3.5 L with air versus 7 kWh / 21 L with evaporative cooling: one exceeds electricity, the other water. Computing purchases add fit permits, never resource allowances. Cooling changes do not change the classifier fingerprint; an identical fit cannot be repeated by switching profiles. Failed and duplicate operations consume no additional budget, fit permit or resources.

Receipts retain the actual run's configuration, class counts, training rows, cooling profile, hardware and resource charges. Current submissions and usable rows are separate from model snapshots; changed labels/configuration mark saved results stale. Hardware maintenance and safe retirement are company obligations with local handling burdens on maintenance/recycling workers. Local residents bear cooling-water competition; utility workers and neighbors bear electricity demand. Upstream water, grid carbon intensity and ongoing serving remain omitted. No real emissions estimate or per-prediction footprint is implied.

Five-step rehearsal:

1. **0–2 min:** Create a focused room, join 15 students, verify five per team and identify the three representatives. Each team chooses its 0/10/20-credit annotation payment before labeling. Introduce Crawford & Joler's *Anatomy of an AI System* and Berreby's Yale Environment 360 reading.
2. **2–7 min:** Start annotation. Everyone follows the policy; six submissions can supply mixed training data. Late arrivals may join during the shift. Unfinished queues remain available during Training.
3. **7–13 min:** Begin Training. The pre-annotation payment is already recorded; teams check what remains for upgrades. Compare cooling charges and remaining caps, make a procurement and cooling decisions, then train. Use the host readiness summary to resolve shortfalls. Replace absent representatives as needed.
4. **13–15 min:** Compare models; explicitly confirm any omission of untrained teams. Detailed classification metrics are optional. Explain that subsequent comparisons reuse the exposed benchmark.
5. **15–20 min:** Reveal a stored prediction, its snapshot and supporting work, cooling profile and hardware. Compare worker compensation and cumulative resource ledgers. Ask “Who supplied the work and who controls the model?” and “What burden did your cooling choice shift, onto whom, and what would you need to measure?” Reset only after discussion.

## Run locally on Ubuntu

Requirements: Docker Engine with Compose v2. For frontend/backend development without containers: Python 3.13+, Node.js 22+, and PostgreSQL 17.

```bash
cp .env.example .env
# Edit .env: replace INSTRUCTOR_SECRET with a private random key, at least 8 characters.
# Generate a key with: openssl rand -hex 24

docker compose up --build
```

Open **http://localhost:8000/instructor**, enter the instructor key, and create a room. Students open **http://localhost:8000** and enter its six-character code and a nickname. Use separate browsers or tabs for separate people; a tab retains its session on refresh using sessionStorage. Closing the tab loses its session. No student accounts or passwords are needed.

For phones on the same Wi-Fi, open `http://YOUR_UBUNTU_LAN_IP:8000/instructor` on your computer **before** displaying the QR code. Alternatively, enter `http://YOUR_UBUNTU_LAN_IP:8000` in the instructor’s **Student-accessible URL** field. Run `hostname -I` in your Ubuntu terminal to find your Wi-Fi address (usually `192.168.x.x` or `10.x.x.x`; avoid Docker bridge addresses such as `172.17.x.x`). The QR code is disabled for localhost, which on a phone points to the phone. The address is saved in your browser; update it if you change networks. Campus networks may prevent device-to-device access; Railway provides a shared public origin.

The instructor key belongs only to the instructor. Do not put it into frontend environment variables, URLs, or the student join link. Room-specific bearer credentials are generated on creation, stored hashed in the database, and sent by the frontend in authorization headers. Use HTTPS for public deployment.

### Development with hot reload

```bash
# Terminal 1, repository root
cp .env.example .env # only if you have not already created it
# Edit the instructor key in .env.
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env

# Terminal 2
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173/instructor**. Vite proxies `/api` to FastAPI. If you already have PostgreSQL, set `DATABASE_URL` in `.env` instead of starting the Compose database. The app refuses to start without database configuration and a sufficiently long instructor key. Database tables are created on startup, with short retries if PostgreSQL is still starting. The milestone upgrades add tables without deleting existing rooms or labels; existing rooms receive metadata on first access.

## Verify Milestone 1

1. Create a room in an instructor tab. Copy the join link or scan its QR code.
2. Join from student tabs or phones with distinct nicknames. Each arrival automatically joins the smallest team; ties use team order. There is no required minimum attendance or fixed team capacity. Use the instructor’s per-student dropdowns to change teams before starting.
3. Check that students can read the shared policy while waiting. Start annotation. Each student gets a server-assigned queue and two large label buttons.
4. Submit labels; refresh a student tab to verify progress survives. There is no answer feedback. Each task can be submitted once, only by its assigned student.
5. In a team with at least two students, have them label the first shared post differently. The instructor’s disputed-post count should increase. Watch counts, label distributions, presence, and recorded task time update every two seconds.
6. Pause the shift; submissions stop. Resume to continue, or choose **Begin training**. **End annotation** closes the initial shift; you can still open Training afterward, including in rooms created before this update.
7. Toggle Presentation for larger team comparisons. Create a new room for another run; existing room records are retained.

Presence means a student polled in the last 15 seconds; it is not proof of active attention. Recorded task time is server elapsed time from issuing a post to receiving its label, capped at 30 minutes per task. It includes idle time and network delay. A pause discards unfinished task timing; completed task timing stays. These are interface timing observations, not a precise measure of cognitive labor or labor costs.

## Verify Milestone 2: real training (one device is enough)

1. Start a room and join on one student device or browser tab. No other team needs to join.
2. Start annotation and label at least **6 distinct posts**, including **2 Allow and 2 Remove**. Use the moderation policy rather than trying to manufacture a score. New and reset queues interleave clear Allow and Remove anchors in the first six cards; an interpretive example arrives by card eight. Existing active assignments keep their order. For a quick UI test you may deliberately use mixed labels, but the model will learn those choices.
3. Choose **Begin training** in the instructor interface. The student now sees a training desk and investment desk, and can continue their unfinished labeling queue. Labels are accepted during Annotation and Training; Testing freezes labels, purchases, configuration changes, and audit decisions.
4. Click **Train model** on the student device or **Train eligible teams** in the instructor interface. Unready teams are skipped individually with an explanation. Successful fits consume one included run; failed readiness checks consume none. Word features use TF-IDF and logistic regression. Class balancing is enabled by default; an observed-proportions alternative is available without a purchase.
5. Click **Compare models** as instructor. Both instructor and students see agreement with the curated reference, confusion matrices (rows = reference; columns = prediction), all 20 held-out predictions side by side, model disagreements, uncalibrated confidence scores, credits, and timing. The broader environmental/economic accounting is held for the reveal. Empty teams show **No trained model**. Filter to model differences or departures from the reference. Expand a reference label for its rationale.
6. Open **Model limits & run history** to compare earlier runs. A changed dataset/configuration marks the last model stale until retraining. Performance is always attached to the actual trained snapshot, not to later purchases.
7. Choose **Open improvement round** to return to Training; change data/configuration, buy runs if needed, retrain, and compare again. Repeated evaluation can guide choices toward this small test set. Later scores are exploratory, not a fresh independent assessment.

There are no reference answers in the annotation phase. During Testing, the held-out examples and their separately authored reference decisions are visible for discussion. They represent Common Ground policy v1, not universal moral truth. The reference data never enters the vectorizer’s fit or the classifier’s labels. No external LLM or AI API is used.

## Verify Milestone 3: resource decisions

Before creating a room, expand **Room budget & illustrative assumptions** to set its starting credits, purchase prices, and fictional resource coefficients. Defaults:

| Investment | Price | Actual gameplay effect |
|---|---:|---|
| Additional annotation | 25 | Adds 10 new posts split among present teammates, up to four packs. New posts come from training candidates outside the team’s initial pool. |
| Dataset auditing | 20 | Unlocks review of conflicting labels and final team adjudication. Buy once. |
| Computing investment | 25 | Adds 2 training runs and unlocks TF-IDF word pairs. Repeatable while credits remain. |
| Infrastructure upgrade | 50 | Unlocks TF-IDF character fragments. Buy once; grants no runs and uses 3× the fictional electricity per run. |

Each team starts with **100 shared credits, one included training run, and a fictional electricity allowance of 12 kWh**. The allowance is configurable before room creation. Successful training deducts its illustrative electricity from that limit; computing purchases add run permits without replenishing electricity. If the chosen configuration exceeds the remaining allowance, the server rejects it without consuming a run. This limit is a game rule, not the actual power available to the server. Buying all four investments would cost 120 credits, so the default budget forces tradeoffs. Any teammate can commit a purchase after confirmation; discuss first and designate one person to click. There is no voting requirement. The ledger records the purchasing participant and cost. The server chooses the price, checks room phase and team ownership, locks the room, and commits purchases atomically. Duplicate request identifiers cannot charge twice or consume two training runs. A repeat training run with unchanged aggregated labels and configuration is rejected.

To check auditing, join a second member of the same team (automatic assignment puts the fourth entrant back on team one, or move a student before starting). Give different labels on shared posts. Buy auditing, **Open review**, discuss, then **Finalize allow/remove**. Original labels and their timing remain; the final team decision replaces voting for that post in subsequent fits. Without auditing, majority votes are used; ties are excluded. A single device can test annotation purchases, configurations, training, and evaluation, but cannot create a disagreement alone.

Spending does not add to a model’s accuracy. New text can help or hurt; feature changes can overfit; auditing can reinforce a team’s mistaken assumptions. Actual measured training time is shown in milliseconds. The illustrative accounting is entirely separate:

- Electricity: successful runs × configurable kWh/run × feature multiplier (words 1, word pairs 1.5, character fragments 3), constrained by the team’s configurable fictional allowance.
- Cooling water: illustrative electricity × configurable liters/kWh.
- Hardware capacity: 1 fictional unit, or 2 after upgrading.
- Unbilled labor: recorded annotation time plus completed shared audit time × configurable credits/hour. These are not deducted from company credits.

**These quantities are fictional teaching inputs, not measurements or scientifically validated estimates of the footprint of this small classifier.** Instructor notes expose every assumption. Shared audit time measures elapsed time from opening a review to submitting a final decision, capped at 30 minutes, rather than summing every teammate’s attention. Pauses/phase changes reset unfinished annotation timing. The instructor opens the broader accounting with the final reveal.

## Verify Milestone 4: the infrastructure reveal

1. After opening Testing, click **Reveal the hidden infrastructure**. This is instructor-only; all connected student screens advance to the same final phase. Decisions remain frozen.
2. Select nodes in the interactive map: mineral extraction → manufacturing → servers; electricity and cooling water support computing; annotators → classification choices → learned model → prediction. Every node is a keyboard-accessible button. On phones the map becomes a readable grid; the explanatory panel remains below it.
3. Choose **Explore company** to inspect one team or all companies. Change the evaluation example to connect an actual stored model prediction with its supporting work. No per-prediction footprint is inferred from classroom totals.
4. Compare the companies in the final balance sheet: policy agreement, spending, annotations, total/average recorded task time, unresolved disagreements, training operations, measured training time, and illustrative resource quantities. Extraction, manufacturing, transport, and disposal are qualitative dependencies, not fabricated measured quantities.
5. Discuss work, control, and benefits using the topic buttons. The reading links connect the activity to *Excavating AI*, *Anatomy of an AI System*, and Yale Environment 360. Ownership is explicitly a simulation premise, not a legal conclusion.
6. Use **Presentation** in the header for large text and a simplified projector view. **Exit presentation** stays accessible in the header, including during the reveal. **Back to model results** reopens Testing if you want to revisit specific decisions.

The advisory phase clock suggests 5 minutes annotation, 4 minutes training, 5 minutes testing, and 5 minutes reveal/discussion (~19 minutes total). It never advances automatically. Pausing annotation freezes its clock; resuming keeps elapsed time. Each new phase/improvement round starts its own suggested time. The timer uses server elapsed time rather than relying on students’ phone clocks being synchronized.

## Verify Milestone 5: demo, reset, and recovery

### Demonstrate with no student devices

At instructor entry, check **Demonstration room** before creating the room. If you are already in a room, use the leave icon and create a separate demo room. Demo rooms cannot accept real student joins, so synthetic labels cannot contaminate a live classroom dataset.

A demo has 15 clearly identified simulated participants with 276 preloaded annotations across all three companies. Labels and annotation times are scripted and are never presented as actual student labor. The label script does not read held-out reference answers. Three classifiers are trained for real from the scripted training labels.

Use the normal **Start annotation → Begin training → Train eligible teams → Compare models → Reveal the hidden infrastructure** controls. No student tabs or accounts are needed. In Training, expand **Demonstrate team investments & auditing**, select a company, and use its investment/audit desk. **Simulate pending annotations** labels newly unlocked posts using the script. Purchases, budgets, training limits, and audits follow the same server rules as live play; real elapsed training time is measured. Any shared audit review you perform is measured interface activity, not simulated student attention.

For a classroom connectivity failure, run the app locally on your laptop and open `http://localhost:8000/instructor` to demonstrate from the projector. Build/download dependencies and Docker images before class. The runtime has no external font, AI API, or image dependencies; reading links are optional external pages. Demo mode still needs the local backend and PostgreSQL. It is not a static/offline replacement for the server.

### Reset without disconnecting students

Choose **Reset room** and type the room code to confirm. This clears labels, audit decisions, purchases, and trained models for that room, restores the configured budget, rebuilds initial queues, balances the existing participants, and returns everyone to the lobby. The room code, instructor session, student credentials, nicknames, and configured rules are retained. Demo rooms reload their scripted labels. Other rooms are untouched.

Reset is atomic and protected by the instructor token. A room generation number rejects late writes from the previous round, and duplicate reset request IDs cannot reset twice. Each tab learns the new generation through polling; students do not have to rejoin. The browser retries interrupted polling, reports the connection issue, and keeps the session during ordinary refreshes. Closing the browser tab loses its sessionStorage credential; there is no account-based recovery. The reset deletes that round’s results, so finish discussion before confirming.

## Tests

```bash
source .venv/bin/activate
python -m pytest backend/tests -q
cd frontend
npm ci
npm run build
```

The default backend suite uses an isolated in-memory SQLite database for convenience. Production uses PostgreSQL. To exercise PostgreSQL row locking and SQL behavior, create a **disposable, separate** test database and run:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/truecost_test \
  .venv/bin/python -m pytest backend/tests -q
```

**The test fixture drops and recreates application tables in TEST_DATABASE_URL. Never point it at a classroom database.**

Browser tests exercise a desktop instructor and a 390px mobile student: QR invitation, annotation, reload persistence, live updates, pause/presentation, one-team training, purchases, held-out evaluation, improvement, keyboard-operated reveal, reset with the same student session, and a complete three-company demonstration with non-local network requests blocked. First run the backend serving the built frontend, then:

```bash
cd frontend
npx playwright install chromium
E2E_INSTRUCTOR_SECRET='YOUR_RUNNING_SERVER_KEY' npm run test:e2e
# Optional: E2E_BASE_URL=http://localhost:8000
```

Each browser test creates a new room in the running app. Screenshots are written to `frontend/test-results/` (ignored by Git).

## Architecture and data

- `frontend/`: React, TypeScript, Vite, accessible phone layouts, instructor dashboard, locally generated QR codes, bundled fonts (no external font requests).
- `backend/app/`: FastAPI, SQLAlchemy, PostgreSQL. Instructor phase transitions and student writes acquire a room row lock to serialize joining, team changes, and submissions. Assignment records enforce unique person/post pairs.
- `backend/app/content.py`: 170 original fictional posts and the shared moderation policy. IDs 0–99 and 120–169 are the 150 training candidates; IDs 100–119 are reserved for held-out evaluation and never sent to annotation clients.
- Each team receives 60 unique candidates. Twenty examples are shared across all three teams; other examples rotate with partial overlap. Eight common anchors are assigned to every team member; the remaining 52 posts are divided into five rotating batches. Each student gets 18–19 posts, regardless of team size; larger teams reuse batches, adding independent labels. A team of five covers all 60 posts with 92 labels. Smaller teams may cover fewer unique posts. Auditing adds explicit team adjudications without overwriting the original annotations. Reference decisions are exposed only during Testing.
- `backend/app/learning.py`: TF-IDF fit on training text only, then logistic regression. Each distinct post gets one majority/adjudicated label. The complete fitted vocabulary, IDF, coefficients, label snapshot, version, predictions, and evaluation are persisted as JSON in PostgreSQL; no pickle loading is used. Fits run synchronously under the room lock because datasets are tiny (at most 150 posts), with numerical worker threads limited to one.
- `backend/app/economy.py`: per-room settings, per-team accounts, purchase ledger, audit decisions, and resource formulas. The new tables are additive. Existing rooms receive default accounts on first access; existing participants and labels remain intact. No destructive migration or database reset is required.
- `backend/app/experience.py`: additive room metadata, phase clocks, scripted demo annotations, atomic reset, and final reveal accounting. All room mutations check the current generation. Private API responses and the HTML shell are not cached by browsers/proxies.
- Two-second HTTP polling supports reconnection without managing WebSocket sessions, designed for classroom-scale attendance. All state lives in PostgreSQL; restarting the server retains rooms and labels.
- Production has one origin: FastAPI serves the Vite build and `/api`. Development uses Vite’s proxy. No paid services or AI APIs are used.

Do not collect real sensitive information in nicknames or posts. Treat participant credentials as access keys; anyone holding one can resume that session. This is a small classroom application, not a public identity system. Retention/export and session recovery can be added later if needed.

## Railway deployment

The root `Dockerfile` builds the frontend and serves it from FastAPI using Railway’s `PORT`. `railway.toml` configures the database-backed `/api/health` check.

1. Add a PostgreSQL service and an application service from this repository.
2. In the app service, set `DATABASE_URL` to the PostgreSQL service’s connection URL (Railway supports a reference such as `${{Postgres.DATABASE_URL}}`). Set a private random `INSTRUCTOR_SECRET`.
3. Deploy using the root Dockerfile and generate a public HTTPS domain. Open `/instructor` there; QR links default to that same origin. If you previously saved a local address, update the Student-accessible URL field to your Railway URL.

Set the Railway application’s root directory to the **repository root**, so the root Dockerfile can see both frontend and backend. Keep one application replica for this small class. The server listens on `0.0.0.0:$PORT`; the startup shell uses `exec` so shutdown signals reach Uvicorn. The app runs as a non-root user; numerical worker threads are bounded. PostgreSQL keeps all room/model data across application restarts. Do not store the database in the application container.

Railway’s health check is `/api/health`; HTTP 200 and `milestone: 5` indicate a database connection and the current app version. It is a startup/deployment check, not a promise of uninterrupted service. See the official [Dockerfile guide](https://docs.railway.com/builds/dockerfiles) and [health-check guide](https://docs.railway.com/deployments/healthchecks).

### Validate the production image locally

```bash
sudo bash scripts/verify-container.sh
```

Requires Docker, Python 3, and curl. This builds the actual production Dockerfile, starts an isolated disposable PostgreSQL 17 container, binds the app to a random loopback port, confirms a non-root runtime, verifies HTML/assets/API, creates a separate demo room, trains/evaluates all three models, opens the reveal, and tests reset. It cleans up only its own containers, image, and network; it does not touch your Compose database or port 8000. Run it where Docker access is available. Do not run `docker compose down -v` to update this app; that would delete your local classroom database.

### Check an existing deployment

```bash
python3 scripts/check_deployment.py https://YOUR-APP.up.railway.app
# Optional full demo smoke test (creates its own demo room, then resets it):
INSTRUCTOR_SECRET='YOUR_RAILWAY_KEY' python3 scripts/check_deployment.py \
  https://YOUR-APP.up.railway.app --exercise-demo
```

The read-only default checks health, the instructor page, and bundled frontend assets on one origin. The optional test does not touch existing classroom rooms. Use your Railway key only in your own terminal environment; do not commit it. Railway publishing/account setup is performed in your Railway project, not automatically by this repository.

`.github/workflows/checks.yml` runs the Python 3.13/PostgreSQL 17 suite, frontend build, browser suite, and disposable production-container smoke test on GitHub pushes, pull requests, or manual workflow dispatch. It uses throwaway CI credentials. The workflow must be enabled/run in your GitHub repository to obtain an actual hosted CI result.

The Compose database volume persists between `docker compose down` and `up`. Production and local updates need only `docker compose up --build`; no database reset or destructive migration is required. Docker is not needed for the native test suite.

## Educational basis and roadmap

- [Crawford & Paglen, *Excavating AI*](https://excavating.ai/): classification reflects human choices and political assumptions. Shared policies and conflicting labels make those choices visible.
- [Crawford & Joler, *Anatomy of an AI System*](https://anatomyof.ai/): AI draws on connected systems of labor, extraction, manufacturing, and infrastructure. The interactive map makes those connections visible.
- [David Berreby, Yale Environment 360](https://e360.yale.edu/features/artificial-intelligence-climate-energy-emissions): electricity, cooling water, and equipment complicate AI sustainability. Resource quantities are explicitly fictional, with configurable assumptions rather than claims about the footprint of this small classifier.

All five implementation milestones are present. Before class, run the production-container check on your Ubuntu laptop, deploy to your Railway project if you want public access, and rehearse the full flow on the classroom network. The remaining deployment verification depends on that actual hosting environment; no live Railway deployment is claimed by the code or tests.
