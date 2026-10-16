# ReefCare MY Backend

Backend API for **ReefCare MY**, a community reef observation and conservation coordination platform developed through Iterations 1–3.

The backend supports public reef information, authenticated observation reporting, AI-assisted report preparation, private evidence handling, coordinator case management, related-incident detection, conservation follow-up, Observer impact feedback, and planning workflows.

The application is built with **FastAPI** and **PostgreSQL on Neon**, with private evidence stored in **Supabase Storage**.

---

## 1. Technology Stack

- **Python 3.12**
- **FastAPI 0.141.1**
- **Uvicorn 0.52.4**
- **Pydantic 2.13.4**
- **SQLAlchemy 2.0.52**
- **psycopg 3.3.4**
- **PostgreSQL on Neon**
- **PyJWT 2.13.0**
- **pwdlib[argon2]**
- **Supabase Storage**
- **python-multipart 0.0.32**
- **DeepSeek API** for selected AI-assisted features
- **Vercel** for backend deployment

---

## 2. Backend Architecture

The backend follows a layered architecture:

```text
Client
  ↓
FastAPI app
  ↓
api/router.py
  ↓
api/routes/
  ↓
dependencies/
  ↓
schemas/
  ↓
services/
  ↓
repositories/
  ↓
PostgreSQL / Supabase Storage / approved external services
```

### Layer Responsibilities

- `app/api/routes/`  
  Thin HTTP adapters responsible for request parsing, dependency injection, response models, and HTTP status codes.

- `app/api/dependencies/`  
  Authentication, role checks, database session dependencies, and rate limiting.

- `app/schemas/`  
  Pydantic request and response contracts. Python uses snake_case internally while external API responses use camelCase where required.

- `app/services/`  
  Business workflow orchestration, validation, authorisation policy, safe response projection, AI integration, and transaction coordination.

- `app/repositories/`  
  SQL queries, database views, and calls to canonical PostgreSQL `reefcare_*` functions.

- `app/core/`  
  Configuration, JWT/security helpers, shared exceptions, enums, and logging.

- `app/db/`  
  Async database engine and session setup.

The database remains authoritative for workflow invariants such as report submission, case claiming, legal state transitions, closure, and protected report access.

---

## 3. Main Backend Areas

By Iteration 3, the backend covers the following functional areas:

```text
Authentication and access control
Public reef information
Dive Sessions
Observation reporting
AI-assisted report preparation
Evidence upload and private retrieval
Coordinator case management
Related-incident detection
Conservation follow-up
Observer impact feedback
Public-safe reef activity
Planning and saved planning workflows
```

The main backend structure remains:

```text
reefcare-backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── router.py
│   │   ├── dependencies/
│   │   └── routes/
│   ├── core/
│   ├── db/
│   ├── repositories/
│   ├── schemas/
│   └── services/
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Important Iteration 3 service areas include:

```text
Smart Report Structuring
Visual Threat Recognition
Report completeness checking
Location consistency checking
Final report review
AI suggestion provenance
Related-incident detection
Observer report tracking
Observer evidence access
Information-response photos
Conservation follow-up
Public reef activity
Planning support
```

---

## 4. Environment Setup

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Required environment variables include:

```env
APP_NAME=ReefCare MY
APP_ENV=development
API_V1_PREFIX=/api/v1

DATABASE_URL=<postgresql+psycopg connection string>

JWT_SECRET_KEY=<minimum 32 character secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,<deployed frontend origins>

LOGIN_RATE_LIMIT_REQUESTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60

SUPABASE_URL=<supabase project url>
SUPABASE_SECRET_KEY=<supabase secret>
SUPABASE_STORAGE_BUCKET=reefcare-evidence

DEEPSEEK_API_KEY=<deepseek api key>
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

### Database Connection

The backend uses SQLAlchemy async sessions with **psycopg 3**.

The connection string should use:

```text
postgresql+psycopg://...
```

rather than a synchronous `psycopg2` connection.

### Important

- Never commit `.env`.
- Never commit database passwords, JWT secrets, DeepSeek API keys, or Supabase secrets.
- Production deployment should use `APP_ENV=production`.
- Application traffic should use the restricted ReefCare application database role rather than the Neon owner account.
- Environment-variable changes on Vercel require a redeployment before they take effect.
- Before deploying the DeepSeek migration, set `DEEPSEEK_API_KEY` as a private Vercel environment variable and redeploy. Keep the old provider key until the new AI flows have been verified in the deployed environment.

