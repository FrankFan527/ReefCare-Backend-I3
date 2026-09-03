# ReefCare MY Backend

Backend API for **ReefCare MY**, an Iteration 1 MVP for community reef observation, case coordination, safe location handling, evidence submission, and observer case tracking in Malaysia.

The backend is built with **FastAPI** and **PostgreSQL on Neon**, with private evidence stored in **Supabase Storage**.

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

---

## 2. Backend Architecture

The backend follows this request flow:

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
PostgreSQL / Supabase Storage
```

### Layer responsibilities

- `app/api/routes/`  
  Thin HTTP adapters. Handles request parsing, dependency injection, response models, and HTTP status codes.

- `app/api/dependencies/`  
  Authentication, role checks, database session dependencies, and rate limiting.

- `app/schemas/`  
  Pydantic request/response contracts. External JSON uses camelCase while Python remains snake_case.

- `app/services/`  
  Workflow orchestration, validation, authorisation policy, safe response projection, and transaction coordination.

- `app/repositories/`  
  SQL queries, database views, and calls to canonical PostgreSQL `reefcare_*` functions.

- `app/core/`  
  Configuration, JWT/security helpers, shared exceptions, enums, and logging.

- `app/db/`  
  Database engine and async session setup only.

---

## 3. Current Repository Structure

```text
reefcare-backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── router.py
│   │   ├── dependencies/
│   │   │   ├── auth.py
│   │   │   ├── authorization.py
│   │   │   ├── db.py
│   │   │   └── rate_limit.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── coordinator.py
│   │       ├── case_actions.py
│   │       ├── dive_sessions.py
│   │       ├── reference.py
│   │       ├── reports.py
│   │       └── health.py
│   ├── core/
│   │   ├── config.py
│   │   ├── enums.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   └── security.py
│   ├── db/
│   │   └── session.py
│   ├── repositories/
│   │   ├── auth_repository.py
│   │   ├── case_repository.py
│   │   ├── case_decision_repository.py
│   │   ├── dive_session_repository.py
│   │   ├── evidence_repository.py
│   │   ├── location_repository.py
│   │   ├── queue_repository.py
│   │   ├── reference_repository.py
│   │   └── report_repository.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── case.py
│   │   ├── common.py
│   │   ├── dive_session.py
│   │   ├── reference.py
│   │   └── report.py
│   └── services/
│       ├── auth_service.py
│       ├── authorization_service.py
│       ├── case_closure_service.py
│       ├── case_decision_service.py
│       ├── case_ownership_service.py
│       ├── case_service.py
│       ├── case_workflow_service.py
│       ├── dive_session_service.py
│       ├── evidence_service.py
│       ├── location_service.py
│       ├── observer_report_service.py
│       ├── projection_service.py
│       ├── queue_service.py
│       ├── reference_service.py
│       └── report_service.py
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
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

CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,https://reefcare-frontend.vercel.app

LOGIN_RATE_LIMIT_REQUESTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60

SUPABASE_URL=<supabase project url>
SUPABASE_SECRET_KEY=<supabase secret>
SUPABASE_STORAGE_BUCKET=reefcare-evidence
```

### Important

- Never commit `.env`.
- Never commit database passwords, JWT secrets, or Supabase secrets.
- Production deployment should use `APP_ENV=production`.
- Application traffic should use the restricted application database role, not the Neon owner account.

---

## 5. Local Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
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

`expiresIn` is returned in **seconds**.

### Current user

```http
GET /api/v1/auth/me
Authorization: Bearer <accessToken>
```

### Register observer

```http
POST /api/v1/auth/register
Content-Type: application/json
```

Example:

```json
{
  "email": "newdiver@example.com",
  "displayName": "New Diver",
  "password": "ReefCare2026Test"
}
```

Self-registration always creates an **observer**. The request contains no role field.

---

## 7. Main API Endpoints

### Reference data

```text
GET /api/v1/reference/threat-categories
GET /api/v1/reference/dive-sites
```

### Dive Sessions

```text
GET  /api/v1/dive-sessions
POST /api/v1/dive-sessions
```

The observer ID comes from the authenticated token. Users cannot request another observer's sessions.

### Observation reports

```text
POST /api/v1/reports
GET  /api/v1/reports/mine
GET  /api/v1/reports/{reportReference}
GET  /api/v1/reports/{reportReference}/timeline
```

### Coordinator workflow

```text
GET  /api/v1/coordinator/queue
POST /api/v1/coordinator/reports/{reportReference}/claim
GET  /api/v1/coordinator/reports/{reportReference}
POST /api/v1/coordinator/reports/{reportReference}/information-request
POST /api/v1/coordinator/reports/{reportReference}/decision
POST /api/v1/coordinator/reports/{reportReference}/close
```

### Health

```text
GET /
GET /api/v1/health
```

---

## 8. Core Workflow

Iteration 1 supports the following vertical path:

```text
Login
  ↓
Create / select Dive Session
  ↓
Submit report
  ↓
Coordinator queue
  ↓
Atomic claim
  ↓
Owned case review
  ↓
Request more information or record decision
  ↓
Close case
  ↓
