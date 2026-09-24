# Blink live-session API investigation — 2026-09-14

Source: installed Blink APK, extracted Hermes v96 bundle, disassembled with P1sec/hermes-dec. Artifacts: `.build/blink-apk/base.apk`, `.build/blink-apk/assets/index.android.bundle`, `.build/blink.hasm`. No login secrets have been extracted or copied.

## Confirmed endpoint discovery

Base URL from native DEX strings: `https://apigw.blinknetwork.com/`.

- GET `mobile/v1/active-sessions?isHome=false`
- GET `mobile/v2/users/active-sessions`

Both endpoints return HTTP 401 without authentication and with our independently acquired Blink bearer token. No successful live-session payload captured yet. `retrieveActiveSessions` selects between them using Firebase remote config `isMultiSessionApiEnabled`. See disassembly around line 548550. GET request construction uses API_BASE_URL + path and a 45000ms timeout (around 533560).

Screen processing of active-session responses reads: `currentSpeed`, `energyDelivered`, `chargingTime`, `percentageOfCharging`, `estTimeToFullCharge`, `estCost`, `estMiles`, `proRate`, `proRateUnit`, `proRateInterval`. These are field names from code, not proof that this particular charger supplies them all (especially battery percentage and ETA). See disassembly around 877875.

## Authentication

OIDC discovery verified at `https://account.blinknetwork.com/auth/realms/blinkcharging/.well-known/openid-configuration`.

Token endpoint: `https://account.blinknetwork.com/auth/realms/blinkcharging/protocol/openid-connect/token`. The app uses accessToken/refreshToken and the realm `blinkcharging`. Discovery advertises authorization_code, refresh_token and password grants among others, with S256 PKCE. Supported server grants do not prove that a particular client can use each grant. The client ID/redirect configuration still needs tracing.

Native BuildConfig confirms CLIENT_ID=`mobile-app`, scope=`openid email profile offline_access`, and APP_AUTH_REDIRECT_SCHEME=`com.blinkcharging.demo`. App version 3.1.39 / version code 2511. Exact REDIRECT_URI still needs extracting before building an authorization-code login.

`adb shell run-as com.blinknetwork.mobile2 id` fails because the production app is not debuggable. Do not assume Termux or ADB can read its private token storage. Do not uninstall/re-sign the user's logged-in app to bypass that limitation.

### Independent login and Firebase trace (2026-09-14)

Password-grant login with client `mobile-app` succeeded using the user's supplied credentials. `api_login.py` prompts interactively. Tokens are stored ONLY on the phone at `~/.config/blink-monitor/tokens.json`, mode 600. Do not print or copy them into notes. Access-token lifetime reported 604800 seconds. Ubuntu network access failed during login; phone networking worked.

`api_probe.py` performs read-only diagnostics and prints only token metadata and response key names/status, not account values or token strings. Verified:

- OIDC `/auth/realms/blinkcharging/protocol/openid-connect/userinfo`: HTTP 200 with our bearer token.
- API gateway `mobile/v1/users`: HTTP 401.
- Both active-session endpoints: HTTP 401.
- Adding app version, device OS/version/locale and Android package headers did not change those 401 responses. X-Android-Cert and both Firebase headers were not supplied. No WWW-Authenticate explanation was returned.

Thus our login token is valid at the identity provider, but gateway authorization is unresolved; lack of an active session cannot explain the unrelated users endpoint failure. This does not establish which missing header or token property causes rejection.

Static trace in `.build/blink.hasm`:

- Function 14205 (around 546145): request interceptor adds bearer accessToken, calls setCommonHeaders, and adds X-Firebase-IdToken for URLs containing guest/user.
- Function 13972 (around 539340): common headers include X-Firebase-AppCheck plus x-app-version, device-os-version, os-type, device-locale, X-Android-Cert and X-Android-Package.
- Function 13989 (around 539856): getIdToken checks remote config `isAnonymousLoginEnabledForRegDriver`; registered-user requests return an empty string if disabled. Otherwise reads Firebase auth currentUser and calls currentUser.getIdToken(). Returns null if no currentUser; does NOT exchange the Blink password or OAuth token here.
- Function 20353 (around 825004): app-specific anonymous Firebase sign-in calls auth().signInAnonymously(). This is a separate Firebase identity, not necessarily the Blink account identity. No custom-token exchange found in app-specific code; signInWithCustomToken occurrences found are SDK wrappers.
- Function 13967 (around 538916): getAppCheckToken calls firebase.appCheck().getToken().
- Function 5436 (around 232165): initializes Android App Check with provider `playIntegrity` and token auto-refresh enabled. Therefore App Check requires the Firebase/Play Integrity flow, not merely a token computed from the user's password. Static analysis proves configured provider, NOT gateway enforcement.

