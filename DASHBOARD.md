# Blink station watch — deployed 2026-09-16

## Multi-site update — September 23

September 24 correction: restored Redwood City - CN37-12 (1250 Veterans Boulevard, 21 ports) as the first secondary site and second dashboard group. It is distinct from Redwood City SMOB - CN37-20 at 905 Maple Street (26 ports). The earlier removal of CN37-12 was a mistaken interpretation of the request to remove SMOB. Existing serial identifiers and history are preserved for CN37-12; its readings do not switch to the composite port identifiers used by newly added sites.

`sites.json` now supplies the controller and dashboard location list. Confirmed new Blink Favorites: AEM Corporate (145 King Street, Toronto; 5 ports), First Baptist Church of Glenarden (600 Watkins Park Drive, Upper Marlboro; 8 ports), SemaConnect US R&D (4961 Tesla Drive, Bowie; 4 ports), and SemaConnect Bangalore Production facility (4 Level 2 plus 7 DC ports). The last site appears near Bowie in Blink but its address includes Bengaluru; this is app-reported data, not a verified physical location. Redwood has been removed from Favorites and the monitoring rotation; historical records are retained.

Run four Gateway scans, then one secondary site, rotating through the secondary list. A remote failure resets the next scan to Gateway and advances the remote index. Multi-port sites store serial plus port label to avoid overwriting one port with another. Secondary sections are read-only; Start keeps its original exact Gateway serial validation. The mixed Level 2/DC site is scanned across both tabs. Remote status is marked stale after an hour, accounting for the longer round robin; Gateway's existing freshness checks remain.

The app returned no chargers after selecting the North York/Chesswood and Amsterdam/Joop Geesinkweg/Barbara Strozzilaan search results. Those areas are not configured as monitored sites. Search address results are geocoding suggestions; select one to obtain the charger list and compare the denominator of each availability fraction. Favorite a chosen site from its detail page and verify it in My Location. Monitoring must be stopped during manual navigation.

## Two-site monitoring — September 18

The Blink app Favorites now includes `1850 Gateway Drive` and `Redwood City - CN37-12` (1250 Veterans Boulevard, Redwood City). Blink's nearby list showed the latter about 5.6 miles away; its detail screen exposed 21 Level 2 ports. Scheduled scans rotate through four Gateway scans then one Redwood scan. While idle, Gateway stays on its open station list, scanning in alternating scroll directions and stopping when all expected stations are read. Its inter-scan delay is 5 seconds; actual interval also includes UI reads/scrolling. During a known active session the delay is 30 seconds to allow charging-screen checks. Redwood has no polling delay afterward. Location reuse requires either the matching site header or known station IDs mapped to the current site; unexpected pages trigger navigation/recovery. Active-session navigation happens initially and when an active/known/candidate session warrants it, rather than after every idle scan. Status changes wake the sync thread immediately; otherwise sync remains about every 10 seconds and the browser polls every 5 seconds. No network-traffic reduction has been measured. The rotation counter persists across restarts; failed scans do not advance it. On-demand verification for Start does not count toward the rotation. Availability speech remains scoped to Gateway. Site scans serialize with all other phone UI work.

Phone and D1 `station_locations` tables map exact station IDs to a site. Ingestion accepts up to 100 stations per batch (previously 30), so the 40 combined ports can sync. Start requests route to the exact station's recorded favorite and retain the existing fresh-Connected/identity/confirmation checks. The dashboard retains Gateway's user-defined groups, then presents all Redwood stations together as one group in the following section. Missing Gateway IDs remain Unknown; unlisted Gateway IDs share its final group. The new site is not ChargePoint Metro Tower.

The `dashboard/location-schema.sql` migration adds the D1 mapping table; fresh installs also create it through `schema.sql`. Phone controller backup before this change: `~/blink-monitor/controller.before-redwood.py`. Local copy: `.build/controller-before-redwood.py`.

Update: after each passive station scan, scroll back to the site's header before the wait. Subsequent scans start downward from the top instead of alternating directions. This adds return-scroll time to the earlier measured 16-second resident scan interval. Targeted Start verification returns at its exact matching row and is not scrolled away. Active charging still takes priority over the idle station display.

Six-month station-history backfill: `history_backfill.py` runs incrementally inside the controller when SQLite state `history_backfill` contains `cutoff`, `months`, and is not `complete`. It visits one date per step, scrolls all detail cards (including grouped days), saves XML evidence under phone `data/history-backfill`, and imports only records with station/date/start/energy/duration/end. It returns to active-session observation between steps, with a 20-second gap; a history step temporarily delays live readings. Progress keys: `days_done`, `months_done`, `sessions`, `last_day`, `complete`. Requested window starts 2026-03-18. Source timestamps use America/Los_Angeles explicitly. Public dashboard now exposes current charging measurements and per-station aggregates/last successful date; full historical session list, commands, and start controls remain authenticated. Success means completed >=1 kWh; yellow Available means no known success in six calendar months, not proof of failure.

Charging-complete alerts speak “Blink charging is complete. Please unplug your car.” through Termux TTS's ALARM stream, just like availability alerts. Speech and the existing notification repeat every five minutes after confirmed completion until acknowledged or the session ends. Estimated completion and zero power alone do not trigger this alert. Failed alert attempts are rate-limited too.

Live site: https://blink.timkay.com (Cloudflare Worker `blink-timkay`, D1 `blink-station-watch`). Public station statuses; private session history and charging controls. Unlock using `.secrets/admin-key.txt`, NOT the Blink account password. Never publish `.secrets`, phone configuration, or tokens. The browser keeps its key in sessionStorage, not the URL. Device ingestion uses a separate secret.

## What runs where