---

## 5. Local Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the API locally:

```powershell
uvicorn app.main:app --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## 6. Authentication

### Login

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded
```

Form fields:

```text
username=<email>
password=<password>
```

Example success response:

```json
{
  "accessToken": "<signed-token>",
  "tokenType": "bearer",
  "expiresIn": 3600,
  "user": {
    "id": 42,
    "displayName": "Sample Observer",
    "role": "observer"
  }
}
```

`expiresIn` is returned in seconds.

### Current User

```http
GET /api/v1/auth/me
Authorization: Bearer <accessToken>
```

### Register Observer

```http
POST /api/v1/auth/register
Content-Type: application/json
```

Example:

```json
{
  "email": "newdiver@example.com",
  "displayName": "New Diver",
  "password": "reef12"
}
```

Self-registration always creates an **Observer**.

The registration request does not expose a privileged role selector.

Current password policy:

```text
Minimum length: 6 characters
Maximum length: 128 characters
At least 4 distinct characters
```

Coordinator and administrator accounts are managed through authorised administrative workflows rather than public self-registration.

---

## 7. Reference Data

Reference endpoints provide controlled values used throughout the application.

Examples include:

```text
GET /api/v1/reference/threat-categories
GET /api/v1/reference/dive-sites
```

Public/reference responses must not expose restricted precise coordinates or private case information.

---

## 8. Dive Sessions

Observers can create and retrieve their own Dive Sessions.

```text
GET  /api/v1/dive-sessions
POST /api/v1/dive-sessions
```

The Observer identity comes from the authenticated token.

Users cannot request another Observer's Dive Sessions by changing an ID.

Dive Sessions provide the confirmed observation context used by the report-submission workflow.

---

## 9. Reporting Workflow

Iteration 3 expands the reporting workflow beyond the original Iteration 1 submission form.

The current Observer flow is approximately:

```text
Authenticate
  ↓
Create / select Dive Session
  ↓
Start observation report
  ↓
Optional Smart Report Structuring
  ↓
Optional Visual Threat Recognition
  ↓
Confirm / correct / remove AI suggestions
  ↓
Completeness check
  ↓
Location consistency check
  ↓
Final review
  ↓
Submit report + evidence
  ↓
Related-incident detection
  ↓
Coordinator workflow
  ↓
Observer tracks status, follow-up and impact
```

AI output remains advisory.

The Observer's confirmed values remain authoritative for the submitted report.

---

## 10. AI-Assisted Reporting

### Smart Report Structuring

```http
POST /api/v1/reports/smart-structure
```

Smart Report Structuring converts an Observer-written description into optional structured suggestions.

Important boundaries:

- accepts report description text only;
- does not persist the draft;
- does not receive precise coordinates;
- does not receive stored private evidence;
- returns advisory suggestions;
- suggestions require Observer review;
- selects only relevant predefined follow-up questions;
- AI failure must not prevent manual reporting.

---

### Visual Threat Recognition

```http
POST /api/v1/reports/visual-recognition
```

Visual Recognition accepts one validated pre-submission image and returns an advisory threat suggestion.

The result:

- does not automatically change the selected threat category;
- is not treated as confirmed until reviewed by the Observer;
- does not replace human confirmation;
- does not independently submit or mutate the report.

---

### AI Suggestion Provenance

Iteration 3 preserves the source and final review state of AI suggestions.

Supported sources include:

```text
smart_report
visual_recognition
```

Reviewed suggestion states include:

```text
confirmed
corrected
removed
```

Smart Report and Visual Recognition may both suggest a value for the same field because provenance is stored separately by source.

AI suggestions are not treated as canonical report values until the Observer resolves them.

---

## 11. Report Preparation Endpoints

### Completeness Check

```http
POST /api/v1/reports/completeness-check
```

Checks whether a report contains the information required for final submission.

This endpoint does not:

- create a report;
- upload evidence;
- mutate workflow state;
- call AI.

---

### Location Check

```http
POST /api/v1/reports/location-check
```

Performs an advisory consistency check between the selected named dive site and the Observer's submitted precise point.

The result does not silently modify:

- the selected dive site;
- latitude;
- longitude;
- location source.

The location warning is advisory rather than a submission blocker.

---

### Final Review

```http
POST /api/v1/reports/review
```

