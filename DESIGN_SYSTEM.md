# Hermes Artifacts Design System

Purpose: keep every generated Hermes dashboard, report, and saved HTML artifact visually cohesive instead of each page inventing a new design language.

## Chosen direction

Use the warm editorial / ivory dashboard language inspired by Anthropic's MIT-licensed `html-effectiveness` reference pages.

This should be the default for:
- artifact hub pages
- trading dashboards and daily trading reports
- travel/research reports
- system/workflow explainers
- cached social or P&L analysis pages
- future persistent dashboards

Dark/neon/glass designs should not be used for full pages unless the user explicitly asks for a dark dashboard. Dark surfaces are reserved for embedded code, terminal output, compact chart panels, or other content where a dark inset is meaningfully better.

## Implementation source of truth

Shared stylesheet:

`assets/unified-dashboard.css`

Every HTML artifact in this repository should link to that stylesheet using the correct relative path. Avoid page-level `<style>` blocks for reusable layout, typography, cards, tables, tags, buttons, nav, or responsive behavior.

## Visual tokens

Core palette:
- Background: warm ivory / parchment (`--ds-bg`, `--ds-bg-soft`)
- Surfaces: softly translucent cream (`--ds-surface`, `--ds-surface-strong`)
- Text: deep espresso (`--ds-ink`)
- Muted text: warm taupe (`--ds-muted`)
- Primary accent: terracotta (`--ds-accent`)
- Secondary accent: muted green (`--ds-accent-2`)
- Tertiary accent: desaturated blue (`--ds-accent-3`)
- Utility states: warm amber warning, muted red danger, muted green good

Typography:
- Body: system sans stack via `--ds-font`
- Editorial display headings: system serif via `--ds-serif`
- Metadata/kickers/code: monospace via `--ds-mono`

Shape and texture:
- Large rounded panels/cards
- Fine warm borders
- Soft shadows, not hard drop shadows
- Subtle background gradient/grid texture
- Generous line height and breathing room

## Component rules

Page structure:
1. One prominent hero/header panel with kicker, H1, short summary, and optional metrics.
2. Optional control/filter bar beneath the hero.
3. Content cards, sections, tables, or article blocks using shared classes/selectors.
4. Footer/manifest metadata in muted monospace.

Cards:
- Use rounded cream surfaces.
- Prefer compact metadata pills at the top.
- Titles should be scannable and not over-decorated.
- Avoid mixing unrelated accent palettes on the same page.

Tables:
- Keep table containers horizontally scrollable on small screens.
- Do not allow document-level horizontal overflow.
- Use warm borders and sticky-ish visual hierarchy rather than heavy gridlines.

Buttons and filters:
- Use pill controls.
- Active state should use the deep ink/terracotta language from the shared CSS.
- Admin-only actions should be visually secondary and preferably hidden/de-emphasized when admin mode is off.

Responsive behavior:
- Page-level horizontal overflow should remain 0 at phone widths.
- Cards/grid layouts should collapse to one column under narrow breakpoints.
- Long headings should wrap safely.
- Wide tables can scroll inside their own containers.

## Migration checklist for any new or updated HTML artifact

- Link `assets/unified-dashboard.css` or the correct relative path to it.
- Remove duplicate global `<style>` blocks unless the styles are truly one-off and cannot belong in the shared design system.
- Use the warm editorial palette and typographic hierarchy.
- Reuse existing shared selectors/classes where possible: hero/header, cards/articles, stats, filters/buttons, tags, callouts, tables, nav, footer.
- Verify with a local HTTP server, not only `file://`, if the page fetches JSON or local assets.
- Check browser console for JavaScript errors.
- Check desktop and narrow viewport for readability and document-level horizontal overflow.

## Current rollout status

The current Hermes artifacts site has been migrated to this shared stylesheet. Static QA verified that all 18 HTML pages link to `unified-dashboard.css`, no migrated page has remaining inline `<style>` blocks, and representative interactive pages load without console errors.
