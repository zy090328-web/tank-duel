# Ethan’s Tank Duel

A tank game drawn on graph paper, for touch-screen tablets and phones.

**Who plays**

The title menu goes one step at a time (mode → who plays → rules → START). On a tablet held wide it is laid out wide; a two-player match on one tablet then turns to the two ends of the tablet, while a match against the computer and online play stay wide.

- **One tablet, two players:** each player holds one end of the tablet.
- **One player against the computer:** on the title screen pick `1 + 1 CPU` … `1 + 3 CPU`.
- **Online, 2–5 tanks on their own devices:** one player taps ONLINE → Create a game (or Direct game) and gets a 4-digit code; the others tap ONLINE → Join a game and type it. The creator picks the settings, can add computer tanks (`+ CPU`), and presses START. Each player can set a name; it is shown on the scoreboard.

**Game modes**

| Mode | Rule | Match length (short / normal / long) |
| --- | --- | --- |
| Classic | Last tank standing wins the round. | first to 3 / 5 / 7 rounds |
| Teams | Red against Blue; shots pass through your own side. Needs 3+ tanks; teams are picked in the waiting room. | first to 3 / 5 / 7 rounds |
| Deathmatch | Destroyed tanks come back after 2 s, untouchable for 2 s (until they fire). A kill is +1, destroying yourself −1. | 5 / 10 / 15 kills |
| Hill | Tanks come back; a tank alone in the circle in the middle scores a point a second. | 20 / 30 / 45 seconds |
| Hot Potato | One tank carries a bomb (it appears 2 s in); touching another tank passes it, though not straight back for a second. The bomb goes off after 9–15 s (shorter with more tanks left): its carrier is out and tanks right beside it are dizzy. Shots only stun. Last tank left wins the round. | first to 3 / 5 / 7 rounds |
| Gun Game | Like Deathmatch, but every kill moves you on to the next weapon: Spread → Bomb → Laser (short), Shot → Spread → Pierce → Bomb → Laser (normal), Shot → Spread → Pierce → Bomb → Homing → Guided → Laser (long). Destroying yourself costs a weapon. No pickups. | 3 / 5 / 7 weapons |
| Tank Soccer | Red against Blue on pitches of their own (13×13, or 15×15 for 4–5 tanks), 1 against 1 or more. Drive into the ball or shoot it; blasts and lasers move it too. Tanks cannot enter a goal; shots only stun. A goal ends the round (with a replay); 90 s without one is a draw. | first to 3 / 5 / 7 goals |
| Infection | One tank starts as a zombie (each round a different one). A zombie has no gun: it drives faster, its FIRE button is a short dash, and touching a survivor turns that tank into a zombie on the spot. Survivors shoot; a zombie takes two shots and comes back after 3 s. A survivor destroyed by its own shot comes back as a zombie. When time is up (30 s with 2 tanks, 40 with 3, 50 with 4–5) every survivor scores; if everyone is caught, the last one caught scores. | first to 3 / 5 / 7 points |
| Base | Two teams, each with a base and two towers on maps of their own (15×15 up to 3 tanks, 17×17 for more). Towers fire slow, non-bouncing shots at enemies within 5 cells; a base can only be hurt once one of its towers is down. Minion waves march every 20 s (two per lane, more as time goes on); they fight minions and buildings and leave tanks alone. Tanks come back at home, the wait growing with time. A base falling ends it; when time is up the side with more of its base left wins. | 4 / 6 / 8 minutes |