- Phone `~/blink-monitor/supervise.py` restarts `controller.py` after unexpected exits. The controller owns the same `monitor.lock` as the old monitor, so they must not run together.
- Reads the genuine Blink app using paired phone-local ADB `127.0.0.1:36007`. No direct Blink API and no root.
- Phone SQLite `~/blink-monitor/data/watch.sqlite3` (WAL mode) stores station observations, changes, live readings, session history, commands and a durable event outbox. Network sync every ~10 seconds runs on a separate thread. Network outages do not block UI checks; records remain local.
- D1 keeps the replicated station states, change events, sessions and command audit. Browser refreshes every 5 seconds.
- Active charging checks normally take ~5–6 seconds. Full 19-station scans take roughly 20–35 seconds and occur ~90 seconds after the preceding scan finishes. Active checks pause during scans; this is NOT simultaneous observation. Each row has its own checked timestamp. After 180 seconds it is stale.
- While idle, recent charge history is checked every 10 minutes. Active session monitoring takes priority. History currently reads the newest month/day and visible detail cards, not a full historical backfill. Older sessions are not automatically scraped.

## Charging and identity

Completion recognizes both `Charge Complete` and `Completed` / `Please unplug the connector`, even if power remains nonzero. Zero readings alone mean waiting for data, NOT completed. Reminders repeat every five minutes after confirmed completion, until acknowledgement/session-end evidence. `Start Charge` replacing the active session controls ends monitoring; missing active indicator alone is ambiguous and retained pending history confirmation.

The live active screen does not expose a serial. A single station labelled `Charging` is recorded only as a **candidate**, not confirmed identity. Session history confirms the serial. Website-initiated starts retain the selected serial directly. Labels and history evidence take precedence over assumptions. The 5.65 kWh ETA still assumes an empty Prius Prime; it does not trigger completion alerts.

Verified seed history from the app on September 16:

- BAE607172: 10:26–10:38, 12m04s, 0.59 kWh.
- BAE607172: 10:39–10:41, 2m13s, 0.10 kWh.

Both are below the user's 1 kWh review threshold. This does not establish a hardware fault: manual test interruptions are another explanation. Never label a station broken just because it is In Use, Unavailable, or produced a short session.

## Start button safety

Only shown for `Connected`. Requires private admin key, same-origin request, fresh station/observer, explicit fee confirmation and an idempotency UUID. One pending command globally; commands expire after 120 seconds. Device atomically claims a command, persists it before UI interaction and never automatically retries a potentially executed start.

Controller refuses if another session is known, locates the exact serial in the pinned location, verifies that row is Connected, selects that row, then verifies the exact row again and presses the newly exposed `Start charge` control once. Unexpected UI, missing identity/status, expiration or a pre-existing selection rejects the request. It only reports success after `Charge session started` or `Stop Charge` appears. Otherwise result is uncertain and must be reviewed, not retried blindly.

Read-only row selection has been tested. Actual Connected→paid start has NOT been end-to-end tested; no paid test start was made. If Blink inserts additional confirmation screens, the command stops as uncertain rather than guessing.

## Recovery and limitations

September 17 update: listener changed to `127.0.0.1:45293`; use `set_device_port.py PORT` on the phone to change it without printing credentials, then restart the controller. `arm_availability.py` arms a persistent one-shot alert for fresh **Available** rows only (never Connected). It speaks station suffixes on the ALARM audio stream, vibrates and posts notification 703. While armed, scans run roughly once a minute and history checks are deferred. When idle, the phone remains on the station-status list between scans rather than repeatedly opening history or the map. Active charging still takes priority.

September 18: listener updated to `127.0.0.1:33703`. Repeated UI errors now trigger recovery after three failures: bring Blink forward/wake the display, then if errors persist force-stop only `com.blinknetwork.mobile2` and relaunch. Retries are rate-limited (60 seconds initially, then 5 minutes). A successful observation resets escalation; launching alone does not mark data fresh. Recovery preserves session, alarm and command state, never presses charging controls, never clears app data, and defers optional history for 10 minutes. ADB must actually report `device` before an app recovery is attempted. Locked phones, lost connectivity, login prompts and a genuinely absent favorite may still require intervention; this is not a guarantee of recovery from every Android state.

This is continuous while Android keeps Termux and wireless debugging alive, NOT a promise of reboot survival. Only `com.termux` is currently installed (no separate Termux:Boot). Pairing survives some restarts, but the wireless-debugging listener/port may change or be disabled. Configuration is private at `~/.config/blink-monitor/controller.json`. It currently reconnects to the configured port, not arbitrary new ports.

Keep Blink visible, screen unlocked, Termux battery exemption/background permission enabled. Controller holds the Termux wake lock and sets stay-on-while-powered to 7. A system kill of all Termux processes also kills the supervisor. Do not operate UI concurrently with the controller; pause/stop it for manual diagnostics and restore it afterward.

Logs: `~/blink-monitor/controller.log`. Current persisted state: SQLite `state` table. Old `status.json` belongs to the retired monitor and is NOT current controller status. The dashboard's observer timestamp, not only network heartbeat, determines liveness.

Tests: `python -m unittest test_controller -v`; `node dashboard/test.mjs`; `node dashboard/check-browser.cjs`. Browser test checks public 19 cards, private history hidden, authenticated history visible and browser exceptions. It never presses Start.

Deploy with Node >=22 and Wrangler. Existing CLI path: `/home/timkay/work/fly-v-cloudflare/node_modules/wrangler/bin/wrangler.js`; use `npx -y -p node@22 node … deploy --config dashboard/wrangler.jsonc`. `setup_dashboard.py` installs only this project's D1 schema and secrets. It passes secrets through curl stdin, never arguments/output. Python urllib produced 403/network errors here; curl sync has been verified working.
