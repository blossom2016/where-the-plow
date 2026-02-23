# Changelog System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a user-facing changelog with new-update notifications to the snowplow tracker.

**Architecture:** CHANGELOG.md → cli.py subcommand → static HTML fragment → frontend modal with localStorage-based notification dot.

**Tech Stack:** Python (re module for markdown parsing), vanilla JS, CSS custom properties.

---

### Task 1: Create CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`

**Step 1: Write the changelog**

```markdown
<!-- changelog-id: 5 -->
# Changelog

## 2026-02-22 — Address Search
You can now search for a street address and jump directly to it on the map,
instead of scrolling and zooming manually.

**Contributors:** [@blossom2016](https://github.com/blossom2016)
[View changes](https://github.com/jackharrhy/where-the-plow/compare/c5672ad...42ddc1e)

## 2026-02-22 — Email Signups & About Modal
New welcome modal with information about the project and an email signup form.
Leave your email to get notified when street-level plow alerts are ready.
Social sharing images and SEO metadata added.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/ae41e5f...c5672ad)

## 2026-02-21 — Coverage Playback Controls
Play back coverage data as a time-lapse animation. Filter by vehicle type
using the legend checkboxes. Follow a specific vehicle during playback.
Improved time range slider and mobile layout.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/5036734...ae41e5f)

## 2026-02-19 — Map Legend & Geolocate
Collapsible legend showing vehicle types with color coding. "Locate me" button
to center the map on your position.

**Contributors:** [@AminTaheri23](https://github.com/AminTaheri23)
[View changes](https://github.com/jackharrhy/where-the-plow/compare/5036734...7f4db6c)

## 2026-02-19 — Coverage History & Heatmap
View which streets have been plowed over the last 6, 12, or 24 hours. Switch
between route lines and a heatmap view. Pick a specific date to review past
coverage. Time slider to scrub through the window.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/4402d55...54f335f)

## 2026-02-19 — Launch
Live map of St. John's snowplow fleet. Vehicles update every 6 seconds from
the City of St. John's AVL system. Click any vehicle to see its recent trail.
Data is stored for historical playback.

[View changes](https://github.com/jackharrhy/where-the-plow/compare/2a08888...4402d55)
```

**Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG.md with project history"
```

---

### Task 2: Add changelog subcommand to cli.py

**Files:**
- Modify: `cli.py`

**Step 1: Add the changelog function and update COMMANDS**

Add to `cli.py` — a `changelog()` function that:
1. Reads `CHANGELOG.md` from the same directory as the script
2. Extracts `changelog-id` from the `<!-- changelog-id: N -->` comment
3. Splits on `## ` to get individual entries
4. For each entry, converts:
   - `**text**` → `<strong>text</strong>`
   - `[text](url)` → `<a href="url" target="_blank" rel="noopener">text</a>`
   - `(#N)` → `(<a href="https://github.com/jackharrhy/where-the-plow/issues/N">#N</a>)`
   - `[@user](url)` — already handled by link conversion
   - Blank lines → paragraph breaks
5. Wraps in `<div class="changelog" data-changelog-id="N">`
6. Each entry is an `<article>` with `<h2>` for the date/title
7. Writes to `src/where_the_plow/static/changelog.html`

The function should work from the project root (where `cli.py` lives). Use
`pathlib.Path(__file__).parent` to find paths relative to the script.

Update `COMMANDS` dict to include `"changelog"` and the dispatch table.

**Step 2: Test locally**

```bash
uv run python cli.py changelog
cat src/where_the_plow/static/changelog.html
```

Verify the output is a valid HTML fragment with the correct `data-changelog-id`.

**Step 3: Commit**

```bash
git add cli.py
git commit -m "feat: add changelog subcommand to cli.py"
```

---

### Task 3: Update Dockerfile

**Files:**
- Modify: `Dockerfile`

**Step 1: Add COPY and RUN for changelog generation**

