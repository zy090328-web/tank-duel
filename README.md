# Graph Paper Tank Duel

A tank duel drawn on graph paper, for touch-screen tablets.

- **One tablet, two players:** each player holds one end of the tablet.
- **Online, 2–5 players on their own devices:** one player taps ONLINE → Create a game and gets a 4-digit code; the others tap ONLINE → Join a game and type it. The creator picks the settings and presses START.

The game itself is `index.html`. `server.js` serves it and runs online rooms: each room is a copy of the same game script running on the server with drawing switched off, so every player is an equal guest (one network round trip each). Players' own tanks move at once on their device and are corrected toward the server.

Served from anywhere else (no `server.js`), online play falls back to [PeerJS](https://peerjs.com/) with one tablet hosting.

Deploy: Railway (Singapore) builds `server.js` on push. `deploy/setup-server.sh` sets it up on a plain Ubuntu server instead.

`tests/`: Playwright tests for server-run rooms (`dedicated.py`, `dedicated_end.py`), tablet-hosted rooms (`run_test.py`, with `mockpeer.js` standing in for PeerJS), landscape controls (`land.py`), and latency/smoothness under simulated lag (`compare.py`, `smooth.py`, using the server's `TEST_LAG_MS` / `TEST_SPIKE`).