Builds the final Observer-facing review before submission.

The review may include:

- report completeness;
- selected threat;
- selected dive site;
- observation information;
- location information;
- evidence metadata;
- location warnings;
- unresolved AI suggestions.

The review endpoint does not persist the final report.

---

## 12. Observation Reports

Main Observer report endpoints include:

```text
POST /api/v1/reports

GET  /api/v1/reports/mine

GET  /api/v1/reports/{reportReference}

GET  /api/v1/reports/{reportReference}/timeline

GET  /api/v1/reports/{reportReference}/evidence/{evidenceId}

GET  /api/v1/reports/{reportReference}/information-request

POST /api/v1/reports/{reportReference}/information-response

POST /api/v1/reports/{reportReference}/information-response/with-photos
```

Observer identity always comes from the authenticated token.

Users cannot request another Observer's protected report by changing an ID or report reference.

---

## 13. Report Submission

Final report submission uses:

```http
POST /api/v1/reports
Content-Type: multipart/form-data
```

The submission includes:

```text
payload
photos
```

`payload` contains the validated report data.

`photos` contains the actual evidence files.

The submission service validates:

- Observer identity;
- report completeness;
- resolved AI suggestions;
- Dive Session ownership;
- selected dive-site consistency;
- location values;
- reference values;
- evidence files.

PostgreSQL remains authoritative for:

- report creation;
- report reference generation;
- evidence metadata persistence;
- Dive Session association;
- report location;
- initial case status;
- intake events.

---

## 14. Evidence Handling

Evidence is stored privately in Supabase Storage.

Current evidence protections include:

- supported media-type validation;
- maximum file-size validation;
- empty-file rejection;
- lightweight file-signature validation;
- private object storage;
- controlled metadata stored in PostgreSQL;
- cleanup when database submission fails;
- no Supabase object key exposed through ordinary API responses.

Current standard upload formats are:

```text
JPEG
PNG
WebP
```

The evidence service is the central backend boundary for image validation and storage.

Future image-format normalisation, such as converting additional decodable image formats into JPEG before storage, should also be implemented in this layer.

---

## 15. Observer Evidence Access

Iteration 3 allows an Observer to safely view evidence associated with their own report.

The Observer may access:

```text
Original report evidence
Observer's own additional-information evidence
```

The Observer may not access:

```text
Another Observer's evidence
Coordinator follow-up evidence
Private Supabase object references
Internal case-event information
```

Private evidence is retrieved through:

```http
GET /api/v1/reports/{reportReference}/evidence/{evidenceId}
```

Access checks occur before the backend downloads the object from private storage.

A missing, mismatched, or unauthorised report/evidence combination is returned as `404` to avoid protected-resource enumeration.

---

## 16. Additional Information with Photos

When a Coordinator requests more information, the submitting Observer can respond with text and optional photographs.

Text-only response:

```http
POST /api/v1/reports/{reportReference}/information-response
```

Response with optional photos:

```http
POST /api/v1/reports/{reportReference}/information-response/with-photos
```

The additional-information response:

- remains attached to the existing report;
- does not create a new report;
- retains the same Coordinator ownership;
- stores reply photos privately;
- associates reply photos with the `info_provided` case event;
- saves the reply and photos together or not at all.

The current photo-response contract supports up to five reply photos.

---

## 17. Coordinator Workflow

The Coordinator workflow includes:

```text
Queue
  ↓
Claim
  ↓
Owned case review
  ↓
Evidence assessment
  ↓
Request more information if required
  ↓
Record decision
  ↓
Related-incident review / follow-up
  ↓
Record conservation action or outcome
  ↓
Closure
```

Core endpoints include:

```text
GET  /api/v1/coordinator/queue

POST /api/v1/coordinator/reports/{reportReference}/claim

GET  /api/v1/coordinator/reports/{reportReference}

POST /api/v1/coordinator/reports/{reportReference}/information-request

POST /api/v1/coordinator/reports/{reportReference}/decision

POST /api/v1/coordinator/reports/{reportReference}/close
```

Additional Iteration 3 Coordinator functionality supports:

```text
Related incidents
Conservation follow-up
Action/outcome recording
Follow-up evidence
Observer-impact feedback
```

Coordinator ownership and legal workflow transitions remain server-side concerns.

---

## 18. Related-Incident Detection

Iteration 3 includes related-incident detection to identify reports that may describe the same reef issue.