After `COPY src/ src/`, add:
```dockerfile
COPY CHANGELOG.md cli.py ./
RUN uv run python cli.py changelog
```

This generates the HTML fragment at build time.

**Step 2: Commit**

```bash
git add Dockerfile
git commit -m "build: generate changelog HTML during Docker build"
```

---

### Task 4: Add changelog dialog HTML to index.html

**Files:**
- Modify: `src/where_the_plow/static/index.html`

**Step 1: Add Changelog link to panel footer**

In `#panel-footer` (line 229), after the About link, add:
```html
&middot;
<a href="#" id="btn-view-changelog">Changelog</a>
```

**Step 2: Add "View Changelog" button to About section of welcome modal**

Inside the About `.welcome-section` (after the existing paragraph at line 341), add:
```html
<button id="btn-about-changelog" class="changelog-link-btn">View Changelog</button>
```

**Step 3: Add changelog overlay and modal**

Before the closing `</body>` tag (before the script tag), add:
```html
<!-- Changelog modal -->
<div id="changelog-overlay" class="hidden">
    <div id="changelog-modal">
        <button id="changelog-close" title="Close">&times;</button>
        <h2>What's New</h2>
        <div id="changelog-content">Loading...</div>
    </div>
</div>
```

**Step 4: Commit**

```bash
git add src/where_the_plow/static/index.html
git commit -m "feat: add changelog dialog and footer link to HTML"
```

---

### Task 5: Add changelog CSS to style.css

**Files:**
- Modify: `src/where_the_plow/static/style.css`

**Step 1: Add changelog modal styles**

At the end of the file, add styles for:

1. `#changelog-overlay` — reuse same pattern as `#welcome-overlay`
2. `#changelog-overlay.hidden` — `display: none`
3. `#changelog-modal` — same glassmorphism card as welcome, but maybe 520px max-width
4. `#changelog-modal h2` — same as welcome h2
5. `#changelog-close` — same as welcome close button
6. `.changelog article` — each entry, with bottom border and padding
7. `.changelog article:last-child` — no bottom border
8. `.changelog article h2` — entry title: slightly smaller, accent color
9. `.changelog article p` — standard paragraph styling
10. `.changelog article a` — link color
11. `.has-update` — `position: relative`
12. `.has-update::after` — notification dot: small circle, accent color, positioned top-right
13. `.changelog-link-btn` — styled as a text link button (no background, link color)

**Step 2: Add mobile responsive styles**

In the existing `@media (max-width: 768px)` block, add changelog modal adjustments.

**Step 3: Commit**

```bash
git add src/where_the_plow/static/style.css
git commit -m "feat: add changelog modal and notification dot styles"
```

---

### Task 6: Add changelog JavaScript to app.js

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add changelog section after welcome modal code**

After the welcome modal section (after line 253), add a new section:

```javascript
/* ── Changelog modal ───────────────────────────────── */

const CHANGELOG_KEY = "wtp-changelog-seen";
const changelogOverlay = document.getElementById("changelog-overlay");
const changelogModal = document.getElementById("changelog-modal");
const changelogCloseBtn = document.getElementById("changelog-close");
const changelogContent = document.getElementById("changelog-content");
const btnViewChangelog = document.getElementById("btn-view-changelog");
const btnAboutChangelog = document.getElementById("btn-about-changelog");

let changelogHtml = null;
let changelogId = null;

async function loadChangelog() {
  if (changelogHtml !== null) return;
  try {
    const resp = await fetch("/static/changelog.html");
    if (!resp.ok) { changelogHtml = "<p>Changelog unavailable.</p>"; return; }
    const html = await resp.text();
    const match = html.match(/data-changelog-id="(\d+)"/);
    changelogId = match ? parseInt(match[1]) : null;
    changelogHtml = html;
    checkChangelogUpdate();
  } catch {
    changelogHtml = "<p>Changelog unavailable.</p>";
  }
}

function checkChangelogUpdate() {
  if (changelogId === null) return;
  const seen = parseInt(localStorage.getItem(CHANGELOG_KEY) || "0");
  if (changelogId > seen) {
    btnViewChangelog.classList.add("has-update");
  }
}

function showChangelog() {
  changelogContent.innerHTML = changelogHtml || "<p>Loading...</p>";
  changelogOverlay.classList.remove("hidden");
  if (changelogId !== null) {
    localStorage.setItem(CHANGELOG_KEY, String(changelogId));
    btnViewChangelog.classList.remove("has-update");
  }
}

function hideChangelog() {
  changelogOverlay.classList.add("hidden");
}

// Load changelog on page load
loadChangelog();

btnViewChangelog.addEventListener("click", (e) => {
  e.preventDefault();
  showChangelog();
});

btnAboutChangelog.addEventListener("click", () => {
  hideWelcome();
  showChangelog();
});

changelogCloseBtn.addEventListener("click", hideChangelog);

changelogOverlay.addEventListener("click", (e) => {
  if (e.target === changelogOverlay) hideChangelog();
});
```

