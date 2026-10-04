# Контракт первой реализации

Создаём локально запускаемую первую версию R0 по PLAN.md. Используем Next.js App Router и TypeScript в apps/web, FastAPI и SQLAlchemy в apps/api. PostgreSQL — рабочая база; SQLite — локальный режим без внешних сервисов. Начальные данные только демонстрационные, явно обозначены в интерфейсе. Платформа ещё не готова принимать реальные персональные данные и подписи.

## Общие соглашения

- API prefix `/api/v1`. JSON uses snake_case. IDs are UUID strings. UTC timestamps are ISO 8601; timezone names are IANA.
- Backend imports use `app.*`, launched from apps/api. SQLAlchemy sync Session dependency: `from app.database import get_db`. Models: `from app.models import ...`. Config: `from app.config import settings`. Authorization: `from app.auth import get_current_user, require_active, require_admin`. Routers under app/routers, each exports `router`. Parent wires them in app/main.py.
- Cookie session `dc_session`, HttpOnly, SameSite=Lax, Secure in production. Browser calls use same-origin `/api/v1` rewritten by Next to API server. Backend mutations check Origin against configured trusted origins. Frontend helper `api<T>(path, options?)` in src/lib/api.ts sends credentials and throws an ApiError with readable message. Paths passed to helper begin `/` and exclude `/api/v1` prefix.
- `get_current_user` validates session; `require_active` also checks active account, current required consent versions, completed/approved registration. Enrollment state is separate `intake_open`. Only admin can approve registration or change roles. Normal registration permits mentee or mentor.
- Common User private self response: id, email, full_name, role, account_status, intake_open, timezone, city, direction_ids, computed profile_completed, organization, mentor_commitment, mentor_commitment_accepted_at. Public mentor response excludes email, phone, birth_date, organization, commitment and review evidence. Live admission uses app.profile_state.admitted_profile; a legacy stored completion flag does not grant access.
- Lists return plain JSON arrays, bounded by limit/offset. Errors use `{detail: string}`. UI must show loading, empty, denied and error states. Avoid silently replacing failed live API calls with fixtures.

## Data model interface

Owner: data agent. Models export Base plus Direction, User, AuthChallenge, SessionToken, Document, DocumentVersion, Consent, RegistrationReview, Project, ProjectMember, Application, Participation, ParticipationEvent, Slot, Booking, Conversation, ConversationMember, Message, Result, Feedback, ShowcaseConsent, AuditEvent, Notification, Report.

Common fields (owner may add constraints and helper properties):

- Direction: id, slug, name_ru, name_kk, name_en, description_ru, active.
- User: id, email, full_name, role, account_status, intake_open, timezone, city, phone, birth_date, organization (300 chars), bio, expertise, evidence_urls (JSON), direction_ids (JSON), capacity, mentor_commitment (false by default), mentor_commitment_accepted_at (server UTC), profile_completed, created_at.
- AuthChallenge: id, email, code_hash, expires_at, attempts, consumed_at, created_at. SessionToken: id, user_id, token_hash, expires_at, created_at.
- Document: id, slug, title, required_roles (JSON), direction_id (nullable), scope (registration/intake/private_project/showcase), active. DocumentVersion: id, document_id, version, content, content_hash, published_at. Consent: id, user_id, document_version_id, accepted_at, method, ip_address, user_agent. UNIQUE(user_id,document_version_id).
- RegistrationReview: id, user_id, admin_id, decision, reason, created_at.
- Project: id, owner_id, mentor_id nullable, direction_id, title, problem, description, private_details, stage, required_skills (JSON), capacity, visibility_status (draft/pending/published/hidden), created_at.
- ProjectMember: id, project_id, user_id, member_role, joined_at. UNIQUE(project_id,user_id).
- Application: id, project_id nullable, mentee_id, mentor_id, initiator_role (mentee/mentor; legacy default mentee), motivation, status (pending/accepted/rejected/withdrawn), rejection_reason nullable, created_at. Participation: id, project_id nullable, mentee_id, mentor_id nullable, status, started_at, completed_at nullable. ParticipationEvent: id, participation_id, actor_id nullable, from_status, to_status, reason, created_at.
- Slot: id, mentor_id, starts_at, ends_at, timezone, status (available/booked/cancelled), created_at. Booking: id, slot_id, mentee_id, mentor_id, participation_id nullable, status (scheduled/completed/cancelled/no_show), meeting_url nullable, created_at. Protect active slot uniqueness at DB level; cancelled bookings may free slot.
- Conversation: id, application_id nullable, participation_id nullable, created_at. ConversationMember: id, conversation_id, user_id. Message: id, conversation_id, sender_id, body, created_at.
- Result: id, participation_id UNIQUE, status, exit_reason, initiator, artifact_url nullable, summary, meeting_count, verification_status (pending/verified), completed_at. Feedback: id, participation_id, author_id, target_role, rating, nps nullable, comment, created_at. UNIQUE(participation_id,author_id).
- ShowcaseConsent: id, project_id, user_id, accepted, updated_at. AuditEvent: id, actor_id nullable, action, entity_type, entity_id, detail (JSON), created_at.
- Notification: id, user_id, kind, title, body, read_at nullable, created_at. Report: id, reporter_id, entity_type, entity_id, reason, status, created_at.

## API routes

Identity owner:

- GET /health: `{status, environment, demo_mode}`.
- POST /auth/request-code `{email}` -> `{challenge_id, debug_code?}` (debug only explicit development config). POST /auth/verify-code `{challenge_id, code}` -> self user, set session cookie. POST /auth/logout. GET /auth/me.
- PUT /me/profile `{full_name, role?, timezone, city, phone?, birth_date?, organization?, bio, expertise?, evidence_urls?, direction_ids, capacity?, mentor_commitment?}` -> user. Only initially unchosen role may be set; later change admin only. Mentor completion requires phone, organization, expertise, at least one evidence link and explicit boolean commitment. Mentee requires birth date; organization and phone are optional. Acceptance time is read only and never accepted from the browser. Incomplete drafts cannot be submitted or admitted.
- POST /me/submit-registration -> user. GET /documents -> current applicable version objects `{id, document_id, title, slug, version, content, scope, required, accepted}`. POST /documents/{version_id}/consent -> consent.
- GET /directions -> array. GET /mentors -> public array (direction_id?, q?). GET /mentors/{id} -> public mentor. PATCH /me/intake `{intake_open, capacity?}`.
- GET /admin/registrations (role?, direction_id?, limit?, offset?) -> users under review with private fields. POST /admin/registrations/{id}/review `{decision: approved|changes_requested, reason}`. GET/POST/PATCH /admin/directions. GET /notifications and PATCH /notifications/{id}/read.
- Public /register, /register/mentee and /register/mentor show the same form fields as authenticated onboarding, with memory-only unsaved preview values. Email login and Google OAuth carry a bounded role hint; only initially unchosen participants may select that role when saving their profile.

Projects owner:

- GET /projects (direction_id?,stage?,q?,kind=ideas|projects?,limit?,offset?) -> public cards. `ideas` selects mentee-owned projects without an assigned mentor; `projects` selects projects with a mentor. Filtering precedes pagination. Public forum is `/forum`; `/projects` remains supported. GET /projects/mine. POST /projects `{title,problem,description,private_details?,direction_id,stage,required_skills,capacity}` -> pending project. GET/PATCH /projects/{id}. GET /projects/{id}/private -> authorized details with current NDA where applicable. GET /admin/projects; POST /admin/projects/{id}/review `{decision: published|hidden, reason}`.
- GET /applications (project_id?,limit?,offset?) -> current user's incoming/outgoing only, with `initiator_role`, `initiator_id`, and `decision_user_id`. Project filtering precedes pagination. POST /applications `{project_id?,mentor_id,motivation}` creates a mentee application. POST /projects/{id}/mentor-offers `{motivation}` creates a mentor offer for a published mentee idea without a mentor. The mentor must be admitted, have current consents, an open intake and available capacity, and share the direction. A pending request for the same pair/project cannot be duplicated across initiator roles. POST /applications/{id}/decision `{decision: accepted|rejected,reason?}` is restricted to the decision user: mentor for a mentee application, idea author for a mentor offer. Acceptance assigns the mentor and creates one participation and conversation atomically; competing requests are closed. POST /applications/{id}/withdraw is restricted to the initiator. Offers do not reveal private project details or bypass NDA.
- GET /participations -> current user's records, includes project_title and other party display names. GET /conversations; GET/POST /conversations/{id}/messages (body).

Bookings owner:

- GET /slots (mentor_id?,from_date?) -> array with mentor_name. POST /slots `{starts_at,ends_at,timezone}`; DELETE /slots/{id} only owner future available slot. GET /bookings -> own records with mentor_name/mentee_name, starts_at/ends_at. POST /bookings `{slot_id,participation_id?}`. POST /bookings/{id}/cancel. POST /bookings/{id}/complete (mentor only).
- Weekly recurring availability can initially be submitted as a bounded set of concrete UTC occurrences with IANA timezone; UI must label horizon accurately. No calendar recurrence is claimed unless rules truly persist.

Results owner:

- POST /participations/{id}/pause `{reason}`; POST /participations/{id}/resume. POST /participations/{id}/complete `{status: completed_successfully|completed_early,exit_reason,artifact_url?,summary}` -> Result. GET /results -> own/admin. POST /participations/{id}/feedback `{rating,nps?,comment}`. GET /exit-reasons -> array `{value,label}`.
- GET /showcase -> verified projects with active requisite consent. POST /projects/{id}/showcase-consent `{accepted}`. POST /admin/results/{id}/verify. GET /stats -> approved aggregate values (never seed presented as real impact). GET /admin/analytics; GET /admin/results/export -> CSV without contacts and spreadsheet injection.

## Frontend interfaces and ownership

- Shell agent owns apps/web package/config, src/app/layout.tsx, globals.css, home page, src/components/shell.tsx, ui.tsx, src/lib/api.ts, types.ts, i18n.ts and src/app/catalog/**. Provides AppShell wrapper, Button, Badge, Field, EmptyState, SectionHeading exports from ui.tsx.
- Workflows agent owns src/app/login/**, onboarding/**, dashboard/**, projects/**, calendar/**, messages/**, admin/**, showcase/**. Imports helpers and shared components; asks shell owner before changing shared files.
- Browser sessions are real cookies; development sample users authenticate through dev code. Show clear development/sample label. Do not call legal placeholders signed or legally valid.
- Branding is defined in DESIGN_BRIEF.md. No fabricated brand logo, photos, live-impact stats or claims of official deployment. Use existing available brand asset, otherwise a restrained text product name.

## Validation

Backend domain tests cover auth/rbac/consents, capacity and booking concurrency, application-to-participation mapping, structured completion, privacy and revoked showcase consent. Frontend build and type checking; browser visit and end-to-end sample user flow. Production hardening and remaining tasks are reported explicitly, not represented as complete.
