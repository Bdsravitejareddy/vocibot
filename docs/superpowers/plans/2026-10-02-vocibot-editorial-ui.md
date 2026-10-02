# VociBot Editorial UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a modern, calm, botanical editorial UI for VociBot without changing the local clinical workflow or its offline behavior.

**Architecture:** Keep all clinical state, local transcription, and API behavior intact. Update the semantic React composition in the app shell, landing/intake flow, and consultation workspace, with `globals.css` as the single owner of design tokens, botanical CSS art, responsive breakpoints, and component presentation.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind import plus project CSS, Lucide icons, Playwright, Node test runner, Electron Builder.

**Spec:** `docs/superpowers/specs/2026-10-02-vocibot-editorial-ui-design.md`

## Global Constraints

- Keep patient data, editable notes, controls, and statuses high-contrast and free of photographic backgrounds.
- Implement original CSS-only botanical decoration; do not add network-loaded assets or copy supplied reference images.
- Preserve offline operation, existing accessible labels, keyboard behavior, runtime modes, `data-testid` hooks, and clinical API interactions.
- Keep a two-column desktop workspace and a single-column workspace below 980 px; preserve usable wrapping below 680 px.
- Keep red exclusive to recording/stop/error states; use forest green, paper, and lime for the new system.

## Review Focus

- Local runtime mode: “Start local AI”, runtime status, microphone permission, and recording controls remain visible after the new hierarchy; covered in Task 3’s existing/extended local-audio browser test.
- Demo runtime mode: the demo action is still distinct and works without a microphone; covered in Task 3’s existing demo browser test.
- Narrow screens: no patient-control or form label is clipped at 390 px; covered by Task 4’s mobile Playwright screenshot/visibility test.
- Form semantics: all original consultation form labels and submit behavior remain usable in the redesigned intake card; covered in Task 2’s browser test.
- Decorative isolation: no image URL or decorative layer is rendered in the workspace panels; covered in Task 1’s component/browser assertion and CSS review.

---

## File structure

- Modify `src/app/globals.css`: define editorial tokens, dark rail, CSS-only botanical scene, paper panels, recording state, and responsive layout rules.
- Modify `src/components/AppShell.tsx`: add semantic styling hooks for the compact dark navigation rail and local-first footer.
- Modify `src/app/page.tsx`: add semantic styling hooks and capability markers for the landing hero.
- Modify `src/components/ConsultationSetup.tsx`: wrap intake form in the approved onboarding composition while preserving labels and submission behavior.
- Modify `src/components/ConsultationWorkspace.tsx`: regroup existing controls into masthead/action-bar hooks without changing provider calls or state behavior.
- Modify `src/components/TranscriptPanel.tsx` and `src/components/ClinicalRecordPanel.tsx`: add panel-specific hooks only if required for the specified visual hierarchy; preserve their current data contracts.
- Modify `tests/browser/runtime-mode.spec.ts`, `tests/browser/local-audio.spec.ts`, and/or add `tests/browser/editorial-ui.spec.ts`: pin semantic structure, local/demos paths, and narrow-width visibility.

### Task 1: Design foundations and navigation rail

**Files:**
- Modify: `src/app/globals.css`
- Modify: `src/components/AppShell.tsx`
- Test: `tests/browser/editorial-ui.spec.ts`

**Interfaces:**
- Consumes: `AppShell({ children: React.ReactNode })` and existing navigation URLs.
- Produces: stable `data-testid="editorial-sidebar"` and `data-testid="botanical-scene"` hooks for browser verification; no new runtime API.

- [ ] **Step 1: Write the failing desktop-shell browser test**

```ts
test("editorial shell presents a local-first rail without workspace decoration", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("editorial-sidebar")).toBeVisible();
  await expect(page.getByText("Local-first")).toBeVisible();
  await expect(page.locator(".workspace [data-testid='botanical-scene']")).toHaveCount(0);
});
```

- [ ] **Step 2: Run the shell test to verify it fails**

Run: `npx playwright test tests/browser/editorial-ui.spec.ts --grep "editorial shell"`

Expected: FAIL because the new semantic hooks do not exist.

- [ ] **Step 3: Implement the dark editorial rail and CSS design tokens**

Add the paper, forest, lime, red, border, focus, typography, and radius tokens in `globals.css`. Add only semantic class/test hooks needed by the test to `AppShell.tsx`; keep links, icons, text, and `main` semantics unchanged. Build a CSS-only `botanical-scene` that can be reused only by onboarding.

- [ ] **Step 4: Run the shell test to verify it passes**

Run: `npx playwright test tests/browser/editorial-ui.spec.ts --grep "editorial shell"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/globals.css src/components/AppShell.tsx tests/browser/editorial-ui.spec.ts
git commit -m "feat: establish editorial navigation shell"
```

### Task 2: Botanical landing and accessible patient intake

**Files:**
- Modify: `src/app/page.tsx`
- Modify: `src/components/ConsultationSetup.tsx`
- Modify: `src/app/globals.css`
- Test: `tests/browser/editorial-ui.spec.ts`

**Interfaces:**
- Consumes: Task 1’s `botanical-scene` styling hook and the existing `ConsultationSetup` `onStart` input contract.
- Produces: desktop landing hero, capability markers, and form/onboarding layout with unchanged labels and submit action.

- [ ] **Step 1: Write the failing landing and intake test**

```ts
test("landing opens a labelled patient intake card beside the botanical scene", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("botanical-scene")).toBeVisible();
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(page.getByLabel("Patient ID")).toBeVisible();
  await expect(page.getByLabel("Conversation language")).toBeVisible();
});
```

- [ ] **Step 2: Run the landing test to verify it fails**

Run: `npx playwright test tests/browser/editorial-ui.spec.ts --grep "patient intake"`

