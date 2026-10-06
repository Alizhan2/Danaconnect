# Mentor discovery design — 6 October 2026

Source: cbfc0a32ea16bb70a00afe84bbaccd8a7b39bd1a.
Pull request: https://github.com/Alizhan2/Danaconnect/pull/5.

The public mentor catalogue and the explicitly fictional demo catalogue now share a dedicated card presentation. Names, specialisms, intake status, introductory text and profile action have distinct visual roles. Search and field filters are grouped in a separate column, stacking above results on mobile. The public catalogue additionally supports filtering by open intake and clearing all filters.

The change uses the existing Lucide icons and WIT colours. No dependencies were added. No portraits or real participant data were fabricated. The public card labels capacity as group capacity; only demo fixtures show calculated available places, since the public Mentor API does not supply occupied places.

## Verification

- 14 existing demo behaviour tests passed after the harness was updated to execute the extracted card component.
- Web TypeScript passed after regenerating local Next route types; the initial check detected stale generated route definitions.
- Browser: RU/KZ/EN, search for Python, combined direction/availability filtering, empty results, reset and demo profile navigation.
- No horizontal overflow at 360/390/768/1024/1440 px. Kazakh cards visually inspected at 390px.
- Real catalogue empty state inspected using an isolated empty test database; no browser console errors observed.

## Scope

This is a first design iteration for catalogue discovery. Detailed profiles and registration forms keep their existing presentation. Photo uploads and other product features require separate work.

## Published result

- Merge: ac02b7cb01290bfceecc8770b3843d0500f34872.
- CI runs 37494637339 and 37494673988: all API, web, admin and PostgreSQL concurrency jobs passed; web and admin production builds passed.
- Deployment: dpl_6pdUStsXgne1toMSuc3Qh39hniGS, promoted to https://danaconnect.vercel.app/.
- Design preview with fixtures: https://danaconnect.vercel.app/demo/mentors.
- Real catalogue: https://danaconnect.vercel.app/catalog.
- Five selected production GET checks returned 200: catalogue, demo catalogue, demo profile, official logo, API health. Catalogue server HTML contains the existing Suspense fallback; its final design and data were verified in browser after hydration.
- Production browser: six marked demo cards, no console errors; real catalogue loads IT, Education and Psychology directions and real empty state. Kazakh mobile catalogue at 390px has no overflow.
- Screenshot: artifacts/verification/mentor-design-production.png. Read-only HTTP evidence: artifacts/verification/mentor-design-http.json.
- Isolated local servers on ports 3330 and 8008 stopped.