Observer views safe status / outcome / timeline
```

---

## 9. Database-Owned Workflow Rules

Critical workflow invariants are enforced in PostgreSQL.

Canonical functions include:

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
- Do not duplicate audit events already written by the database functions.
- Do not recreate PostgreSQL triggers/functions in an independent Alembic schema.
- The database remains authoritative for legal transitions, claim atomicity, closure rules, and protected workflow operations.

---

## 10. Case Status Codes

Canonical persisted status values include:

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
closed_no_action
closed_not_substantiated
closed_no_partner
closed_logged
```

Do not introduce a separate uppercase backend-only status vocabulary.

---

## 11. Decision and Closure Values

### Decision endpoint response types

```text
monitoring_only
refer_or_share
intervention_required
```

`no_responsible_partner` is handled through the closure path rather than exposed as a selectable decision value.

### Iteration 1 closure reason codes

```text
referred_other_org
monitored_no_action
not_substantiated
no_responsible_partner
logged_for_reference
```

---

## 12. Security Controls

Iteration 1 includes:

- modern password hashing;
- expiring signed JWT access tokens;
- authenticated role dependencies;
- observer/coordinator ownership checks;
- login and registration rate limiting;
- explicit production CORS allowlist;
- safe Pydantic response projections;
- precise reef-location access restrictions;
- private Supabase evidence storage;
- database-enforced claim, transition and closure workflow rules;
- global exception handling with safe error responses;
- environment-based secret management.

Precise locations must never be returned from public/reference endpoints.

---

## 13. CORS

Production frontend origin:

```text
https://reefcare-frontend.vercel.app
```

The backend uses an explicit `CORS_ORIGINS` allowlist. Avoid wildcard production origins.

When changing CORS environment variables in Vercel, redeploy the backend before testing again.

---

## 14. Evidence Handling

Evidence photos are:

- validated for supported media type;
- checked for file size and non-empty content;
- stored privately in Supabase Storage;
- referenced in PostgreSQL using controlled object metadata;
- removed from storage if the report workflow fails before successful completion.

Ordinary API responses must not expose private storage keys.

---

## 15. Error Behaviour

Expected HTTP behaviour includes:

```text
400  invalid workflow/input combination
401  unauthenticated / invalid credentials
403  authenticated but not authorised
404  resource not found or not owned
409  conflict / invalid state transition / duplicate claim
413  evidence file too large
422  request validation error
429  rate limit exceeded
500  safe internal/database failure
```

Global exception handlers are registered centrally in `app/core/exceptions.py`.

---

## 16. Testing

Core Iteration 1 flows have been tested through Swagger and Thunder Client.

Recommended smoke test after every integration merge:

```text
1. POST /auth/login
2. GET /auth/me
3. GET /reference/dive-sites
4. GET /dive-sessions
5. POST /reports
6. GET /coordinator/queue
7. POST /coordinator/reports/{reportReference}/claim
8. GET /coordinator/reports/{reportReference}
9. POST /coordinator/reports/{reportReference}/decision
10. POST /coordinator/reports/{reportReference}/close
11. GET /reports/mine
12. GET /reports/{reportReference}/timeline
```

Also test negative paths:

```text
401 unauthenticated
403 wrong role / wrong owner
404 missing report
409 duplicate claim / invalid transition
422 invalid request data
429 excessive login attempts
```

---

## 17. Development Workflow

Each feature should be developed on its own branch.

Recommended workflow:

```text
Work on own branch
        ↓
Finish feature
        ↓
Fetch latest main
        ↓
Merge main into own branch
        ↓
Resolve conflicts
        ↓
Run tests
        ↓
Push own branch
        ↓
Open Pull Request
        ↓
Review + CI
        ↓
Merge into main
```

Before starting a new feature:

```powershell
git checkout main
git pull origin main
git checkout -b feature/<feature-name>
```

---

## 18. Deployment

The backend is deployed on Vercel.

After environment-variable changes:

1. Update the correct Production / Preview environment variable.
2. Redeploy the backend.
3. Confirm the deployment is `Ready`.
4. Run a deployed smoke test against the frontend.

The backend and frontend are separate origins, so CORS must include the deployed frontend URL.

---

## 19. Current Iteration 1 Status

Implemented backend areas include:

- observer registration;
- login and authenticated user session;
- role-based access control;
- threat-category reference data;
- Dive Session creation/listing;
- safe location handling;
- report submission;
- private evidence upload;
- coordinator queue;
- atomic claim;
- owned case review;
- information requests;
- case decisions;
- case closure;
- observer My Reports;
- observer report detail;
- observer-safe timeline;
- global error handling;
- rate limiting;
- CORS configuration;
- deployed frontend/backend integration support.

---

## 20. Team

TM 18 Backend Team:

- **Hong Shen** — PM / Backend Engineer
- **Frank** — Backend Lead
- **Miusan** — Data Lead / Backend Engineer

---

## 21. Related Documentation

For detailed backend contracts, repository responsibilities, schemas, database functions, endpoint examples, and security/data-management rules, refer to:

```text
ReefCare Backend Documentation
Iteration 1
Updated 03 September 2026
```
