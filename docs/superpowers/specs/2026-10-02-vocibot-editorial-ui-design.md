# VociBot editorial clinical UI redesign

## Goal

Make the local-first clinical documentation app feel calm, modern, and premium while preserving the speed, visibility, and safety of an active consultation. The supplied visual references inform the mood: deep forest green, warm neutral surfaces, organic botanical forms, generous editorial typography, and restrained lime highlights.

## Non-negotiable constraints

- Patient data, editable notes, live audio controls, and status must remain high-contrast and free of photographic backgrounds.
- Botanical imagery is decorative and appears only in the landing/onboarding experience; it must not imply medical facts or obscure application controls.
- No network-loaded visual assets. The application remains usable offline.
- Existing accessible labels, keyboard behavior, runtime modes, tests, and clinical-record interactions remain intact.
- Responsive layouts retain a single-column experience on narrow screens.

## Visual system

- **Canvas:** warm mineral `#F1F1E9`; panels use a soft paper `#FBFBF7` rather than stark white.
- **Ink:** deep forest `#112A1B`, with charcoal body text and muted olive metadata.
- **Signal:** acidic fern/lime (`#B6E95F`) indicates local readiness, active processing, and updated data; red remains reserved for recording/stop/error states.
- **Typography:** system sans with tighter, oversized display headings; small mono-like uppercase labels for status and metadata.
- **Shape:** 18–24 px panel radii, fine low-contrast borders, diffuse rather than elevated shadows.
- **Botanical scene:** a CSS-only collage of blurred leaf/terrain gradients, fine grain, and translucent organic ellipses. It is an original abstract treatment, not a copy of the supplied images or an external image dependency.

## Information architecture

### App shell

The sidebar becomes a dark evergreen rail with a compact wordmark, clearly selected navigation, and a small local-first assurance at the bottom. It stays fixed-width on desktop and turns into a compact header/navigation row on mobile.

### Landing and intake

The landing surface becomes a two-column editorial hero. The left side contains a concise value proposition and the primary “New consultation” action. The right side is the abstract botanical visual with three quiet capability markers: Local processing, Multilingual speech, and Reviewable note. When intake opens, the same visual remains as a low-contrast side panel; the patient form is a single quiet paper card with one clear submit action.

### Active consultation

The workspace is reorganized into:

1. A compact patient masthead with patient identity, local-processing state, recording status, timer, and primary recording control.
2. A slim action bar that distinguishes the microphone action from the non-clinical demo action; secondary controls stay visually quiet.
3. Two equal, stable paper panels: Conversation and Draft note. Their headings, status chips, content density, form controls, and evidence labels are simplified and consistently aligned.
4. A lower audit/review region that does not compete with the live conversation.

During recording, the visual signal is a controlled red recording dot and a modest waveform/line animation; it does not use botanical decoration. Review and approved states use the green/lime system without looking like alerts.

## Component boundaries

- `AppShell`: dark navigation rail and privacy treatment only.
- `HomePage`: controls whether the editorial hero or intake card is shown.
- `ConsultationSetup`: semantic form markup remains unchanged; layout gains an onboarding frame/aside.
- `ConsultationWorkspace`: preserves provider/state behavior; groups existing controls into the masthead and action bar without API changes.
- `TranscriptPanel` and `ClinicalRecordPanel`: preserve content semantics and `data-testid` hooks, gain denser modern panel framing.
- `globals.css`: owns tokens, botanical CSS illustration, layouts, states, and responsive rules. No runtime image loading is needed.

## Data flow and error handling

The redesign changes presentation only. Consultation creation, local WebSocket transcription, final reconciliation, note edits, approval, and errors use their current data paths. Error banners remain immediately visible directly below controls, with the existing error text preserved.

## Responsive and accessibility behavior

- At desktop widths, the hero and workspace use balanced two-column compositions.
- Below 980 px, the workspace stacks Conversation before Draft note; landing art moves below the action/form rather than hiding required content.
- Below 680 px, navigation, controls, and status wrap without truncating labels. Form fields stack.
- Colour is never the only status indicator; all status chips retain text. Focus rings are high contrast, visible on the dark rail and light panels. Decorative botanical layers are hidden from assistive technology through CSS-only presentation.

## Verification

- Preserve and run frontend unit tests, backend tests, typecheck, lint, production build, and browser E2E tests.
- Add/adjust browser assertions only where visual structure affects semantic labels or runtime mode visibility.
- Inspect desktop and browser screenshots at desktop and mobile widths; verify that live microphone controls remain visible and usable.
- Repackage the macOS app and smoke-test the packaged loopback backend plus UI once the visual build is complete.
