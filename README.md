# Workout --> GitHub Heatmap Dashboard

Turn your Strava and Garmin activities into GitHub-style contribution heatmaps.  
Automatically generates a free, interactive dashboard updated daily on GitHub Pages.  
**No coding required.**  

- View the Interactive [Activity Dashboard](https://aspain.github.io/git-sweaty/)
- Once setup is complete, this dashboard link will automatically update to your own GitHub Pages URL.


![Dashboard Preview](site/readme-preview-20260213.png)

## Quick Start

### Run the setup script

1. Fork this repo: [Fork this repository](../../fork)
2. Clone your fork and enter it:

   ```bash
   git clone https://github.com/<your-username>/<repo-name>.git
   cd <repo-name>
   ```
3. Sign in to GitHub CLI:

   ```bash
   gh auth login
   ```

4. Run setup:

   ```bash
   python3 scripts/setup_auth.py
   ```

   Follow the terminal prompts to choose a source and unit preference:
      - `strava` - terminal will link to [Strava API application](https://www.strava.com/settings/api). Create an application first and set **Authorization Callback Domain** to `localhost`. The prompt will then ask for `Client ID` and `Client Secret`
      - `garmin` - terminal prompts for Garmin email/password
      - unit preference (`US` or `Metric`)

   The setup may take several minutes to complete when run for the first time. If any automation step fails, the script prints steps to remedy the failed step.  
   Once the script succeeds, it will provide the URL for your dashboard.

### Updating Your Repository

- To pull in new updates and features from the original repo, use GitHub's **Sync fork** button on your fork's `main` branch.
- Activity data is stored on a dedicated `dashboard-data` branch and deployed from there
- `main` is intentionally kept free of generated `data/` and `site/data.json` artifacts so fork sync process stays cleaner.
- After syncing, manually run [Sync Heatmaps](../../actions/workflows/sync.yml) if you want your dashboard refreshed immediately. Otherwise updates will deploy at the next scheduled run.

### Switching Sources Later

You can switch between `strava` and `garmin` any time, even after initial setup.

- Re-run `python3 scripts/setup_auth.py` and choose a different source (or pass `--source strava` / `--source garmin`).

## Configuration (Optional)

Everything in this section is optional. Defaults work without changes.
Base settings live in `config.yaml`, and `config.local.yaml` overrides them when present.

Auth + source settings:
- `source` (`strava` or `garmin`)
- `strava.client_id`, `strava.client_secret`, `strava.refresh_token`
- `garmin.token_store_b64`, `garmin.email`, `garmin.password`
- `garmin.strict_token_only` (when `true`, Garmin sync requires `garmin.token_store_b64` and does not fall back to email/password auth)

Sync scope + backfill behavior:
- `sync.start_date` (optional `YYYY-MM-DD` lower bound for history)
- `sync.lookback_years` (optional rolling lower bound; used only when `sync.start_date` is unset)
- `sync.recent_days` (sync recent activities even while backfilling)
- `sync.resume_backfill` (persist cursor so backfills continue across scheduled runs)
- `sync.per_page` (page size used when fetching provider activities; default `200`)
- `sync.prune_deleted` (remove local activities no longer returned by the provider; pruning only happens on runs that perform a full backfill scan)

Activity type behavior:
- `activities.types` (featured order in UI, and acts as allowlist when `activities.include_all_types` is `false`)
- `activities.include_all_types` (when `true`, include all seen sport types; when `false`, include only `activities.types`)
- `activities.exclude_types` (explicit type exclusions, even when `include_all_types` is `true`)
- `activities.type_aliases` (map raw provider type names to canonical type names before grouping/filtering)
- `activities.group_aliases` (map canonical type names to explicit grouped labels)
- `activities.group_other_types` (when `true`, non-featured types are grouped into broader buckets; repo default is `false`)
- `activities.other_bucket` (fallback group name when grouped type matching has no hit)

Display + rate-limit settings:
- `units.distance` (`mi` or `km`)
- `units.elevation` (`ft` or `m`)
- `rate_limits.*` (Strava API pacing caps used by sync; ignored for Garmin)

## Notes

- Raw activities are stored locally for processing but are not committed (`activities/raw/` is ignored). This prevents publishing detailed per-activity payloads and GPS location traces.
- If neither `sync.start_date` nor `sync.lookback_years` is set, the sync workflow backfills all available history from the selected source (i.e. Strava/Garmin).
- Strava backfill state is stored in `data/backfill_state_strava.json`; Garmin backfill state is stored in `data/backfill_state_garmin.json`. If a backfill hits API limits (unlikely), this state allows the daily refresh automation to pick back up where it left off.
- The Sync action workflow includes a toggle labeled `Reset backfill cursor and re-fetch full history for the selected source` which forces a one-time full backfill. This is useful if you add/delete/modify activities which have already been loaded.
- The GitHub Pages site is optimized for responsive desktop/mobile viewing.
- If a day contains multiple activity types, that day’s colored square is split into equal segments — one per unique activity type on that day.