Candidate detection may consider approved report context such as:

- geographic proximity;
- threat category;
- observation timing;
- depth;
- description similarity;
- image similarity where enabled.

Automated similarity does not merge reports automatically.

A human decision remains required before reports are treated as the same incident.

Confirmed relationships preserve the original reports while associating them with the same underlying issue.

The related-incidents workflow must not expose:

- another Observer's identity;
- another Observer's protected report details;
- private storage references;
- unrestricted precise-location information.

---

## 19. Conservation Follow-Up

Iteration 3 extends the case lifecycle beyond the original decision and closure workflow.

Follow-up records may represent:

```text
Planned conservation action
Recorded/completed conservation action
Monitoring follow-up
External/sourced outcome
Other valid follow-up records
```

Follow-up records are append-oriented.

Corrections supersede earlier records rather than silently overwriting history.

Demonstration records are excluded from real Observer impact feedback.

Coordinator follow-up evidence remains private unless explicitly exposed through an authorised workflow.

---

## 20. Observer Impact Feedback

Observers can receive safe feedback describing what happened after their report entered the conservation workflow.

Possible feedback includes:

```text
Report referred or shared for follow-up
Report contributing to ongoing monitoring
Conservation action planned
Conservation action recorded as completed
External follow-up outcome recorded
Report retained as site history
Report linked to an existing report of the same issue
```

The Observer-facing projection deliberately excludes:

- Coordinator identity;
- another Observer's identity;
- another report reference;
- internal incident IDs;
- internal action notes;
- source references intended for Coordinator use;
- private storage references.

Observer impact feedback is private to the submitting Observer.

It is separate from the public reef-activity publication boundary.

---

## 21. Observer Timeline

```http
GET /api/v1/reports/{reportReference}/timeline
```

The timeline exposes Observer-safe workflow history.

Iteration 3 timeline entries may include:

```text
status
related_incident
follow_up
```

The latest ordinary status remains the current case state.

Related-incident and follow-up entries are informational events rather than replacement workflow states.

The timeline never exposes:

- another report reference;
- another Observer;
- internal incident identifiers;
- Coordinator identity.

---

## 22. Public Reef Information

The public ReefCare experience provides public-safe information about selected reef and dive-site areas.

Public projections must not expose:

- exact restricted coordinates;
- private Observer identities;
- protected case information;
- private evidence;
- Coordinator-only details.

Public ReefCare information can include approved:

```text
Dive-site information
Responsible observation guidance
Environmental context
Public-safe ReefCare activity
```

Public information and private case-management information remain deliberately separated.

---

## 23. Public ReefCare Activity

Iteration 3 supports public-safe ReefCare activity for selected dive sites.

Example endpoint:

```http
GET /api/v1/public/dive-sites/{diveSiteId}/activity
```

The public activity projection supports:

```text
Loading state
Populated activity
Honest empty state
API error / retry state
```

Only records approved for public display should be returned.

Public activity must not expose:

- exact sensitive coordinates;
- private Observer details;
- restricted report references;
- private evidence;
- internal case information.

The public-activity publication boundary is separate from private Observer impact feedback.

---

## 24. Planning

Iteration 3 introduces planning support connected to the ReefCare public and reporting experiences.

Current planning work includes:

```text
Planning core
Public-site planning handoff
AI-assisted Planning Brief
Saved plans
Planning/report handoff
```

Planning functionality remains separated from protected case-management data.

Only information appropriate to the planning workflow should cross public, report, and case boundaries.

---

## 25. Database-Owned Workflow Rules

Critical workflow invariants remain enforced in PostgreSQL.

Canonical database functions include:

```text
reefcare_submit_report(...)
reefcare_claim_report(...)
reefcare_change_status(...)
reefcare_close_report(...)
reefcare_my_reports(...)
reefcare_report_timeline(...)
reefcare_report_location(...)
```

Important rules:

- Do not directly update `report.current_status_id` for normal workflow transitions.
- Do not duplicate `case_event` entries already created by canonical database functions.
- Do not recreate PostgreSQL workflow functions or triggers independently in Python.
- Do not maintain a conflicting second database schema.
- The database remains authoritative for legal transitions, claim atomicity, closure rules, ownership, and protected workflow operations.

Repositories should remain thin SQL/data-access boundaries rather than replacing database-owned workflow logic.

---