Expected: FAIL because the landing visual and intake composition hooks do not exist.

- [ ] **Step 3: Implement the landing hero and intake composition**

Use concise landing copy, a CSS botanical visual on the non-data side, and three plain-language markers: “Local processing”, “Multilingual speech”, and “Reviewable note”. Keep every original form label, validation message, and runtime-status content in the rendered intake form.

- [ ] **Step 4: Run the landing test to verify it passes**

Run: `npx playwright test tests/browser/editorial-ui.spec.ts --grep "patient intake"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/page.tsx src/components/ConsultationSetup.tsx src/app/globals.css tests/browser/editorial-ui.spec.ts
git commit -m "feat: redesign consultation onboarding"
```

### Task 3: Focused live consultation workspace

**Files:**
- Modify: `src/components/ConsultationWorkspace.tsx`
- Modify: `src/components/TranscriptPanel.tsx`
- Modify: `src/components/ClinicalRecordPanel.tsx`
- Modify: `src/app/globals.css`
- Test: `tests/browser/local-audio.spec.ts`
- Test: `tests/browser/vocibot.spec.ts`

**Interfaces:**
- Consumes: current `ConsultationWorkspace` provider lifecycle, `TranscriptPanel` props, `ClinicalRecordPanel` props, labels, and test IDs.
- Produces: masthead, action bar, panel hierarchy, and review/approved states with unchanged operational controls.

- [ ] **Step 1: Extend the failing browser tests for structural and operational invariants**

```ts
await expect(page.getByTestId("consultation-masthead")).toBeVisible();
await expect(page.getByRole("button", { name: "Start local AI" })).toBeVisible();
await expect(page.getByText("Live transcript")).toBeVisible();
await expect(page.getByText("Structured clinical record")).toBeVisible();
```

Keep the current local recording/finalization and demo transcript assertions in place.

- [ ] **Step 2: Run the targeted browser tests to verify they fail**

Run: `npm run test:e2e -- --grep "local microphone|demo consultation"`

Expected: FAIL because `consultation-masthead` is absent.

- [ ] **Step 3: Implement the masthead, action bar, and paper-panel hierarchy**

Add a `data-testid="consultation-masthead"` wrapper around the existing patient/status content. Reorder and style existing buttons so local microphone is primary in local mode and demo remains secondary. Preserve every existing click handler, disabled condition, error banner, transcript content, record input, evidence label, review action, and approved state.

- [ ] **Step 4: Run the targeted browser tests to verify they pass**

Run: `npm run test:e2e -- --grep "local microphone|demo consultation"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/ConsultationWorkspace.tsx src/components/TranscriptPanel.tsx src/components/ClinicalRecordPanel.tsx src/app/globals.css tests/browser/local-audio.spec.ts tests/browser/vocibot.spec.ts
git commit -m "feat: modernize live consultation workspace"
```

### Task 4: Responsive polish and release verification

**Files:**
- Modify: `src/app/globals.css`
- Test: `tests/browser/editorial-ui.spec.ts`

**Interfaces:**
- Consumes: the semantic hooks produced by Tasks 1–3.
- Produces: tested 390 px mobile presentation and a package-ready production build.

- [ ] **Step 1: Write the failing narrow-width visibility test**

```ts
test("editorial intake and local controls remain usable at narrow width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New consultation" })).toBeVisible();
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(page.getByLabel("Patient ID")).toBeVisible();
});
```

- [ ] **Step 2: Run the narrow-width test to verify it fails**

Run: `npx playwright test tests/browser/editorial-ui.spec.ts --grep "narrow width"`

Expected: FAIL if the new responsive hooks/styles do not keep the required controls visible.

- [ ] **Step 3: Implement responsive layout and focus refinements**

At 980 px stack workspace panels and move the botanical scene below essential onboarding content. At 680 px collapse the rail into a compact header/navigation row, stack form fields, wrap actions, and retain visible focus rings on light and dark surfaces.

- [ ] **Step 4: Run focused visual and behavior verification**

Run: `npx playwright test tests/browser/editorial-ui.spec.ts && npm run typecheck && npm run lint`

Expected: PASS with no type or lint errors.

- [ ] **Step 5: Run complete release verification and package**

Run: `.venv/bin/pytest -q && npm test && npm run build && npm run test:e2e && npm run desktop:pack`

Expected: all suites pass and `dist/mac-arm64/VociBot.app` is rebuilt.

- [ ] **Step 6: Smoke-test the packaged app and commit**

Run: `open -n dist/mac-arm64/VociBot.app`, then confirm `http://127.0.0.1:8000/health` returns `{"status":"ok"}` and `http://127.0.0.1:3000/` returns HTTP 200; close the parent app process gracefully afterward.

```bash
git add src/app/globals.css tests/browser/editorial-ui.spec.ts
git commit -m "feat: finalize responsive editorial UI"
```

## Self-review

- **Spec coverage:** Tasks 1–2 implement the visual system, rail, landing, intake, and original CSS-only botanical treatment. Task 3 covers the consultation masthead, action hierarchy, paper panels, recording/review states, and unchanged workflow. Task 4 covers the two required breakpoints, accessibility focus behavior, full verification, packaging, and desktop smoke test.
- **Step scan:** Every task begins with an exact failing assertion and command, introduces only scoped markup/CSS behavior, then reruns the proving command.
- **Type consistency:** No new application data interface is introduced. All referenced hooks are exact string test IDs; component props and existing API/provider contracts are preserved.
- **Review focus:** Local mode, demo mode, narrow screens, form semantics, and isolation of botanical decoration are assigned to concrete tests in Tasks 1–4.
- **Proportion:** The plan specifies interfaces and visible outcomes without prescribing CSS implementation bodies.
