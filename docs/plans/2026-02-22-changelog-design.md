# Changelog System Design

## Summary

Add a user-facing changelog to the site. CHANGELOG.md at project root, a CLI
subcommand to convert it to an HTML fragment, baked into the Docker image at
build time, a new Changelog dialog in the frontend, and a "new updates"
notification dot using localStorage.

## CHANGELOG.md Format

```markdown
<!-- changelog-id: N -->
# Changelog

## YYYY-MM-DD — Title
Plain-English description of what changed. No code paths.
References issues inline like (#11).

**Contributors:** @username (only for non-Jack contributors)
[View changes](https://github.com/jackharrhy/where-the-plow/compare/abc...def)
```

- `changelog-id` is an integer, incremented on each new entry
- Reverse-chronological (newest first)
- User-facing language only, link commit ranges for technical detail
- Issue references as `(#N)` — converted to GitHub links in HTML

## CLI Subcommand

`cli.py changelog` — parses CHANGELOG.md, outputs HTML fragment to
`src/where_the_plow/static/changelog.html`.

Markdown parsing is minimal, using `re` — no external dependency:
- Split on `## ` to get entries
- Convert `**text**` → `<strong>`
- Convert `[text](url)` → `<a>`
- Convert `(#N)` → GitHub issue link
- Extract `changelog-id` from HTML comment
- Output: `<div data-changelog-id="N">` with `<article>` per entry

## Dockerfile Integration

After `COPY src/ src/`, add:
```dockerfile
COPY CHANGELOG.md cli.py ./
RUN uv run python cli.py changelog
```

HTML fragment is baked into image at `/app/src/where_the_plow/static/changelog.html`.

## Frontend

### New HTML elements (index.html)
- `#panel-footer`: add `<a href="#" id="btn-view-changelog">Changelog</a>`
- About section in welcome modal: add `<button id="btn-about-changelog">`
- New `#changelog-overlay` / `#changelog-modal` pair (same pattern as welcome)

### JavaScript (app.js)
- `CHANGELOG_KEY = "wtp-changelog-seen"` — stores last-seen changelog-id
- On init: fetch `/static/changelog.html`, parse `data-changelog-id`, compare
  with localStorage, add `has-update` class to footer link if newer
- `showChangelog()`: inject HTML, show overlay, update localStorage, remove dot
- `hideChangelog()`: hide overlay
- Wired to: footer link, about-dialog button, close button, overlay click

### CSS (style.css)
- Reuse modal overlay/card pattern from welcome modal
- `.has-update::after` — notification dot (accent color circle)
- Changelog article styling: entry spacing, date headers

## AGENTS.md Addition

New `## Changelog` section with guidelines on when to update, what to write,
and how to suggest updates without auto-adding.