## 26. Case Status and Workflow Values

Canonical persisted workflow values are defined centrally and must be reused across schemas, services, repositories, and database operations.

Examples include:

```text
draft
submitted
received
claimed
under_review
needs_more_info
evidence_accepted
monitoring
referred
response_recommended
response_planned
response_complete
closed_no_action
closed_not_substantiated
closed_no_partner
closed_logged
```

Do not create a separate uppercase backend-only workflow vocabulary.

---

## 27. Security Controls

Current backend security controls include:

- modern password hashing;
- signed JWT access tokens;
- access-token expiration;
- authenticated role dependencies;
- Observer ownership isolation;
- Coordinator case ownership checks;
- login and registration rate limiting;
- explicit production CORS allowlist;
- Pydantic response boundaries;
- precise reef-location access restrictions;
- private Supabase evidence storage;
- server-side evidence authorisation;
- database-enforced workflow transitions;
- protected report-reference enumeration controls;
- environment-based secret management;
- safe error responses;
- AI advisory boundaries.

Sensitive values must never be exposed through ordinary API responses or logs.

This includes:

```text
Database passwords
JWT secrets
Supabase secret keys
DeepSeek API keys
Private evidence object keys
Restricted precise coordinates
Internal Coordinator-only notes
Protected actor identities
```

---

## 28. Location Privacy

Named/general reef location and precise coordinates are treated separately.

Precise location may be retrieved only through authorised database/service boundaries.

The submitting Observer may see their own submitted location where allowed.

The claiming Coordinator may access authorised case location where required.

Public/reference endpoints must not expose restricted precise coordinates.

Administrators do not automatically gain sensitive-location access simply because they hold an administrative role.

---

## 29. Error Behaviour

Expected HTTP behaviour includes:

```text
400  invalid workflow/input combination
401  unauthenticated / invalid credentials
403  authenticated but not authorised
404  missing or non-owned protected resource
409  conflict / invalid state transition / duplicate claim
413  evidence file too large
422  request validation error
429  rate limit exceeded
500  safe internal/database/storage failure
```

Pydantic validation errors are returned in JSON-safe form.

Internal Python exception objects must not leak into FastAPI responses.

Protected-resource lookups may deliberately return `404` instead of revealing whether another user's resource exists.

---

## 30. CORS

The backend and frontend are deployed separately, so CORS must explicitly include approved frontend origins.

Do not use:

```text
*
```

as the production CORS policy.

After changing `CORS_ORIGINS` in Vercel:

```text
Update environment variable
  ↓
Redeploy backend
  ↓
Confirm deployment is Ready
  ↓
Run frontend/backend smoke test
```

Local origins should be retained only where needed for development.

---

## 31. Testing

The backend has an automated test suite covering API, service, unit, and database-integration behaviour.

Latest full regression result:

```text
598 passed
7 skipped
5 warnings
```

The remaining warnings are dependency deprecation warnings and are not test failures.

Important tested areas include:

```text
Authentication
Observer registration
Report submission
JSON-safe validation failures
Observer report tracking
Precise-location isolation
Private evidence handling
Information-response photos
Coordinator follow-up evidence
Planning
Public sites
Smart Report Structuring
Visual Recognition
Related-Incident Detection
Related-Incident database behaviour
Observer timeline
Observer access boundaries
```

Run the complete test suite with:

```powershell
pytest -q
```

A full regression run should be completed before merging substantial backend changes.

Targeted tests may be run during development before the full suite.

---

## 32. Development Workflow

Feature work should remain isolated until tested and reviewed.

Recommended workflow:

```text
Update local main
  ↓
Create / switch to feature branch
  ↓
Implement feature
  ↓
Run targeted tests
  ↓
Run full regression suite
  ↓
Push feature branch
  ↓
Open Pull Request
  ↓
Review
  ↓
Merge into main
  ↓
Deploy
  ↓
Run production smoke test
```

Typical branch setup:

```powershell
git checkout main
git pull origin main
git checkout -b feature/<feature-name>
```

Before merge:

```powershell
pytest -q
```

Check the files being committed:

```powershell
git status
git diff
```

Never commit `.env` or runtime secrets.

---

## 33. Deployment

The backend is deployed on **Vercel**.

Production backend:

```text
https://reefcare-backend.vercel.app
```

The production deployment is connected to the `main` branch.

After backend or environment changes:

