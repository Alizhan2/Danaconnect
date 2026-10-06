# Public community design release — 2026-10-06

## Delivered
- Compact WIT / DanaConnect header with full platform name and mobile navigation.
- Shorter mentor catalogue introduction; larger mentor names, descriptions, tags and detail labels.
- Light profile surfaces and consistent public buttons, fields and registration role cards.
- Project publication-type buttons using existing API filters; compact editorial project rows.
- Approved homepage copy, three languages, authentication and consent behavior preserved.

## Release evidence
- Source: `636788aa5d46d6619d82d9f8d3489daa7b60919d`.
- PR: https://github.com/Alizhan2/Danaconnect/pull/7 (merged).
- Merge: `c7aac4b7d952efc90676853f0e7256bdab6db7c0`.
- GitHub checks: push `37501721872`, PR `37501745142`, both successful (web, admin, API, PostgreSQL concurrency).
- Vercel: `dpl_GzU21uDWro12Kmk8dyk9pt5x7zjW`, Ready, production promoted.
- Build URL: https://danaconnect-bg6ytsgys-alizhan695-7132.vercel.app
- Public URL: https://danaconnect.vercel.app

## Verification
- Web TypeScript check passed.
- Existing local tests: demo mentors 14, registration 22, mobile navigation 5, frontend 23; 64 passed.
- Local Chrome: desktop and 390×850, catalogue filter and profile, project filters, registration roles and mentor fields.
- RU/KZ/EN project filter labels and registration forms checked; no horizontal overflow in checked mobile views. Mentor commitment remained unchecked.
- Local header measured ~123px desktop and ~129px mobile, versus previously observed ~199px / ~220px.
- Desktop demo intro measured ~182px versus previous ~370px.
- Filled project row checked using one synthetic project and owner in an isolated temporary SQLite database. No synthetic records written to production.
- Production HTTP 200: `/`, `/demo/mentors`, `/projects`, `/register/mentor`; updated public shell present in HTML.
- Production browser catalogue: six labelled fictional profiles, updated header/intro, no horizontal overflow; both brand images loaded with nonzero natural width.
- Screenshot: `artifacts/verification/community-design-production.png` (local ignored artifact).

## Scope and limits
- No new real mentor photos or production records added.
- Browser automation intermittently timed out during production navigation/scroll; recovered sufficiently to inspect and capture the catalogue. Full production account/registration submission was not repeated for this visual release.
- Research and rationale: `docs/DESIGN_ANALOGUES_REVIEW_2026-10-06.md`.
