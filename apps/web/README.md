# Web Application

Next.js frontend for the ResolveAI customer support SaaS: the agent web app (sign-up,
login, workspace switching, settings, and the dashboard shell that later features plug into).

- Next.js 16 (App Router, `src/`), TypeScript strict, Tailwind CSS v4, ESLint
- shadcn/ui (Radix), restyled with the tokens in [DESIGN.md](./DESIGN.md)
- TanStack Query for server state; react-hook-form + zod for forms
- Typed API client: `openapi-typescript` + `openapi-fetch`

## Run it

Prerequisites: Node 20+, and the API running on port 8000 (see `services/api/README.md`).

```bash
cd apps/web
cp .env.example .env.local   # optional; API_URL defaults to http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
```

The browser only talks to `localhost:3000`. `next.config.ts` rewrites `/api/*` to
`${API_URL}/api/*`, so the refresh cookie (scoped to `/api/v1/auth`) is first-party and no
CORS setup is needed.

## Scripts

| Script | What it does |
| --- | --- |
| `npm run dev` | Dev server on port 3000 |
| `npm run build` / `npm start` | Production build and server |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run gen:api` | Regenerates `src/lib/api/schema.d.ts` from `http://localhost:8000/openapi.json` (API must be running). Commit the result. |

## How auth works here

- The access token is kept **in memory only** (`src/lib/auth/session-store.ts`), never in
  localStorage or sessionStorage.
- On load, `AuthProvider` calls `POST /api/v1/auth/refresh` (using the httpOnly cookie), then
  `GET /api/v1/auth/me`. A glass loading screen shows until that finishes.
- `src/lib/api/client.ts` adds the bearer token to every request. On a 401 from any non-auth
  endpoint, it refreshes once and retries the request once. Concurrent 401s share a single
  refresh call, because the API treats reuse of a rotated refresh token as theft. If the
  refresh fails, the session is cleared and the `(app)` guard sends the user to
  `/login?next=<path>`.
- Cached query data is keyed by workspace id and dropped on login, logout and workspace
  switch.

## Layout

```
src/
  app/
    (auth)/login, (auth)/signup    two-column auth screens with the product preview
    (app)/dashboard, settings, tickets, approvals, conversations, knowledge
    layout.tsx, providers.tsx, globals.css (design tokens)
  components/
    ui/          restyled shadcn components
    shell/       sidebar, top bar, workspace switcher, user menu
    auth/, dashboard/, settings/
  lib/
    api/         client, generated schema, query hooks, error copy
    auth/        session store and AuthProvider
```

Never hardcode API URLs in components. Every call goes through `api` from `@/lib/api/client`.
