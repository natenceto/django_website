# Screenshots guidance

Suggested pages to capture for the repository README and GitHub display:

- Home / Landing page (`/`) — shows overall site header and main features.
- Map view (`/map/` or map page) — visual map of charging stations.
- Charging station detail (a station page with status and connectors) — demonstrates OCPP/live state UI.
- About page (`/about/`) — includes funding acknowledgement and project description.

How to create and add screenshots:

1. Run the site locally (see `setup.sh` and `.env.example`).
2. Open the pages above in a browser at a suitable viewport (e.g., 1280×720).
3. Take PNG screenshots (filename suggestion: `screenshot-home.png`, `screenshot-map.png`, `screenshot-station.png`, `screenshot-about.png`).
4. Add the images to `docs/screenshots/` and commit them.
5. Reference them in `README.md` using relative paths, for example:

```markdown
![Home screenshot](docs/screenshots/screenshot-home.png)
```

Notes:

- Avoid including any sensitive user data or real credentials in screenshots.
- If you prefer not to commit images to the repo, host them in the project's GitHub releases or an external CDN and link to them instead.
