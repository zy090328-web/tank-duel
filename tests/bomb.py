# The bomb power-up: hits a tank head-on, hurts tanks near where it goes off, spares its own tank
# up close, breaks breakable walls, and shows up on a guest's screen. Needs the server on port 8790.
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# place two tanks on the current map: shooter facing +x with `gap` open cells ahead, target offset from the line
PLACE = r"""
([gap, off, wallAhead]) => {
  const T = __tank, W = T.walls, C = T.COLS, R = T.ROWS, open = (c, r) => c >= 0 && r >= 0 && c < C && r < R && !W[r][c];
  for (let r = 1; r < R - 1; r++) for (let c = 1; c < C - 1; c++) {
    let ok = true;
    for (let k = 0; k <= gap; k++) if (!open(c + k, r)) ok = false;
    if (wallAhead && open(c + gap + 1, r)) ok = false;
    const tr = r + (off > 0 ? 1 : off < 0 ? -1 : 0);
    if (off && !open(c + gap, tr)) ok = false;
    if (!ok) continue;
    const [a, b] = T.tanksNow;
    a.x = c + 0.5; a.y = r + 0.5; a.angle = 0; a.power = 'bomb'; a.cool = 0; a.shield = 0;
    b.x = c + gap + 0.5 - (wallAhead ? 0 : 0); b.y = r + 0.5 + off; b.shield = 0;
    return [c, r];
  }
  return null;
}
"""

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    async def fresh(p):
      await ev(p, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'dm', cpu: 0, soft: false, powerups: false, winScore: 7 }))")
      await ev(p, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()")
      await p.wait_for_timeout(2400)

    L = await page('local', 820, 1180)
    check('bomb' in await ev(L, '__tank.POWER_TYPES'), 'bomb is one of the pickups')

    # 1. head-on: the bomb flies 3 cells and destroys the tank it touches; the shooter is fine
    await fresh(L)
    pos = await ev(L, PLACE, [3, 0, False])
    check(pos is not None, f'found an open row {pos}')
    await ev(L, "__tank.usePower(__tank.tanksNow[0])")
    m = await ev(L, "__tank.missiles.map(m => m.type)")
    check(m == ['bomb'], f'bomb in flight {m}')
    await L.wait_for_timeout(1300)
    al = await ev(L, "__tank.tanksNow.map(t => t.alive)"); sc = await ev(L, '__tank.scores')
    check(al == [True, False] and sc[0] == 1, f'head-on hit: target destroyed, shooter alive, kill counted {al} {sc}')
    await L.screenshot(path='/tmp/bomb_local.png')

    # 2. near miss: the bomb passes beside the target into a wall; the blast still gets it
    await fresh(L)
    pos = await ev(L, PLACE, [3, 0.85, True])
    if pos is None: pos = await ev(L, PLACE, [2, 0.85, True])
    check(pos is not None, f'found a row ending in a wall {pos}')
    await ev(L, "__tank.usePower(__tank.tanksNow[0])"); await L.wait_for_timeout(1500)
    al = await ev(L, "__tank.tanksNow.map(t => t.alive)")
    check(al == [True, False], f'splash: tank beside the impact point destroyed {al}')

    # 3. out of reach: a tank 2 cells from the impact survives
    await fresh(L)
    pos = await ev(L, PLACE, [3, 0, True])
    # move the target away so the bomb flies on into the wall 3 cells ahead
    await ev(L, "(() => { const T = __tank, [a, b] = T.tanksNow, W = T.walls; for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (!W[r][c] && Math.hypot(c + 0.5 - a.x, r + 0.5 - a.y) > 5) { b.x = c + 0.5; b.y = r + 0.5; return; } })()")
    await ev(L, "__tank.usePower(__tank.tanksNow[0])"); await L.wait_for_timeout(1600)
    al = await ev(L, "__tank.tanksNow.map(t => t.alive)")
    check(al[0], f'shooter not hurt by its own bomb landing 3 cells away {al}')

    # 4. point-blank into a wall: the shooter is spared
    await fresh(L)
    pos = await ev(L, PLACE, [0, 0, True])
    await ev(L, "(() => { const T = __tank, b = T.tanksNow[1], W = T.walls; for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (!W[r][c] && Math.hypot(c + 0.5 - T.tanksNow[0].x, r + 0.5 - T.tanksNow[0].y) > 4) { b.x = c + 0.5; b.y = r + 0.5; return; } })()")
    await ev(L, "__tank.usePower(__tank.tanksNow[0])"); await L.wait_for_timeout(700)
    check(await ev(L, "__tank.tanksNow[0].alive") and not await ev(L, "__tank.missiles.length"), 'bomb fired into a wall at point-blank goes off but spares the shooter')

    # 5. a shield takes the blast
    await fresh(L)
    pos = await ev(L, PLACE, [3, 0, False])
    await ev(L, "__tank.tanksNow[1].shield = 3")
    await ev(L, "__tank.usePower(__tank.tanksNow[0])"); await L.wait_for_timeout(1300)
    check(await ev(L, "__tank.tanksNow[1].alive") and await ev(L, "__tank.tanksNow[1].shield") == 0, 'a shield stops the bomb once')

    # 6. breakable walls near the blast break
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), { soft: true }))")
    await ev(L, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()"); await L.wait_for_timeout(2400)
    found = await ev(L, r"""() => {
      const T = __tank, W = T.walls, C = T.COLS;
      for (let i = 0; i < T.soft.length; i++) if (T.soft[i]) {
        const r = (i / C) | 0, c = i % C;
        for (let k = 1; k <= 3; k++) { if (c - k < 0 || W[r][c - k]) break; if (k === 3 || (k >= 2 && c - k - 1 >= 0 && W[r][c - k - 1])) {
          const a = T.tanksNow[0]; a.x = c - k + 0.5; a.y = r + 0.5; a.angle = 0; a.power = 'bomb'; a.cool = 0; T.tanksNow[1].x = 1e3; return i; } }
      }
      return -1; }""")
    if found >= 0:
      await ev(L, "(() => { const T = __tank, b = T.tanksNow[1], a = T.tanksNow[0], W = T.walls; for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (!W[r][c] && Math.hypot(c + 0.5 - a.x, r + 0.5 - a.y) > 5) { b.x = c + 0.5; b.y = r + 0.5; return; } })()")
      n0 = await ev(L, "__tank.broken.length")
      await ev(L, "__tank.usePower(__tank.tanksNow[0])"); await L.wait_for_timeout(1300)
      check(await ev(L, "__tank.broken.length") > n0, 'the blast breaks breakable walls')
    else: print('   (no breakable wall with room in front on this map; skipped)')

    # 7. computer tanks use bombs without errors
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), { cpu: 3, powerups: true }))")
    await ev(L, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()"); await L.wait_for_timeout(2400)
    for _ in range(12):
      await ev(L, "__tank.tanksNow.forEach((t, i) => { if (i && t.alive && !t.power) t.power = 'bomb'; })"); await L.wait_for_timeout(1000)
    st = await ev(L, '__tank.stats')
    check(sum(v['s'] for v in st) >= 0 and await ev(L, '__tank.state') in ('play', 'ending', 'result', 'matchEnd'), f'12 s of computer tanks with bombs ran ({[v["k"] for v in st]} kills)')
    await L.close()

    # 8. online (this tablet hosts): the guest sees the bomb and the blast
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 7, game: 'dm', soft: false })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(500)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()')
    for _ in range(40):
      if await ev(G, '__tank.state') == 'play': break
      await G.wait_for_timeout(250)
    pos = await ev(H, PLACE, [4, 0, False])
    await ev(H, "__tank.usePower(__tank.tanksNow[0])"); await G.wait_for_timeout(250)
    gm = await ev(G, "__tank.missiles.map(m => m.type)")
    check(gm == ['bomb'], f'guest sees a bomb in flight {gm}')
    await G.screenshot(path='/tmp/bomb_guest_flight.png')
    await G.wait_for_timeout(1500)
    check(not await ev(G, "__tank.tanksNow[1].alive") or await ev(G, "__tank.tanksNow[1].respawn") > 0 or await ev(G, '__tank.scores[0]') >= 1, 'guest tank destroyed by the bomb')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
