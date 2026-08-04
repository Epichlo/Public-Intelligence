# Website Development

This document describes how to work in the Website repository. It covers only
repository-specific structure and conventions. For organization-wide engineering
principles and development workflow, refer to:

- `../docs/ENGINEERING_PRINCIPLES.md`
- `../docs/DEVELOPMENT_WORKFLOW.md`

## Stack

The website uses:

- Next.js App Router.
- TypeScript.
- Tailwind CSS.
- shadcn/ui configuration.
- Geist via `next/font`.
- npm for dependency management.

The project is intentionally small. Do not add frameworks, routing layers, state
libraries, animation systems, or design dependencies unless a concrete website
need justifies them.

## Project Structure

Current repository structure:

```text
.
├── docs/
├── src/
│   ├── app/
│   ├── components/
│   └── lib/
├── components.json
├── eslint.config.mjs
├── next.config.ts
├── package.json
├── postcss.config.mjs
└── tsconfig.json
```

Important files and folders:

- `src/app/`: App Router routes, layouts, and route-level pages.
- `src/components/`: reusable website components.
- `src/lib/`: shared utilities that are not UI components.
- `components.json`: shadcn/ui configuration.
- `src/app/globals.css`: Tailwind import, shadcn CSS integration, and global
  design tokens.
- `src/app/layout.tsx`: root layout inherited by all routes.
- `src/app/page.tsx`: homepage.

## App Router Structure

Routes are file-system based under `src/app`.

Examples:

```text
src/app/page.tsx                  -> /
src/app/vision/page.tsx           -> /vision
src/app/architecture/page.tsx     -> /architecture
src/app/research/page.tsx         -> /research
src/app/roadmap/page.tsx          -> /roadmap
src/app/contribute/page.tsx       -> /contribute
```

The root layout in `src/app/layout.tsx` owns global concerns:

- HTML language.
- Geist font setup.
- Dark-mode class.
- Global navigation through `SiteHeader`.
- Shared global CSS import.

Do not duplicate the global header in individual pages.

## Adding New Pages

Before adding a page:

1. Confirm the page has a clear reader task.
2. Check whether the content belongs in organization-level docs under `../docs/`.
3. Prefer adding pages under an existing section before creating new top-level
   navigation.
4. Keep the page documentation-first and avoid marketing sections.

To add a route:

1. Create a directory under `src/app/`.
2. Add a `page.tsx` file.
3. Wrap page content in `PageShell`.
4. Use semantic HTML for headings, sections, and navigation.
5. Add navigation only if the page is a durable primary destination.

Example:

```tsx
import { PageShell } from "@/components/page-shell";

export default function ExamplePage() {
  return (
    <PageShell>
      <section className="max-w-3xl space-y-4">
        <h1 className="text-4xl font-medium text-foreground">Example</h1>
        <p className="text-lg text-muted-foreground">Coming Soon</p>
      </section>
    </PageShell>
  );
}
```

## Component Organization

Components should live in `src/components/`.

Current shared components:

- `SiteHeader`: global top navigation.
- `PageShell`: shared page width and spacing wrapper.

Component rules:

- Create components only when they remove meaningful repetition or clarify a
  stable layout pattern.
- Keep route-specific content in the route file unless it is reused.
- Do not introduce a broad component system before the site needs one.
- shadcn/ui is configured, but components should be added deliberately and only
  when they match the documentation-first interface.

## Local Development

Install dependencies:

```bash
npm install
```

Start the development server:

```bash
npm run dev
```

The local server normally runs at:

```text
http://localhost:3000
```

If port `3000` is already in use, Next.js may choose another port or fail. Use
the terminal output as the source of truth for the local URL.

## Build And Verification Commands

Run lint:

```bash
npm run lint
```

Run a production build:

```bash
npm run build
```

Start a production server after building:

```bash
npm run start
```

Expected verification for code changes:

- Run `npm run lint`.
- Run `npm run build`.
- Review the changed files for unintended design or content drift.

Documentation-only changes do not require a production build unless they affect
rendered website content.

## Repository-Specific Engineering Conventions

Use these conventions in addition to organization-wide guidance:

- Do not redesign the project structure without explicit approval.
- Keep changes scoped to the requested website behavior.
- Preserve the App Router model.
- Preserve the dark-only design unless a future spec changes it.
- Prefer server components by default.
- Avoid client components unless interactivity requires them.
- Avoid new dependencies for static content and layout.
- Prefer semantic HTML and Tailwind utility classes over custom abstractions.
- Use the `@/*` import alias for imports from `src/`.
- Keep global layout concerns in `src/app/layout.tsx`.
- Keep reusable layout primitives in `src/components/`.
- Do not add placeholder assets, decorative graphics, gradients, animations, or
  marketing sections.

## Guidance For AI Coding Agents

Before editing:

- Inspect the current files.
- Read the relevant docs in this repository.
- Check `../docs/` when a request touches organization-level meaning.
- Confirm whether the user asked for implementation, planning, or documentation.

When editing:

- Modify the smallest set of files that satisfies the request.
- Avoid broad refactors.
- Do not change navigation, layout, dependencies, or design language unless the
  request explicitly requires it.
- Keep code and copy consistent with `docs/STYLE_GUIDE.md` and
  `docs/WEBSITE_SPEC.md`.

After editing:

- Run `npm run lint` and `npm run build` for code changes.
- Summarize every changed file.
- State any verification that could not be completed.
