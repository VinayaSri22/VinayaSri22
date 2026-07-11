# GitHub Profile OS

A self-updating, dashboard-style GitHub profile README.

- **No server, no database, no external services.** A single Python script
  (standard library only) reads `config.json`, pulls live data from the GitHub
  REST + GraphQL APIs, and renders the whole profile as one composed SVG
  (a dark and a light variant), then writes `README.md`.
- **Runs itself.** A GitHub Action rebuilds the dashboard every morning (and on
  every push to `config.json`) and commits the result.
- **Real data only.** In CI the run fetches live stats and *fails* rather than
  commit fabricated numbers. Sample numbers exist only for local previews.
- **Theme-correct.** `README.md` uses `<picture>` to serve the dark dashboard to
  dark-theme viewers and the light one to light-theme viewers.

![Dashboard preview](assets/dashboard-dark.svg)

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
| `avatar` | Path to an image embedded (base64) into the hero. Set to `null`/`""` to remove it. |
| `avatar_style` | `"image"` (use `avatar`), or `"pixel"` to use the built-in generated pixel avatar. |
| `timezone` | IANA name (e.g. `Asia/Kolkata`) for the "Last updated" stamp. |
| `accent` | Reserved for future accent tweaks. |
| `engineering_journal` | One-sentence summary shown in the full-width Journal strip. |
| `building` | Cards in "Currently Building": `icon`, `name`, `desc`, `tags`. |
| `tech_stack` | Rows in "Tech Stack": `icon`, `label`, `values`. |
| `learning` | `name: percent` pairs rendered as progress bars. |
| `learning_quote` | Italic line under the learning bars. |
| `socials` | `linkedin`, `email`, `website`, `location` in the Connect panel. |
| `footer` | Full-width footer message. |
| `sample_stats` | Placeholder numbers for **local previews only** (`--sample`). Never used in CI. |

**Available icon names:** `brain`, `robot`, `bolt`, `code`, `server`,
`window`, `database`, `wrench`, `globe`, `linkedin`, `mail`, `link`, `pin`,
`coffee`, `run`, `pen`.

**Avatar image:** drop a PNG at the path in `avatar` (a transparent background
works best so it blends on both themes). It's embedded into the dashboard SVG as
base64, so nothing is hosted externally. To go text-only, set `avatar` to `""`.

---

## Live data

| Panel | Source |
| --- | --- |
| GitHub Stats | REST `/users/:login` (repos, followers, following) + summed stargazers. |
| Contributions / PRs / Issues / Commits | GraphQL `contributionsCollection` (needs the Action's token). |
| GitHub Activity heatmap | GraphQL contribution calendar (last 26 weeks). |
| Daily quote | Rotates through a built-in list by day of year. |

**No fake data.** In GitHub Actions the script fetches live stats; if the API
call fails it raises and the job fails, so a broken/fabricated dashboard is
never committed. Locally (no token) it automatically switches to `--sample`
mode with a synthetic heatmap so you can preview the design safely.

---

## Run locally

```bash
python3 update.py --sample   # build with sample data (no token needed)
python3 preview.py           # build sample data + copy dark dashboard to preview.svg
```

Preview rendering to PNG (macOS): `qlmanage -t -s 1952 -o . preview.svg`.

No dependencies are required — everything uses the Python standard library.

---

## How it stays GitHub-compatible

The entire dashboard is generated as a **single composed SVG**, in a dark and a
light variant (`assets/dashboard-dark.svg`, `assets/dashboard-light.svg`).
`README.md` embeds them with a `<picture>` element, so GitHub can't reflow the
layout and each viewer gets the variant matching their system theme. Clickable
social links are rendered as normal Markdown links beneath the image.
