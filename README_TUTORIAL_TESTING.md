# Tutorial & testing mode

- The six-screen tutorial appears **before** the create/join room choices on a fresh browser session. Every screen includes an example of a consequence.
- Players can replay it from the home screen or in a match using the **Tutorial** button.
- The server now defaults to long **testing** phase timers: Build 4 minutes, Diplomacy 5 minutes, Council 3 minutes, Core Crisis 3 minutes.
- To use the original short timers: `FI_TIMER_MODE=quick python -m uvicorn server:app --port 8000` (on Windows PowerShell: `$env:FI_TIMER_MODE="quick"; python -m uvicorn server:app --port 8000`).
- Timers are authoritative on the server; changing the browser clock will not affect them.
- The timer now displays `M:SS`.
- Cosmetic improvements include clearer, more luminous world framing and highlighted selection. The 3D asset library and gameplay rules are unchanged.
- Tutorial completion is stored per browser tab session; opening a fresh incognito session shows it again.
