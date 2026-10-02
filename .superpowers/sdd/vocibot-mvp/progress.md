# SDD ledger — plan: docs/superpowers/plans/2026-09-26-vocibot-mvp.md

Ruling: Use FastAPI/Python for the backend per the user's latest approved technical architecture; replace Prisma route handlers with SQLAlchemy services and keep the same JSON contracts.

Pre-flight: Tasks 2 consumes Task 1 domain types; Task 3 consumes Tasks 1–2 schemas/providers; Task 4 consumes Task 3 API contracts; Task 5 consumes Tasks 3–4 approval/state contracts; Task 6 consumes the complete application. No unresolved interface conflicts found.

Task 1: complete — tests: `npm test -- tests/setup.test.ts` → 1 passed; `.venv/bin/pytest backend/tests/test_setup.py -q` → 1 passed.

Task 2: complete — tests: `.venv/bin/pytest backend/tests/test_extraction.py backend/tests/test_record_diff.py -q` → 5 passed; `npm test -- tests/extraction.test.ts tests/record-diff.test.ts` → 2 passed.

Task 3: complete — tests: `.venv/bin/pytest backend/tests/test_consultation_flow.py -q` → 4 passed; `npm test -- tests/consultation-flow.test.ts` → 1 passed.

Task 4: complete — tests: `npm run typecheck` → passed; `npm run test:e2e -- tests/browser/vocibot.spec.ts` → 1 passed.

Task 5: complete — tests: `npm run typecheck` → passed; `npm run test:e2e -- tests/browser/vocibot.spec.ts` → 1 passed, including stop, doctor edit, approval, history, detail, and evidence assertions.

Task 6: complete — tests: `npm run lint` → 0 errors; `npm run typecheck` → passed; `npm test` → 4 passed; `.venv/bin/pytest -q` → 11 passed; `npm run build` → passed; `npm run test:e2e` → 1 passed; `git diff --check` → clean.

Final review: self-review (no subagent tool) — reviewed the full branch against the approved spec and plan; upgraded local STT/VAD adapters to lazy-loaded implementations; reran lint, typecheck, unit tests, pytest, production build, and browser acceptance flow.
