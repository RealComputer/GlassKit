# Repository Guidelines

## Technology Stack
This web UI currently uses:

- React 19 + React DOM 19
- TypeScript 5
- Vite 7
- Tailwind CSS 4
- Motion (Framer Motion) for animation
- Heroicons for iconography
- ESLint 9

## Project Structure & Module Organization
This repository is a Vite + React + TypeScript web app. Work from the repo root.

- `src/`: application code (`main.tsx` entry, `App.tsx` root component, and styles).
- `public/`: static files served as-is
- Config files: `vite.config.ts`, `eslint.config.js`, `tsconfig*.json`, and `index.html`.

Keep feature code in `src/` and prefer Tailwind utilities in JSX over component-specific CSS.

## Build, Test, and Development Commands
Run commands from the repository root:

- `npm install`: install dependencies.
- `npm run dev`: start local dev server.
- `npm run build`: type-check. always run before commit.
- `npm run lint`: run ESLint across the codebase. always run before commit.

## Commit Guidelines

- Format: `<component>: <short summary>`
- Example: `webui: add recorder status indicator`
