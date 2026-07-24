# Changelog

All notable changes to TerraRisk, grouped by development milestone.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Enterprise Climate Credit Report v2** — the PDF report redesigned from
  a 1–2 page summary into a 7-section report (Executive Summary, Risk
  Dashboard, Historical Analysis, Climate Outlook, Farm Intelligence,
  Methodology, Audit Appendix), including a deterministic Credit
  Recommendation, per-factor trend vs. the prior assessment, and an
  annotated farm map (north arrow, scale bar, coordinates).

### Fixed
- Map rendering invisible in production due to a CSS cascade-order bug
  between MapLibre's own styles and Tailwind's utility classes.
- Report generation jobs could get stuck indefinitely if the Earth Engine
  provider failed to construct, with no error surfaced to the user.
- Windows-authored shell scripts corrupted by CRLF line endings on the
  Linux deployment target.

## [1.0.0-rc2] — 2026-07-18 — Production Readiness Audit

### Added
- Docker Compose production deployment, nginx reverse proxy with TLS
  termination and rate limiting, health checks (`/health`, `/health/ready`).
- `create_admin_user.py` provisioning script.
- Deployment and Getting Started guides.

### Fixed
- Reliability, security, and diagnostics issues found during a structured
  production-readiness audit (connection pool `pool_pre_ping`, nginx
  rate-limit gaps, a job-reaper edge case).

### Security
- RC1 audit: fixed an IDOR (insecure direct object reference) on the
  report-trigger endpoint and added a vertex cap on submitted farm
  polygons to bound worst-case processing cost.
- M1 hardening: fixed a Google Earth Engine service-account IAM
  over-privilege issue and a separate IDOR, removed dead stub endpoints,
  and moved several defaults to secure-by-default values.

## [0.11.0] — 2026-07-17 — Workspace UX Polish (M2B P11)

### Changed
- Consolidated 8 duplicated risk-band chip implementations into one
  shared component with a threshold-range tooltip.
- Added print styles to the report page; fixed a responsive layout bug
  in the Method tab below 640px width.

## [0.10.0] — 2026-07-17 — Wizard & Session Hardening (M2B P10)

### Added
- Per-officer persistent assessment drafts with Resume/Discard.
- A 4-step guided wizard combining farm creation and report triggering.
- Sliding-session JWT refresh with a client-side expiry warning.

## [0.9.0] — 2026-07-14 — Evidence & Method Tabs (M2A/M2B P9)

### Added
- Evidence tab (which satellite observations contributed to a score) and
  Method tab (weights, floor rule, plain-English methodology) on every
  report, plus a deterministic band-and-confidence-keyed Recommendation.

## [0.8.0] — 2026-07-14 — Honest Execution Timeline (M2A/M2B P8)

### Added
- Real, server-recorded job progress checkpoints replacing any
  simulated/animated loading state — the frontend renders only actual
  pipeline stage transitions.

## [0.7.0] — 2026-07-13 — Workspace Foundation (M2B P7)

### Added
- Workspace list endpoints and shell: farms, assessments, jobs, and
  reports, all owner-or-branch scoped, with four index/detail routes on
  the frontend.

## [0.6.0] — 2026-07-12 — PDF Report Export (M2A P6)

### Added
- First version of the server-rendered, cached PDF report (ReportLab +
  matplotlib), covering branding, farm info, score/band/confidence, a
  four-factor card grid, two charts, and the farm boundary map.

## [0.5.0] — 2026-07-12 — Report Dashboard (M2A P5)

### Added
- The web dashboard's charts, narrative summary, and read-only farm map.

## [0.4.0] — 2026-07-12 — Async Report Workflow (M2A P4)

### Added
- Trigger-and-poll report generation as a background job with status
  tracking.

## [0.1.0]–[0.3.0] — 2026-07-11 — Farm Creation Flow (M2A P0–P3)

### Added
- Frontend foundations (auth shell, typed API client), village search
  against real Latur-district data, an interactive farm-boundary-drawing
  map, and the area-confirmation/save flow.

## [0.0.1] — 2026-07-09 to 2026-07-11 — MVP Foundations (M0–M1)

### Added
- Database schema, authentication, the Google Earth Engine adapter, the
  farm-boundary pipeline, and the core farm→report backend service —
  the foundation everything above was built on.