**Step 2: Test locally**

Run `uv run python cli.py changelog` to generate the HTML, then `uv run cli.py dev`.
Verify:
- Changelog link appears in footer
- Clicking it opens the changelog modal with rendered content
- Closing works (X, overlay click)
- "View Changelog" button in About dialog opens changelog and closes About
- Notification dot appears on first visit, disappears after opening changelog
- Reloading the page — no dot (localStorage remembers)

**Step 3: Commit**

```bash
git add src/where_the_plow/static/app.js
git commit -m "feat: changelog modal with fetch, localStorage notification"
```

---

### Task 7: Add .gitignore entry for generated changelog.html

**Files:**
- Modify: `.gitignore`

**Step 1: Add changelog.html to gitignore**

The file is generated by the CLI and shouldn't be committed. Add:
```
src/where_the_plow/static/changelog.html
```

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore generated changelog.html"
```

---

### Task 8: Update AGENTS.md with changelog guidelines

**Files:**
- Modify: `AGENTS.md`

**Step 1: Add Changelog section**

After the "Key conventions" section, add:

```markdown
## Changelog

`CHANGELOG.md` at the project root is for **end users**, not developers.
Write in plain English -- no file paths, no code snippets, no technical
jargon. Each entry links to a GitHub commit range via
`[View changes](compare URL)` so technical users can drill in.

**Format:** Each entry is `## YYYY-MM-DD — Title` followed by a few
sentences, an optional `**Contributors:**` line (only for non-Jack
contributors), and a `[View changes]()` link. Increment the
`<!-- changelog-id: N -->` integer at the top whenever a new entry is added.

**When to update:** User-facing features, significant bug fixes, and new
data sources warrant a changelog entry. Internal refactors, code cleanup,
CI changes, and documentation do not.

**Agent behavior:** If a change looks changelog-worthy, mention it to the
user ("This might warrant a changelog entry") but do NOT add it
automatically. The user decides when to batch changes into an entry,
typically before finishing a branch. Reference GitHub issues with `(#N)`
when relevant.

**Generating HTML:** After editing `CHANGELOG.md`, run
`uv run python cli.py changelog` to regenerate the HTML fragment. The
Dockerfile does this automatically at build time.
```

**Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: add changelog guidelines to AGENTS.md"
```

---

### Task summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Create CHANGELOG.md with project history | `CHANGELOG.md` |
| 2 | Add changelog subcommand to cli.py | `cli.py` |
| 3 | Update Dockerfile for build-time generation | `Dockerfile` |
| 4 | Add changelog dialog HTML | `index.html` |
| 5 | Add changelog CSS styles | `style.css` |
| 6 | Add changelog JavaScript | `app.js` |
| 7 | Gitignore generated HTML | `.gitignore` |
| 8 | Add changelog guidelines to AGENTS.md | `AGENTS.md` |