**Dropping out and coming back** (on the game's own server): each device keeps a random key, and the server gives a player the same id whenever it joins with it. A player whose line drops (the browser sent to the background, the screen locked, the network gone) keeps their seat for 3 minutes: their tank stands still, and the game reconnects by itself as soon as the page is back. After the page was closed, the online screen offers "Rejoin game ####" for 10 minutes. A tablet host whose line drops keeps its room for 3 minutes and takes it back by itself; guests see that it is away. A server-run room everyone dropped out of stays open for 5 minutes. Leaving with the Leave / menu buttons frees the seat at once.

**Gatling**: maps 0, 3, 5, 9 and 11 have a spot in the middle where a gatling appears 6 s into a round (in Classic, Teams, Deathmatch and Infection, whether power-ups are on or not) and comes back 15 s after it is taken. One press fires a 2.2 s stream of about 30 short, once-bouncing shots, a little off line; the tank drives at about half speed meanwhile.

**Terrain** (on by default; the map-extras chip switches it): **grass** hides a tank from enemies unless one is within 1.6 cells or it has just fired; **water** stops tanks but not shots. On a screen shared by two players grass hides no one. Computer tanks see only what a player on their side would see.

**Replay**: in every mode but Hill and Base, the kill (or goal) that ended a round is shown again in slow motion (about half speed, at most 4 s), with the path the shot took. Every device replays what it recorded itself; the host only sends the time of the kill and when the replay runs. Anyone can tap Skip.

**Party rules** (Rules → Party rule): Off, Random (a different one every round) or one of eight: Super bounce, Turbo, Big tanks, Rapid fire, Pickup storm, Slow shots, Bank shots (a shot hurts only after a bounce), Fog. A rule only changes tuning values for the round; guests get the round's rule with the snapshot.

**Leaderboard**: online matches in which at least two players have set a name are recorded on the server (server-run rooms directly; Same Wi-Fi hosts send `POST /result`). `GET /board` gives totals per player, this week's leaders and head-to-head records; the title screen and the online screen open it. Results are kept in `board.json` under `DATA_DIR` (on Railway a volume mounted at `/data`).

Options for every mode: four ammo rules, power-ups (laser, homing and guided missiles, bomb, shield, spread, mine, piercing shot; an armed mine is hidden from the other side unless a tank is within 1.3 cells, faint to its own side, and a bare smudge when two share a screen), **breakable walls** (lightly drawn walls break when shot), and the map set. Three and more tanks play on the 13×13 maps, three of which are four-way symmetric. After a match a table shows each tank's score, kills, losses and hit rate.

The game itself is `index.html`. `server.js` serves it and runs online rooms: each room is a copy of the same game script running on the server with drawing switched off, so every player is an equal guest (one network round trip each). Players' own tanks move at once on their device and are corrected toward the server.

**Direct game** (on the game's server): one tablet hosts, and each guest opens a direct WebRTC link to it (offer/answer passed through the server). On one Wi-Fi the link stays on the local network; between different networks STUN servers that answer inside mainland China (Xiaomi, Tencent, Bilibili) plus Cloudflare/Google let the devices connect straight to each other. If a direct link can't form (some mobile networks block it), that guest keeps playing through the server.

Served from anywhere else (no `server.js`), online play falls back to [PeerJS](https://peerjs.com/) with one tablet hosting.

Deploy: Railway builds `server.js` on push. `deploy/setup-server.sh` sets it up on a plain Ubuntu server instead.

`tests/`: Playwright tests for game modes, computer tanks, teams and names (`modes.py`, needs the server on port 8790), Infection, replays and the mode cards (`infect_replay.py`), Tank Soccer, Hot Potato and Gun Game (`new_modes.py`), dropping out and coming back (`rejoin.py`), the gatling and hidden mines (`gatling_mines.py`), map checks (`maps_check.py`), base mode (`base.py`), party rules (`party.py`), the leaderboard (`board.py`, starts its own server), the bomb (`bomb.py`), coming back protected (`respawn.py`), grass and water (`terrain.py`), server-run rooms (`dedicated.py`, `dedicated_end.py`), tablet-hosted rooms (`run_test.py`, with `mockpeer.js` standing in for PeerJS), landscape controls (`land.py`), and latency/smoothness under simulated lag (`compare.py`, `smooth.py`, using the server's `TEST_LAG_MS` / `TEST_SPIKE`).
