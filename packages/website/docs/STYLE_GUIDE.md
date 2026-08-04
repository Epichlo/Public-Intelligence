# Website Style Guide

This guide defines the visual and interaction standards for the Website
repository. It is intended for human contributors and AI coding agents. Broader
project values and engineering principles live in `../docs/`.

## Visual Identity

The website should feel like serious engineering documentation:

- Minimal.
- Dark mode only.
- Typography-first.
- Monochrome.
- Quiet.
- Precise.
- Durable.

The reference category is documentation for mature engineering projects, not a
startup landing page. The website should make information easy to evaluate
without visual persuasion.

Do not add:

- Gradients.
- Glassmorphism.
- Decorative graphics.
- Illustrations.
- Icons unless they communicate necessary UI function.
- Unnecessary animations.
- Marketing sections.
- Statistics blocks.
- Testimonials.

## Typography Philosophy

Typography is the primary design material.

Rules:

- Use Geist as the single font family.
- Keep headings clear, restrained, and readable.
- Use generous line height for paragraphs.
- Keep body copy within readable line lengths.
- Use size and spacing to create hierarchy before adding visual treatment.
- Avoid letter-spacing changes unless a specific typographic problem requires
  them.

Headings should describe the content directly. Avoid decorative or promotional
headings.

## Spacing Philosophy

Whitespace should make the site easier to scan.

Rules:

- Use generous page padding.
- Keep content constrained to readable widths.
- Prefer vertical rhythm over visual containers.
- Keep the homepage compact enough to remain above the fold on a typical laptop
  whenever possible.
- Do not use large empty sections to simulate importance.

Spacing should support documentation reading patterns: scan, compare, click into
deeper context.

## Color Philosophy

The palette is dark-only and monochrome.

Rules:

- Use existing semantic tokens from `src/app/globals.css`.
- Prefer `text-foreground` and `text-muted-foreground` for text hierarchy.
- Use `border-border` only where a structural boundary is useful.
- Do not introduce new brand colors.
- Do not add gradients.
- Do not rely on color alone to communicate meaning.

Color should clarify hierarchy. It should not create decoration.

## Responsive Design Principles

Responsive behavior should be simple and robust.

Rules:

- Keep layouts readable on mobile before adding complexity.
- Allow navigation links to wrap naturally when needed.
- Avoid fixed-width elements that cause overflow.
- Keep content width constrained on large screens.
- Use responsive type and spacing sparingly.
- Test pages at narrow and laptop-sized widths when changing layout.

The site should work well as documentation on both mobile and desktop without
requiring separate experiences.

## Accessibility Expectations

Accessibility is a baseline requirement.

Expectations:

- Use semantic HTML landmarks and headings.
- Keep link text descriptive.
- Preserve visible focus states.
- Maintain sufficient contrast.
- Do not remove keyboard access.
- Do not use animation for essential meaning.
- Use `aria-label` only when semantic text is not enough.
- External links should use appropriate `target` and `rel` attributes when they
  open in a new tab.

A minimal interface is not automatically accessible. Structure and semantics
must still be explicit.

## Component Philosophy

Components should be practical and few.

Rules:

- Add reusable components only for stable patterns.
- Avoid creating wrapper components for one-off content.
- Keep components small and readable.
- Prefer composition over configuration-heavy APIs.
- Avoid cards unless content is genuinely a repeated item or framed tool.
- Do not nest cards.
- Do not introduce visual components that imply a broader design system before
  the site needs one.

Current shared components:

- `SiteHeader`: global navigation.
- `PageShell`: page width and spacing.

Future components should match the existing restraint.

## Documentation-First Design

The website exists to help readers understand and navigate the project.

Documentation-first design means:

- Content comes before presentation.
- Navigation is stable and predictable.
- Pages have a clear information purpose.
- Links route readers to deeper sources of truth.
- Claims are precise and supported.
- Visual hierarchy is created through text, spacing, and structure.

Avoid landing-page patterns unless a future spec explicitly requires them. In
particular, avoid hero graphics, large promotional sections, conversion funnels,
and repeated call-to-action blocks.

## Maintaining Consistency

Before adding or changing UI:

1. Check whether the existing `PageShell` and typography patterns are enough.
2. Use existing tokens and Tailwind utilities.
3. Keep the layout monochrome and static.
4. Confirm the content has a documentation purpose.
5. Remove anything decorative that does not improve comprehension.

When in doubt, choose the simpler version. A future contributor should be able
to understand the page by reading the markup and the content, not by reverse
engineering a visual concept.
