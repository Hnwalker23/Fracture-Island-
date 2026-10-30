# Fracture Isles

A browser multiplayer island game for 2 to 6 players. Each round, players take turns in seat order and make one choice. Build your island, trade with another player, or set a shared law. Keep the Core alive for eight rounds; the highest score wins.

## Play locally

1. Install Python 3.10 or newer.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Start the server: `python -m uvicorn server:app --host 127.0.0.1 --port 8000`.
4. Open `http://127.0.0.1:8000`.
5. Create a room, invite at least one other player, choose islands, then start.

## Turn order

The host chooses first, then each other player chooses in order. After making one choice, you wait until the next round. A turn times out after 45 seconds and becomes a pass.

Each turn, choose one action: build a Farm, Tower, or Monument; gather 2 food or energy; repair the Core; pass; offer a trade; accept a trade on your turn; or set next round's law.

- Farm: costs 1 energy, scores 1 point, and produces food each round. Tower: costs 1 food, scores 1 point, and produces energy. Monument: costs 2 food and 2 energy, and scores 3 points.
- Repair: spend 1 energy to restore 12 Core health. Balanced law makes the Core lose 8 health each round.
- Trade: offer another player 1 food for 1 energy, or 1 energy for 1 food. You use your action to offer; the recipient uses their action to accept. Choosing another action declines and returns the offered resource.
- Set a law: use your action to set Balanced, Harvest, or Power for the next round. Balanced has normal production and Core loss 8. Harvest adds 1 food per Farm and makes the Core lose 10. Power adds 1 energy per Tower and makes the Core lose 10. Later players can change the law; the last law set before the round ends applies next round.

If the Core reaches zero, everyone loses. If it survives round eight, the highest score wins; ties go to the player who joined first. The server is authoritative and stores rooms in memory, so restarting it ends active games.
