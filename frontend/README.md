# TerraRisk AI — Frontend

Next.js landing page and web application for **TerraRisk AI** — a deep-tech startup delivering intelligent terrain and geospatial risk analytics.

## Tech Stack

- [Next.js 15](https://nextjs.org/) (App Router)
- [React 19](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/)
- [Tailwind CSS v4](https://tailwindcss.com/)
- [shadcn/ui](https://ui.shadcn.com/)

## Getting Started

From the `frontend/` directory:

Install dependencies:

```bash
npm install
```

Run the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Scripts

| Command         | Description              |
| --------------- | ------------------------ |
| `npm run dev`   | Start dev server (Turbopack) |
| `npm run build` | Production build         |
| `npm run start` | Start production server  |
| `npm run lint`  | Run ESLint               |

## Deploy on Vercel

Set the **Root Directory** to `frontend` when importing this monorepo on [Vercel](https://vercel.com/new).

Alternatively, use the Vercel CLI from this directory:

```bash
npx vercel
```

## Project Structure

```
src/
├── app/                  # Next.js App Router pages & layout
├── components/
│   ├── landing/          # Landing page sections
│   └── ui/               # shadcn/ui components
└── lib/                  # Utilities
```

## License

Private — TerraRisk AI © 2026