1. Push or merge the intended code.
2. Confirm the correct Vercel deployment was triggered.
3. Confirm required Production environment variables are available.
4. Wait until the deployment status is `Ready`.
5. Run backend/API smoke tests.
6. Test the deployed frontend/backend workflow.

The backend currently integrates with:

```text
Vercel
  ↓
FastAPI backend
  ↓
Neon PostgreSQL

FastAPI backend
  ↓
Supabase private evidence storage
```

AI-assisted features use the configured DeepSeek service where enabled.

---

## 34. Production Troubleshooting

When diagnosing a deployed issue, first identify whether it is:

```text
Frontend request construction
FastAPI validation
Application/service logic
Database workflow
Supabase evidence storage
External AI service
Vercel configuration
```

### HTTP 422

A `422` usually indicates request validation failure.

For multipart report submission, confirm that the final request contains both:

```text
payload
photos
```

A UI displaying a photo filename does not necessarily prove that the actual browser `File` object reached the final `FormData`.

### HTTP 500

Check:

```text
Vercel Function Invocation logs
Database configuration
Environment variables
Database schema/function compatibility
Supabase configuration
```

Do not expose production secrets while debugging.

### Environment Changes

After changing a Vercel environment variable, redeploy before testing again.

---

## 35. Current Iteration 3 Status

Implemented or integrated backend areas include:

- Observer registration and login;
- role-based authentication and access boundaries;
- account password validation;
- Dive Session creation and listing;
- threat-category and dive-site reference data;
- public reef information support;
- public-safe ReefCare activity;
- safe location handling;
- report completeness checking;
- location consistency checking;
- Smart Report Structuring;
- Visual Threat Recognition;
- AI suggestion provenance;
- final Observer AI review;
- report submission;
- private evidence upload;
- Coordinator queue;
- atomic case claim;
- Coordinator case review;
- information requests;
- Observer information responses;
- additional-information photo upload;
- case decisions;
- case closure;
- related-incident detection;
- human-confirmed related incidents;
- related-incident database safeguards;
- conservation follow-up/action recording;
- follow-up evidence;
- correction/supersession of follow-up records;
- Observer impact feedback;
- Observer My Reports;
- Observer report detail;
- Observer-safe timeline;
- Observer-owned evidence retrieval;
- planning core;
- planning handoff;
- AI-assisted Planning Brief;
- saved plans;
- report/planning handoff;
- rate limiting;
- global error handling;
- production CORS;
- Vercel deployment;
- Neon PostgreSQL integration;
- Supabase private evidence integration.

---

## 36. Backend Quality Baseline

Future backend changes should preserve the following principles.

### Human Confirmation over AI Automation

AI may assist with report preparation and similarity detection, but it must not silently become the authoritative decision-maker.

### Database-Owned Workflow

Critical report and case transitions remain enforced by PostgreSQL rather than duplicated independently in route or frontend logic.

### Privacy by Design

Precise locations, identities, and private evidence are exposed only to explicitly authorised users.

### Append-Oriented Traceability

Important workflow and follow-up history should be preserved rather than silently overwritten.

### Honest Public Projection

Public ReefCare pages expose only approved public-safe information.

### Closed-Loop Observer Experience

Observers can submit a report and later understand its status, follow-up, and contribution without gaining access to Coordinator-only information.

### Stable API Boundaries

External API contracts should use dedicated Pydantic schemas rather than returning raw database mappings.

### Safe Evidence Handling

Private storage references stay server-side and all evidence retrieval passes an explicit authorisation boundary.

---

## 37. Team

**FIT5120 TM18 — ReefCare MY**

Backend contributors include:

- **Hong Shen**
- **Frank**
- **Miusan**

The wider ReefCare MY project also includes frontend, product, design, testing, and project-management contributions from other team members.

---

## 38. Related Documentation

For detailed API contracts, database rules, user stories, acceptance criteria, security decisions, maintenance procedures, and handover information, refer to the latest Iteration 1–3 project documentation.

Key supporting material includes:

```text
ReefCare Backend Documentation
Iteration 1–3 User Stories
Iteration 3 Proposal
Product Discovery documentation
Testing documentation
Maintenance / Handover documentation
```

This README is intended to provide developers with a practical overview of the current Iteration 3 backend.

Detailed database contracts, endpoint payloads, operational procedures, and maintenance instructions should remain in the dedicated project documentation rather than being duplicated completely here.
