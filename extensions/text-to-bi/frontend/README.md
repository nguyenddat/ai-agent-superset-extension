# Text to BI frontend

React 17 page for the Superset Text to BI extension. Superset loads it through webpack Module Federation: the remote
is `textToBi_supersetTextToBi`, it exposes `./index` (`src/index.tsx`), shares `react` and `react-dom` with Superset
as singletons, and is served from `/api/v1/extensions/text-to-bi/superset-text-to-bi/`.

`src/index.tsx` reads the user's access from `auth/me`, adds the "AI Agent", "Mô hình dữ liệu" and "Quản trị dữ liệu"
menus to Superset's navbar (only the groups the user can open something in) and mounts `<App>` under Superset's
header when the URL is `/text-to-bi/`. The section comes from `?section=<segment>`.

## Stack

- React 17 (peer dependency, provided by Superset). `lib/react-compat.ts` shims `useSyncExternalStore` and `useId`
  for components ported from the React 19 standalone app.
- shadcn components, style `base-nova` on [Base UI](https://base-ui.com) (`@base-ui/react`), icons from
  `lucide-react`; see `components.json`.
- Tailwind CSS v4 through `@tailwindcss/postcss`. `styles/globals.css` imports only Tailwind's theme and utilities,
  with no preflight, so nothing reaches Superset's own pages; the few base rules shadcn needs are scoped to `.tb-page`,
  the root `AppShell` renders. Dark mode follows `data-theme-mode` on the page host, which `index.tsx` sets from
  Superset's theme.
- `@xyflow/react` and `elkjs` for the model and lineage canvases, `recharts` for chat and statistics charts, `react-markdown` with
  `remark-gfm` for answers, `swr` for data fetching.
- webpack 5 with `ts-loader` (transpile only); `@/` resolves to `src/`.

## Folders

```text
src/
├── index.tsx        Navbar menus and page mounting
├── app.tsx          Picks the section component for the current ?section=
├── components/
│   ├── ui/          shadcn primitives (button, dialog, select, table, tabs, ...)
│   ├── layout/      app-shell.tsx: the .tb-page root and portal container
│   └── *.tsx        Shared composites: data table, prompt composer, streaming answer, stat tiles, toaster, ...
├── features/
│   ├── workspace/               Section list and access rules (workspace-layout.tsx), overview, database scope
│   ├── text2sql/                Hỏi dữ liệu: chat, SSE stream, results, charts/
│   ├── own-knowledge/           Tri thức riêng
│   ├── data-dictionary/         Từ điển
│   ├── business-model/          Mô hình
│   ├── data-lineage/            Dòng dữ liệu
│   ├── metric-management/       Metric
│   ├── glossary-management/     Thuật ngữ
│   └── expert-rule-management/  Quy tắc
├── lib/
│   ├── api.ts         apiFetch: base path /extensions/text-to-bi/superset-text-to-bi, session cookie, CSRF token
│   ├── access.ts      Access flags from auth/me
│   ├── navigation.tsx PAGE_PATH, pageHref, navigate, unsaved-edit guard
│   ├── theme.ts       Light/dark mode from data-theme-mode
│   ├── sse.ts         Server-Sent Events reader
│   └── ...            format, portal container, React 17 shims, cn()
└── styles/globals.css Tailwind entry, theme tokens, navbar menu styles
```

Each feature folder keeps its own `api.ts` and `types.ts` next to its components. Which section a user can open is
decided by `canOpenSection` in `features/workspace/workspace-layout.tsx`; the backend still checks every request.

## Commands

From this directory:

```sh
npm install
npm run typecheck   # tsc --noEmit
npm run build       # webpack production build into dist/
```

You normally do not run the build by hand: `uv run scripts/build.py` at the repository root bundles backend and
frontend into `extensions/superset-text-to-bi-0.1.0.supx`, and `uv run scripts/check.py` runs the typecheck.
