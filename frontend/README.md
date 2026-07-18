# TerraRisk Frontend

Next.js web application for **TerraRisk** — the credit-officer workspace
for farm-level climate risk assessment (Service 1) and, in progress,
portfolio-level risk dashboards (Service 2). See the repo-root
[README](../README.md) for the product overview and [`../docs`](../docs)
for the full engineering record.

## Tech stack

- [Next.js 15](https://nextjs.org/) (App Router, Turbopack)
- [React 19](https://react.dev/) + TypeScript
- [Tailwind CSS v4](https://tailwindcss.com/) + [shadcn/ui](https://ui.shadcn.com/)
- [TanStack Query](https://tanstack.com/query) for server-state
- [MapLibre GL JS](https://maplibre.org/) + [Terra Draw](https://github.com/JamesLMilner/terra-draw) for the farm-boundary map
- [openapi-fetch](https://openapi-ts.dev/openapi-fetch/) + [openapi-typescript](https://openapi-ts.dev/) for a contract-first, typed API client
- [Vitest](https://vitest.dev/) for tests

## Structure

```
src/
├── app/
│   ├── (app)/       # authenticated workspace: overview, assessments, farms, reports
│   └── (public)/    # unauthenticated routes: login
├── components/      # shared UI (map, charts, workspace widgets, shadcn primitives)
├── features/        # feature-scoped logic: auth, farm-drawing, assessment(-wizard), report, workspace, navigation-guard
└── lib/
    └── api/          # generated OpenAPI types (schema.d.ts) + the typed client (client.ts)
```

## Routing

Next.js App Router with two route groups sharing the `app/` tree but
different layouts: `(app)` is the authenticated officer workspace
(overview, `/assessments`, `/assessments/new`, `/assessments/[jobId]`,
`/farms`, `/farms/[id]`, `/reports`, `/reports/[id]`); `(public)` is
unauthenticated (`/login`). `features/navigation-guard` enforces the
authenticated/unauthenticated boundary client-side; the backend enforces it
independently on every request (bearer JWT), so the guard is a UX
convenience, not the actual access-control boundary.

## State management

- **Server state** (anything from the API): TanStack Query — caching,
  polling (job status), and mutation state all go through it, never raw
  `useEffect` + `fetch`.
- **Session**: a bearer JWT + role + officer name in `localStorage`
  (`features/auth/session.ts`), attached to every request via an
  `Authorization: Bearer` header. A deliberate, documented pilot trade-off
  — see [`docs/DECISIONS.md`](../docs/DECISIONS.md) for why (not an
  httpOnly cookie yet) and the planned migration path.
- **In-progress assessment drafts**: `features/assessment-wizard/draft-storage.ts`
  persists wizard state locally so a session interruption (e.g. a 401
  mid-work) doesn't silently discard an officer's in-progress work.

## API client

Never hand-typed. `npm run generate:api` runs `openapi-typescript` against
the backend's live `/openapi.json` and writes `src/lib/api/schema.d.ts`
(committed, so a fresh checkout typechecks without a running backend).
`src/lib/api/client.ts` wraps the generated `openapi-fetch` client with
bearer-token injection and a 401 → clear-session-and-redirect interceptor.
Whenever the backend's API shape changes, regenerate before relying on the
new shape:

```bash
npm run generate:api
```

The target URL (`http://127.0.0.1:8000/openapi.json`) is hardcoded in
`package.json`'s script, independent of `NEXT_PUBLIC_API_BASE_URL` — it
always requires a backend running locally on the default port, regardless
of what `NEXT_PUBLIC_API_BASE_URL` is set to.

`NEXT_PUBLIC_API_BASE_URL` is a Next.js public env var — inlined into the
client bundle at **build time**, not read at runtime. Locally it defaults
to the local backend (`http://127.0.0.1:8000`); in the production Docker
image it's a build `ARG` (empty/relative by default, since nginx proxies
`/api/` on the same origin — see [`docs/Deployment_Guide.md`](../docs/Deployment_Guide.md)).

## Development

```bash
npm install
cp .env.example .env.local   # then adjust if the backend isn't on the default port
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Requires the backend
running (see `../backend/README.md`) for anything beyond the login screen.

## Testing

```bash
npm test          # vitest (pure-logic + one real-stack integration test)
npx tsc --noEmit  # typecheck
npm run lint       # eslint
npm run build      # production build
```

Most tests run in a node environment (no DOM) for pure logic (geometry,
formatting). One jsdom-based integration test drives the real farm-creation
flow against a real local backend and skips cleanly when that stack isn't
available — see [`docs/DECISIONS.md`](../docs/DECISIONS.md) for why the map
canvas itself is the one mocked seam.

## Production build

```bash
npm run build   # next build --turbopack, output: "standalone" (next.config.ts)
npm run start   # serve the production build locally
```

The production Docker image (`Dockerfile`) builds this standalone output
and runs it with plain `node server.js` — never `next dev` in production.

## License

Private — TerraRisk © 2026
