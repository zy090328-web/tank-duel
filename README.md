# Graph Paper Tank Duel

A tank game drawn on graph paper, for touch-screen tablets and phones.

**Who plays**

- **One tablet, two players:** each player holds one end of the tablet.
- **One player against the computer:** on the title screen pick `1 + 1 CPU` … `1 + 3 CPU`.
- **Online, 2–5 tanks on their own devices:** one player taps ONLINE → Create a game (or Same Wi-Fi game) and gets a 4-digit code; the others tap ONLINE → Join a game and type it. The creator picks the settings, can add computer tanks (`+ CPU`), and presses START. Each player can set a name; it is shown on the scoreboard.

**Game modes**

| Mode | Rule | Match length (short / normal / long) |
| --- | --- | --- |
| Classic | Last tank standing wins the round. | first to 3 / 5 / 7 rounds |
| Teams | Red against Blue; shots pass through your own side. Needs 3+ tanks; teams are picked in the waiting room. | first to 3 / 5 / 7 rounds |
| Deathmatch | Destroyed tanks come back after 2 s, untouchable for 2 s (until they fire). A kill is +1, destroying yourself −1. | 5 / 10 / 15 kills |
| Hill | Tanks come back; a tank alone in the circle in the middle scores a point a second. | 20 / 30 / 45 seconds |
| Base | Two teams, each with a base and two towers on maps of their own (15×15 up to 3 tanks, 17×17 for more). Towers fire slow, non-bouncing shots at enemies within 5 cells; a base can only be hurt once one of its towers is down. Minion waves march every 20 s (two per lane, more as time goes on); they fight minions and buildings and leave tanks alone. Tanks come back at home, the wait growing with time. A base falling ends it; when time is up the side with more of its base left wins. | 4 / 6 / 8 minutes |

**Terrain** (on by default; the map-extras chip switches it): **grass** hides a tank from enemies unless one is within 1.6 cells or it has just fired; **water** stops tanks but not shots. On a screen shared by two players grass hides no one. Computer tanks see only what a player on their side would see.

Options for every mode: four ammo rules, power-ups (laser, homing and guided missiles, bomb, shield, spread, mine, piercing shot), **breakable walls** (lightly drawn walls break when shot), and the map set. Three and more tanks play on the 13×13 maps, three of which are four-way symmetric. After a match a table shows each tank's score, kills, losses and hit rate.

The game itself is `index.html`. `server.js` serves it and runs online rooms: each room is a copy of the same game script running on the server with drawing switched off, so every player is an equal guest (one network round trip each). Players' own tanks move at once on their device and are corrected toward the server.

**Same Wi-Fi game** (on the game's server): one tablet hosts, and each guest opens a direct WebRTC link to it over the local network (offer/answer passed through the server, no outside STUN). Game data then never leaves the room. If a direct link can't form within the room's network, that guest keeps playing through the server.

Served from anywhere else (no `server.js`), online play falls back to [PeerJS](https://peerjs.com/) with one tablet hosting.

Deploy: Railway builds `server.js` on push. `deploy/setup-server.sh` sets it up on a plain Ubuntu server instead.

`tests/`: Playwright tests for game modes, computer tanks, teams and names (`modes.py`, needs the server on port 8790), map checks (`maps_check.py`), base mode (`base.py`), the bomb (`bomb.py`), coming back protected (`respawn.py`), grass and water (`terrain.py`), server-run rooms (`dedicated.py`, `dedicated_end.py`), tablet-hosted rooms (`run_test.py`, with `mockpeer.js` standing in for PeerJS), landscape controls (`land.py`), and latency/smoothness under simulated lag (`compare.py`, `smooth.py`, using the server's `TEST_LAG_MS` / `TEST_SPIKE`).
