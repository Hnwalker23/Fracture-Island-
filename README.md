# FRACTURE ISLES — playable multiplayer game

A browser-based island strategy game for 2–6 people. Each player has a distinct island, a rotatable software-rendered 3D island scene, buildings, resource production, alliances, trades, global laws, Core crises, and an eight-round win condition. Uses a Python FastAPI WebSocket server with authoritative game logic.

## Run locally

1. Install Python 3.10+.
2. In this folder run `python -m pip install -r requirements.txt`.
3. Run `python -m uvicorn server:app --host 0.0.0.0 --port 8000`.
4. Open `http://localhost:8000` in your browser.
5. For phones on the same Wi-Fi, open `http://YOUR_COMPUTER_LAN_IP:8000` (allow firewall access to port 8000). Create a room and share the six-character code.

## Deploy for public play

Deploy this folder to a Python Web Service on Render, Railway, Fly.io, or a comparable host supporting WebSockets and long-running processes. Start command:

`uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}`

For a managed host, configure one running worker/instance. Enable HTTPS, which automatically uses secure WebSockets (`wss://`). A sleeping free instance may interrupt games. Do **not** use a static-only hosting service like GitHub Pages or Vercel static hosting: this project requires the Python server.

## Limitations / production hardening

- Match state is **in memory**, so restarting or scaling the server resets rooms. Use persistent database-backed transactions and a shared event bus before scaling to multiple instances.
- The server validates actions and uses per-room locks, but is not hardened against abusive public traffic; add rate limits and room cleanup for a public launch.
- The island renderer uses custom JavaScript 3D geometry projected onto a 2D canvas (rotatable 3D-style geometry), **not WebGL/Three.js**. This keeps the project self-contained and offline-installable. It is not a full GPU 3D scene.
- Font download is optional; system fonts are used offline.
- This project has not been deployed to a permanent public URL.
- The user-facing timer is enforced by the server; matches are deliberately quick, and an eight-round game can take less than 10 minutes if players submit early.

## Rules

- Six specialties: Verdantia, Pyrrhos, Aetheria, Solara, Tiderest, Frostholm.
- Each player has six plots, one build/upgrade/ability action per round.
- Four buildings: farm, tower, market, monument. Upgrade once.
- Every round: Build (20s), Diplomacy (35s), Council (15s if a law), Crisis pledge (15s on rounds 3 and 6), Reckoning (automatic).
- Two completed trades per player per round; one active alliance per player.
- Laws: Harvest, Rationing, Trade Incentive, Restoration, Wealth Levy, Emergency Powers.
- Core starts at 70 and loses 3 per round; collapse at 0 causes collective loss.
- Winner after eight rounds: prosperity + 2 per constructed building + well-being + min(8, floor(successful crisis contributions / 3)).

## Quick test

`python -m unittest discover -s tests -v`

## Colorful Fantasy 3D update
The island viewport now uses **real WebGL GPU-rendered 3D geometry**, with a rotatable camera, six different miniature biomes, dimensional buildings, detailed floating rock terrain, a glowing crystal Core and energy bridges in the shared archipelago. No additional frontend dependencies or CDN connection are required. WebGL must be enabled in your browser. Multiplayer backend and gameplay commands are unchanged.

**Important:** These are custom low-poly procedural models, not professionally sculpted or textured commercial-quality assets. Browser visual quality and performance have not yet been verified in an interactive browser session in this environment. The existing game server still stores rooms in memory; deploy as a single server instance unless persistence is added.


## Imported real 3D asset packs

The frontend now loads the uploaded GLB models from `public/assets/` with Three.js.
It uses the Sky Islands pack for actual floating terrain and the Riverside Town pack for houses, markets, and watermills.
The IslandsFreeLand model is also included for future use.

Three.js and GLTFLoader are loaded from esm.sh and therefore require internet access in the browser.
Asset licenses are included in `ASSET_LICENSES.md`. These models are licensed for use in games but may **not** be redistributed as standalone asset packs.
The game server and rules remain unchanged from the previous release.
