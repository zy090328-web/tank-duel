# Graph Paper Tank Duel

A tank duel drawn on graph paper, for touch-screen tablets.

- **One tablet, two players:** each player holds one end of the tablet.
- **Online, 2–5 tablets on the same Wi-Fi:** one tablet taps ONLINE → Host a game and shows a 4-digit code; the others tap ONLINE → Join a game and type it.

Everything is in `index.html`. Online play uses [PeerJS](https://peerjs.com/) (WebRTC): the host tablet runs the game and sends snapshots; the other tablets send their controls.

`tests/` holds a local stand-in for PeerJS (`mockpeer.js`) and a Playwright test that runs a host and four guests in one browser.
