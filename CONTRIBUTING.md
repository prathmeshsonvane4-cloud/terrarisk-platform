# Contributing to TerraRisk

TerraRisk is an early-stage product built for a single pilot customer
(DCCB Latur) — the priorities right now are pilot stability and the
farmer-facing roadmap, not a broad open-source contributor base. That
said, issues and pull requests are welcome, especially for bugs,
documentation gaps, and test coverage.

## Before you start

- Read [`docs/DECISIONS.md`](docs/DECISIONS.md) first — it's the running
  log of every architectural decision and why it was made. A change that
  contradicts a logged decision needs to either respect the reasoning
  behind it or open a discussion about revisiting it, not silently
  override it.
- Check [`docs/Product_Design_v2.md`](docs/Product_Design_v2.md) for the
  product's design philosophy before proposing UI/UX changes.
- This project explicitly avoids fabricating data: any score, chart, or
  report value must trace back to a real computed or persisted input.
  "Data unavailable" is always preferred over an invented number.

## Development setup

See [`docs/Getting_Started.md`](docs/Getting_Started.md) for local setup
(backend, frontend, PostGIS) and [`docs/Deployment_Guide.md`](docs/Deployment_Guide.md)
for production deployment.

## Making a change

1. Open an issue first for anything beyond a small fix — this project
   moves fast and a short discussion up front avoids wasted work.
2. Write tests for new behavior. The backend suite currently sits at
   192/192 passing; a PR that drops coverage without a stated reason
   won't be merged.
3. Keep commits focused and the message explaining *why*, not just *what*
   — match the existing commit history's style.
4. Run the full test suite locally before opening a PR:
   ```bash
   cd backend && pytest
   cd frontend && npm test && npm run build
   ```

## Code style

- Backend: Python, FastAPI, SQLAlchemy (async), Pydantic v2. Follow the
  existing service/schema/API layering — business logic belongs in
  `app/services/`, not in route handlers.
- Frontend: Next.js 15, TypeScript, Tailwind. Match existing component
  patterns before introducing a new one.
- No comments explaining *what* code does when the code already makes
  that clear — comments should carry a non-obvious *why*.

## Reporting a security issue

Please do not open a public issue for a security vulnerability — contact
the maintainer directly instead.