No Firebase token obtained yet. Do not claim API monitoring works. Next useful options: investigate the legitimate driver web portal's own API flow, or test through the genuine app; standalone Python App Check generation has not been established. Preserve working ADB screen monitoring.

### Follow-up probes: App Check enforcement confirmed at Firebase Auth

- Added installed APK signing certificate SHA-1 as X-Android-Cert to api_probe.py. The gateway account and session requests still returned 401.
- Implemented firebase_probe.py using the documented Firebase anonymous sign-in REST endpoint (`https://firebase.google.com/docs/reference/rest/auth`). Public client configuration comes from APK Android resources; do not confuse this API key with a secret user token.
- Anonymous sign-in without package/certificate headers returned HTTP 403: `Requests from this Android client application <empty> are blocked.`
- With the installed app's package name and signing-certificate headers, the same request returned HTTP 401: `Firebase App Check token is invalid.` No Firebase identity/token was successfully obtained or stored.
- This directly establishes that THIS Firebase Auth anonymous sign-in route requires App Check; it does not independently prove which check the Blink API gateway is rejecting.
- App Check's configured Android provider is Play Integrity. Reproducing only user login, anonymous sign-in and public metadata is insufficient. Do not use embedded development debug tokens or modify/uninstall the logged-in production app as a shortcut.
- Website follow-up: current U.S. driver FAQ directs account/history/session features to the app; advertised web portal is for hosts. No supported U.S. driver live-session website found. Prior web-portal suggestion was speculative, not a discovered alternative.
- Checked actual Blink Account > Notifications > App: Charge Status ON; Marketing Updates OFF. There is no separate completion toggle on that screen. No settings were changed. User reports completion notifications used to arrive and stopped despite no settings changes. Cause and intent remain unknown.

## Important completion and plug-state findings

Vehicle statuses defined in the bundle include FULLCHARGE, CHARGING, CONNECTED, IDLE, FAULT, PAUSE, NOT_CONNECTED, COMPLETE, OFFLINE, UNAVAILABLE, AVAILABLE, ERROR, SUSPENDED, COMPLETED_AND_OCCUPIED, STOPPED_AND_OCCUPIED and FAULTED.

The Station Port UI displays “Charge Complete” when status is STOPPED_AND_OCCUPIED (disassembly around 876430). Thus app code does distinguish stopped-but-occupied. Actual authenticated API state and post-unplug transition remain to be captured; do not equate a mere missing UI with unplugging.

At approximately 14:55 on 2026-09-14 the user reported completion. UI capture showed `Charge Complete` / `parkingFee` and `Parking fees may apply`, but still displayed 3.12 kW and 5.48 kWh. This disproves the original assumption that displayed power must fall to zero on completion. The monitor was corrected to recognize the exact Charge Complete label and entered stopped state at 14:56:17. It retains low-power confirmation as fallback. It does not press Stop Charge.

Energy plateaus in captured CSVs: 4.70 kWh from 14:34:15 to 14:43:55 (~9m40s); 5.48 kWh from 14:44:28 through at least 14:55:40 (~11m11s). The first plateau happened before completion, so no-energy-change alone is not a reliable stop detector. These are observed intervals, not necessarily the full durations. Restarting the script reset its displayed `since` timer; CSV history provides the longer continuous plateau.

Around 14:58 the screen changed from Charge Complete/Stop Charge to Start Charge, 0.00 kW, 0.00 kWh, Occupancy Time 0, plus a dialog: “Thank you for charging!” / “Your charging session ended at: 1850 Gateway Drive. Please move your vehicle.” Captured in observation-8.xml and observation-9.xml under `data/unplug-observation/`. This is a concrete session-ended signal, consistent with the planned unplugging; it is not a universal proof of physical unplugging because sessions can also be ended manually. Monitor now ends reminders on Start Charge plus either that dialog or a previously confirmed stopped state.
