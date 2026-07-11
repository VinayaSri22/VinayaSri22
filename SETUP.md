# GitHub Profile OS

A self-updating, dashboard-style GitHub profile README.

- **No server, no database, no external services.** A single Python script
  (standard library only) reads `config.json`, pulls live data from the GitHub
  REST + GraphQL APIs, renders a set of theme-adaptive SVG panels, and writes
  `README.md`.
- **Runs itself.** A GitHub Action rebuilds the dashboard every morning (and on
  every push to `config.json`) and commits the result.
- **Fully themeable.** Every panel adapts to the viewer's light/dark system
  theme automatically.

![Dashboard preview](assets/banner.svg)

---

## Use it for your own profile

1. **Fork** this repository, then rename the fork to your **exact GitHub
   username** (e.g. a user named `octocat` creates a repo named `octocat`).
   A repo that matches your username is what GitHub renders on your profile.
2. Edit **`config.json`** with your details (see below).
3. Go to the **Actions** tab and enable workflows, then run **"GitHub Profile
   OS"** once via **Run workflow** to build immediately. After that it updates
   daily on its own.

That's it — no tokens to create. The workflow uses the automatic
`GITHUB_TOKEN` that GitHub Actions provides.

---

## Configuration (`config.json`)

Everything you see is driven by this one file. You never edit Python.

| Field | What it controls |
| --- | --- |
| `github_username` | Which account's live stats are fetched. |
| `name`, `role`, `tagline` | Hero banner text. `tagline` may use `\n` for line breaks. |
| `hero_chips` | The `•`-separated chips under the tagline. |
| `timezone` | IANA name (e.g. `Asia/Kolkata`) for the "Last updated" stamp. |
| `accent` | Reserved for future accent tweaks. |
| `engineering_journal` | One-sentence summary shown in the full-width Journal strip. |
| `building` | Cards in "Currently Building": `icon`, `name`, `desc`, `tags`. |
| `tech_stack` | Rows in "Tech Stack": `icon`, `label`, `values`. |
| `learning` | `name: percent` pairs rendered as progress bars. |
| `learning_quote` | Italic line under the learning bars. |
| `socials` | `linkedin`, `email`, `website`, `location` in the Connect panel. |
| `footer` | Full-width footer message. |
| `stats_fallback` | Values used if the API is unavailable (also power local previews). |

**Available icon names:** `brain`, `robot`, `bolt`, `code`, `server`,
`window`, `database`, `wrench`, `globe`, `linkedin`, `mail`, `link`, `pin`,
`coffee`, `run`, `pen`.

---

## Live data

| Panel | Source |
| --- | --- |
| GitHub Stats | REST `/users/:login` (repos, followers, following) + summed stargazers. |
| Contributions / PRs / Issues / Commits | GraphQL `contributionsCollection` (needs the Action's token). |
| GitHub Activity heatmap | GraphQL contribution calendar (last 26 weeks). |
| Daily quote | Rotates through a built-in list by day of year. |

If the API can't be reached (e.g. running locally without a token), the script
falls back to `stats_fallback` and a synthetic heatmap so it never breaks.

---

## Run locally

```bash
python3 update.py          # regenerates assets/*.svg and README.md
python3 preview.py         # composes a single preview.svg of the whole dashboard
```

Preview rendering to PNG (macOS): `qlmanage -t -s 1936 -o . preview.svg`.

No dependencies are required — everything uses the Python standard library.

---

## How it stays GitHub-compatible

GitHub renders SVGs referenced from the README as images. Each generated SVG
embeds a `<style>` block with a `prefers-color-scheme` media query, so the same
file shows a dark palette to dark-theme viewers and a light palette to
light-theme viewers. Every element also carries an explicit color attribute, so
it still renders correctly in tools that ignore CSS.
