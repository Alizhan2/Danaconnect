# Women in Tech public refresh — 6 October 2026

Source commit: 54790ad4181740c5c7d54cd120cc28167c70fe99.
PR: https://github.com/Alizhan2/Danaconnect/pull/3.
Follow-up logo fix: f02313c1445d2cafe0a2de70589ff0c044280b2a, https://github.com/Alizhan2/Danaconnect/pull/4.

## Delivered requirements

1. Official Kazakhstan logo displayed whole, with DanaConnect secondary.
2. Full translated platform name in shared header/footer.
3. Mentors / Projects / Community / About / Join navigation.
4. Language order KZ / RU / EN, existing saved preference preserved.
5. Guest Log In / Get Started actions; authenticated workspace and notifications preserved.
6–8. Platform eyebrow, headline and description from supplied Word in three languages.
9. Hero actions open mentor and project catalogues.
10. Public mentor / participant / project counts, current consent eligibility, complete project count.
11. WIT palette and existing Poppins / Cyrillic Noto Sans pairing.
12. Light, non-animated connections illustration with decorative semantics.

Community is an overview of existing participation routes. No new social network or AI functionality is implied.

## Verification performed

- Focused API suite: 21 passed, including 12 new public summary tests.
- Local browser guest: RU/KZ/EN, complete logo, menu order and links; mobile menu and Escape.
- No horizontal overflow at 360, 390, 768, 1024 and 1440 px.
- About and Community routes; registration role chooser; renamed Projects heading.
- Separate empty test database returned real zeros. Stopped only the isolated API: summary showed dashes and retry. Restart and retry restored zeros.
- No production user records, consents or emails changed by this release.
- Full source CI 37490933055 / PR CI 37490981447: 429 API, 110 web, 26 admin tests; both frontend builds; PostgreSQL pilots 55 + 25 checks, 286 + 120 requests.
- Production HTTP acceptance: 72 checks, zero mismatches. Public summary additionally returns 200 with all three counts 0 and demo_mode false.
- Production authenticated mobile navigation verified at 360px; workspace, notifications and administration links remain accessible. No hidden platform-report link.

## Production correction

Initial production browser inspection caught a logo delivery failure in the Next image optimizer path. The original static file returned HTTP 200. The follow-up renders it directly (`unoptimized`), as the existing DanaConnect asset does; no image content was changed. Final visual verification must use the corrected deployment.

## Brand asset provenance

Source page: https://women-in-tech.org/kazakhstan/
Image: https://women-in-tech.org/wp-content/uploads/2024/11/Logo_WIT_Kazakhstan.png
Saved unchanged in apps/web/public/brand/wit-kazakhstan.png; SHA256 18BD2EDB75DFDEFB02FF21D2EE195614BF855A52139FDC0C21C0422B0D456C40.

The blue square background belongs to the official asset; the mark is not recoloured or cropped.

## Scope of evidence

This release checks the public refresh. It does not claim a new acceptance run of real participant registration, email delivery, OAuth or legal-document approval. Existing regression suites cover unchanged logic; legal gates remain in place.

## Final release result

- Final source commit: f02313c1445d2cafe0a2de70589ff0c044280b2a; merge: dba3a1c3183ed1652d875501d5d94ddbf152869b.
- Final CI: https://github.com/Alizhan2/Danaconnect/actions/runs/37491605007 and PR run 37491641267, all four jobs successful.
- Final deployment: dpl_CdMRwjC6Nx6Y6DN4YFBv16WasQDc.
- Deployment URL: https://danaconnect-qc55by07s-alizhan695-7132.vercel.app.
- Promoted to the platform at https://danaconnect.vercel.app/.
- Corrected production logo verified in browser: direct asset URL, natural width 4500, visibly intact.
- Final production desktop and 390px Kazakh mobile screenshots inspected; no horizontal overflow, signed-in workspace visible.
- Final HTTP acceptance rerun: 72 checks, zero failures.
- Private evidence: artifacts/verification/wit-home-production.png, wit-home-production-mobile.png, production-http-after-release.json.
- Local isolated servers on ports 3300 and 8008 stopped. No migration required.
