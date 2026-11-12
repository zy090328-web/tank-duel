# Base mode: towers, bases, minions, the time limit, and the same on a guest's screen and in a
# server-run room. Needs the server on port 8790 (with TEST_HOOKS=1 is fine too).
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False
STEP = "(n) => { const T = __tank; for (let i = 0; i < n; i++) T.update(1 / 120); }"

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)

    # ---------- menu ----------
    M = await page('menu', 820, 1180)
    cards = await ev(M, "__tank.menuItems().map(it => [it.kind, it.v || '', it.x, it.y, it.w, it.h])")
    boxes = [c[2:] for c in cards]
    overlap = any(not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]) for i, a in enumerate(boxes) for b in boxes[i + 1:])
    kinds = sorted(c[0] for c in cards)
    check(kinds == ['board', 'game', 'game', 'game', 'game', 'game', 'online'] and not overlap and all(c[2] > 0 and c[2] + c[4] < 820 for c in cards), f'step 1 shows five mode cards, Online and Leaderboard, none overlapping {kinds}')
    q = await ev(M, "(() => { const it = __tank.menuItems().find(it => it.kind === 'game' && it.v === 'base'); return it && [it.x + it.w / 2, it.y + it.h / 2]; })()")
    await M.mouse.click(q[0], q[1]); await M.wait_for_timeout(100)
    check(await ev(M, "__tank.settings().game") == 'base' and await ev(M, "__tank.menuStep") == 'who', 'tapping Base picks it and moves on to who plays')
    q = await ev(M, "(() => { const it = __tank.menuItems().find(it => it.kind === 'step'); return [it.x + it.w / 2, it.y + it.h / 2]; })()")
    await M.mouse.click(q[0], q[1]); await M.wait_for_timeout(100)
    check(await ev(M, "__tank.menuStep") == 'mode', 'Back returns to the modes')
    await M.close()

    # ---------- two players on one screen ----------
    L = await page('local', 820, 1180)
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'base', cpu: 0, terrain: false, powerups: false, winScore: 3 }))")
    await L.keyboard.press('Enter'); await L.wait_for_timeout(2400)
    info = await ev(L, "({ st: __tank.state, map: __tank.mapId, base: __tank.BASEMAPS.has(__tank.mapId), n: __tank.structs.length, team: __tank.teamOf, size: __tank.COLS })")
    check(info['st'] == 'play' and info['base'] and info['n'] == 6 and info['team'] == [0, 1] and info['size'] == 15, f'match on a 15x15 base map with 2 towers and a base each {info}')
    # the base shrugs off hits while both towers stand
    await ev(L, "(() => { const T = __tank, c = T.structs.find(s => s.kind === 'core' && s.team === 1); T.damageStruct(c, 5, 0); })()")
    check(await ev(L, "__tank.structs.find(s => s.kind === 'core' && s.team === 1).hp") == 20, 'base takes no damage while both its towers stand')
    # a real shot at a tower hurts it
    await ev(L, r"""(() => { const T = __tank, s = T.structs.find(s => s.kind === 'tower' && s.team === 1), a = T.tanksNow[0], W = T.walls;
      // a free cell 1.5 to 3.5 cells away with a clear line to the tower's face
      for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) {
        if (W[r][c] || T.water[r * T.COLS + c]) continue;
        const x = c + 0.5, y = r + 0.5, d = Math.hypot(x - s.x, y - s.y);
        if (d < 1.5 || d > 3.5) continue;
        const fx = s.x + (x - s.x) / d * 0.55, fy = s.y + (y - s.y) / d * 0.55;
        let clear = true;
        for (let i = 0; i <= 40; i++) if (T.circleHitsWall(x + (fx - x) * i / 40 * 0.95, y + (fy - y) * i / 40 * 0.95, 0.1)) clear = false;
        if (!clear) continue;
        a.x = x; a.y = y; a.angle = Math.atan2(fy - y, fx - x); a.cool = 0; a.inv = 0; T.tanksNow[1].x = 1e3; T.fire(a); return d;
      }
      return 0; })()""")
    await ev(L, STEP, 60)
    hp = await ev(L, "__tank.structs.find(s => s.kind === 'tower' && s.team === 1).hp")
    check(hp == 9, f'a shot takes one off a tower ({hp})')
    # bring both blue towers down: the base opens, the cells open, red scores
    await ev(L, "(() => { const T = __tank; T.structs.filter(s => s.kind === 'tower' && s.team === 1).forEach(s => T.damageStruct(s, 20, 0)); })()")
    st = await ev(L, "(() => { const T = __tank, s = T.structs.filter(s => s.kind === 'tower' && s.team === 1); return [s.map(x => x.hp), s.map(x => T.walls[x.r][x.c]), T.scores]; })()")
    check(st[0] == [0, 0] and st[1] == [False, False] and st[2][0] == 2, f'fallen towers free their cells and count for red {st}')
    await ev(L, "(() => { const T = __tank, c = T.structs.find(s => s.kind === 'core' && s.team === 1); T.damageStruct(c, 20, 0); })()")
    await ev(L, STEP, 600)
    check(await ev(L, "__tank.state") == 'matchEnd' and await ev(L, "__tank.baseWinner") == 0, 'red wins when the blue base falls')
    await L.screenshot(path='/tmp/terr/base_local_end.png')
    await L.close()

    # ---------- alone with computer tanks: waves, towers firing, time limit ----------
    S = await page('solo', 1180, 820)
    await ev(S, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'base', cpu: 3, terrain: true, powerups: true, winScore: 3 }))")
    await ev(S, "(() => { __tank.beginFromMenu(); __tank.bots.add(0); })()")
    await ev(S, STEP, 120 * 2 + 120 * 6)
    check(await ev(S, "__tank.COLS") == 17 and await ev(S, "__tank.minions.length") >= 4, 'four tanks play on 17x17; the first wave marches')
    shot = False
    for _ in range(30):
      await ev(S, STEP, 120)
      if await ev(S, "__tank.shells.length") > 0: shot = True; break
    check(shot, 'towers or minions fire')
    await ev(S, "__tank.roundTv = 239.5"); await ev(S, STEP, 120 * 3)
    check(await ev(S, "__tank.state") == 'matchEnd', 'the match ends when time is up (4 min)')
    await S.close()

    # ---------- online (this tablet hosts): the guest sees the same ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 5, game: 'base', soft: false, terrain: true })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(500)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    check(await ev(G, "__tank.lobby.teams") == [0, 1], f'the two players start on opposite teams {await ev(G, "__tank.lobby.teams")}')
    check(any(it['kind'] == 'team' for it in await ev(H, "__tank.net.netItems()")), 'team chips show in the waiting room')
    await ev(H, "__tank.applyMenu({ kind: 'bots', v: 1 })"); await ev(H, "__tank.applyMenu({ kind: 'bots', v: 1 })"); await H.wait_for_timeout(500)
    await H.screenshot(path='/tmp/terr/base_lobby.png')
    await ev(H, '__tank.net.hostStart()')
    for _ in range(40):
      if await ev(G, '__tank.state') == 'play': break
      await G.wait_for_timeout(250)
    check(await ev(G, "__tank.structs.length") == 6 and await ev(G, "__tank.settings().game") == 'base', 'guest has the towers and bases')
    await G.wait_for_timeout(6000)
    check(await ev(G, "__tank.minions.length") > 0, f'guest sees minions ({await ev(G, "__tank.minions.length")})')
    await ev(H, "(() => { const T = __tank; T.structs.filter(s => s.kind === 'tower' && s.team === 0).slice(0, 1).forEach(s => T.damageStruct(s, 20, 1)); })()")
    await G.wait_for_timeout(500)
    gs = await ev(G, "(() => { const T = __tank, s = T.structs.filter(s => s.kind === 'tower' && s.team === 0)[0]; return [s.hp, T.walls[s.r][s.c]]; })()")
    check(gs == [0, False], f'a tower falling reaches the guest {gs}')
    await G.screenshot(path='/tmp/terr/base_guest.png'); await H.screenshot(path='/tmp/terr/base_host.png')
    await ev(H, "(() => { const T = __tank, c = T.structs.find(s => s.kind === 'core' && s.team === 0); T.damageStruct(c, 30, 1); })()")
    for _ in range(20):
      if await ev(G, '__tank.state') == 'matchEnd': break
      await G.wait_for_timeout(250)
    await G.wait_for_timeout(1500)
    check(await ev(G, "__tank.state") == 'matchEnd' and await ev(G, "__tank.baseWinner") == 1, 'guest sees blue win')
    await G.screenshot(path='/tmp/terr/base_guest_end.png')
    await H.close(); await G.close()

    # ---------- server-run room ----------
    A = await page('ann'); B = await page('bo')
    await ev(A, "__tank.setSettings({ ammo: 'unlimited', powerups: true, maps: 'all', winScore: 5, game: 'base', soft: true, terrain: true })")
    await ev(A, '__tank.net.goOnline()'); await A.wait_for_timeout(500)
    await ev(A, '__tank.net.startHosting()'); await A.wait_for_timeout(1500)
    code = await ev(A, '__tank.net.code')
    await ev(B, f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(1500)
    await ev(A, "__tank.net.sendCmd('bots', 2)"); await A.wait_for_timeout(500)
    await ev(A, "__tank.net.sendCmd('start')")
    for _ in range(40):
      if await ev(B, '__tank.state') == 'play': break
      await B.wait_for_timeout(250)
    await B.wait_for_timeout(8000)
    check(await ev(B, "__tank.settings().game") == 'base' and await ev(B, "__tank.minions.length") > 0 and await ev(B, "__tank.NP") == 4, 'server-run base room: 4 tanks, minions marching')
    await B.screenshot(path='/tmp/terr/base_server_guest.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
