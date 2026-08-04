# Website Specification

This document defines the purpose, structure, and content expectations for the
Public Intelligence website repository. It is repository-specific by design.
Organization-wide context, technical strategy, glossary, engineering principles,
and roadmap details live in `../docs/` and should be referenced instead of
copied here.

## Purpose

The Website repository contains the public web presence for Public Intelligence.
Its job is to publish clear, stable, documentation-first information about the
project and provide a durable entry point into deeper project materials.

This repository is not the source of truth for the full Public Intelligence
vision, architecture, roadmap, or engineering process. Those materials belong in
the organization-level documentation:

- `../docs/PROJECT_CONTEXT.md`
- `../docs/ARCHITECTURE_OVERVIEW.md`
- `../docs/ROADMAP.md`
- `../docs/ENGINEERING_PRINCIPLES.md`
- `../docs/DEVELOPMENT_WORKFLOW.md`
- `../docs/GLOSSARY.md`

The website should summarize and route readers to the right places without
duplicating those documents.

## Intended Audience

The website is written for people who need to understand the project quickly and
accurately:

- Engineers evaluating the architecture and implementation direction.
- Researchers following the technical work.
- Open-source contributors looking for where to start.
- Reviewers, partners, and community members seeking a trustworthy overview.
- AI coding agents that need repository-specific constraints before making
  changes.

The audience should be assumed to be technically literate. The writing should be
accessible, but it should not flatten technical nuance into marketing language.

## Information Architecture

The current site has a small, stable top-level structure:

- `/`
- `/vision`
- `/architecture`
- `/research`
- `/roadmap`
- `/contribute`
- External GitHub organization link

The site should grow by adding durable documentation pages under these sections,
not by adding campaign-style landing pages. Top-level navigation should remain
small enough to scan at a glance.

## Navigation Philosophy

Navigation is a map, not a marketing funnel.

The global navigation should:

- Stay minimal and predictable.
- Prefer stable nouns over slogans.
- Link to the primary documentation areas.
- Keep GitHub as an external link to the official organization:
  `https://github.com/Public-Intelligence-Revolution`.
- Avoid transient links, campaign labels, badges, or calls to action.
- Remain usable on small screens through simple wrapping or similarly restrained
  responsive behavior.

Do not add navigation items unless they represent a durable information category
that will remain useful as the project matures.

## Page Purposes

### Home

The homepage introduces the website and routes readers to the main sections. It
should remain compact, serious, and documentation-oriented. It should not become
a long marketing page.

The homepage currently contains:

- Project name.
- Short infrastructure-focused positioning statement.
- One concise description paragraph.
- Quick links to key sections and GitHub.
- Current milestone.

### Vision

The Vision page should explain what the website needs readers to understand
about direction and intent. It should reference `../docs/PROJECT_CONTEXT.md`
for organization-level context instead of restating it in full.

### Architecture

The Architecture page should guide readers toward the current technical model,
system boundaries, and architecture documents. It should reference
`../docs/ARCHITECTURE_OVERVIEW.md` as the deeper source of truth.

### Research

The Research page should organize public research notes, open questions,
technical investigations, and references that support the website audience. It
should avoid speculative claims that are not backed by project documentation.

### Roadmap

The Roadmap page should summarize website-relevant milestones and direct readers
to `../docs/ROADMAP.md` for organization-level planning. It should avoid
overpromising dates or implementation status.

### Contribute

The Contribute page should explain how website readers become contributors. It
should route engineering contributors to `../docs/DEVELOPMENT_WORKFLOW.md` and
`../docs/ENGINEERING_PRINCIPLES.md` when the guidance applies beyond this repo.

### GitHub

GitHub is not a local page. It is an external link to the official Public
Intelligence GitHub organization:

`https://github.com/Public-Intelligence-Revolution`

## Content Philosophy

The website should be useful before it is persuasive.

Content should:

- Explain what exists, what is planned, and where to learn more.
- Prefer precise technical language over promotional language.
- Stay concise unless the page is explicitly a documentation page.
- Link to source documents instead of duplicating them.
- Make uncertainty explicit where the project is still researching or designing.
- Avoid hype, artificial urgency, and generic open-source slogans.

Content should not:

- Repeat organization-wide documentation verbatim.
- Create a separate version of the roadmap, glossary, or architecture source of
  truth.
- Introduce claims that are not represented in project documentation.
- Add marketing sections such as testimonials, statistics, promotional banners,
  or campaign copy.

## Writing Style

Use a calm engineering voice:

- Short paragraphs.
- Direct sentences.
- Concrete nouns.
- Minimal adjectives.
- Active voice where practical.
- Clear links with descriptive labels.

Avoid:

- Hype language.
- Startup-style positioning.
- Overexplaining obvious UI behavior.
- Decorative section titles.
- Vague claims such as "revolutionary", "seamless", or "game-changing".

When content depends on organization-level concepts, link to the relevant file in
`../docs/` and summarize only what is necessary for website navigation.

## Future Expansion Strategy

Expand the website through stable information areas:

- Add child pages under existing sections before adding new top-level nav items.
- Promote a child page to navigation only when it becomes a primary reader path.
- Keep the homepage compact as the project grows.
- Treat organization-level docs as upstream sources for architecture, roadmap,
  glossary, and project context.
- Review existing pages before adding new pages to avoid duplicate explanations.

Future website pages should have a clear reader task. If a proposed page cannot
name its reader and purpose, it should not be added yet.
