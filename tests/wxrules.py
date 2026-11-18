# Weather rules: on snow maps tanks slide, on rainy maps lightning shows every tank for a moment (a cloak still
# hides), sandstorm gusts bend shots and push tanks, drifting fog banks hide whoever is inside; a setting, on unless
# switched off, the same for everyone online.  python3 tests/wxrules.py http://127.0.0.1:8790/
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# a solo match against one computer tank on a map of the given weather, held still (both tanks placed by hand)
ON = r"""
([kind, rules]) => { const T = __tank;
  T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 1, maps: 'all', powerups: false, terrain: true, soft: false, wxRules: rules }));
  let id = -1; for (let i = 0; i < T.MAPS.length; i++) if (T.themeOf(i) === kind && !T.BIG_MAPS.has(i) && !T.BASEMAPS.has(i) && !T.SOCCERMAPS.has(i) && !T.DARK_MAPS.has(i)) { id = i; break; }
  T.goMenu(); T.beginFromMenu(); T.loadMap(id); T.resetEntities(); T.state = 'play';
  const [a, b] = T.tanksNow; a.inv = b.inv = 0; a.reveal = b.reveal = 0; T.bots.clear && T.bots.clear();
  // an open run of cells along a row for the slide
  for (let r = 1; r < T.ROWS - 1; r++) for (let c = 1; c < T.COLS - 4; c++) {
    let ok = true; for (let k = 0; k < 4; k++) if (T.walls[r][c + k] || T.water[r * T.COLS + c + k] || T.grass[r * T.COLS + c + k]) ok = false;
    if (ok) { a.x = c + 0.5; a.y = r + 0.5; a.angle = 0; return id; } }
  return id; }"""
SLIDE = r"""() => { const T = __tank, a = T.tanksNow[0]; a.svx = 3; a.svy = 0; const x0 = a.x;
  for (let i = 0; i < 60; i++) T.stepPhysics(T.C.STEP, true, true);
  return a.x - x0; }"""

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    S = await page('solo')
    check(await ev(S, '__tank.settings().wxRules') is True, 'weather rules are on to start with')
    await ev(S, "__tank.setSettings(Object.assign({}, __tank.settings(), { wxRules: false }))")
    check(await ev(S, '__tank.settings().wxRules') is False, '...and can be switched off')

    # snow: a pushed tank with nothing pressed slides on; elsewhere, or with the rules off, it stops
    await ev(S, ON, ['snow', True]); snow = await ev(S, SLIDE)
    await ev(S, ON, ['snow', False]); off = await ev(S, SLIDE)
    await ev(S, ON, ['mist', True]); mist = await ev(S, SLIDE)
    check(snow > 0.3, f'on snow a tank slides on ({snow:.2f} cells)')
    check(off < 0.12 and mist < 0.12, f'with the rules off ({off:.2f}) or away from snow ({mist:.2f}) it stops')

    # rain: lightning shows a tank hidden in grass, but not a cloaked one; none with the rules off
    async def rain(rules):
      await ev(S, ON, ['rain', rules])
      return await ev(S, r"""() => { const T = __tank, [a, b] = T.tanksNow;
        let g = -1; for (let i = 0; i < T.COLS * T.ROWS; i++) if (T.grass[i] && !T.walls[(i / T.COLS) | 0][i % T.COLS]) { g = i; break; }
        b.x = g % T.COLS + 0.5; b.y = ((g / T.COLS) | 0) + 0.5; b.reveal = 0;
        a.x = b.x + 4 < T.COLS ? b.x + 4 : b.x - 4; a.y = b.y;
        const before = T.seenBy(0, b);
        T.boltT = 0.001; T.stepPhysics(T.C.STEP, true, false);
        const after = T.seenBy(0, b), flash = T.boltFlash;
        b.reveal = 0; b.cloak = 2; T.boltT = 0.001; T.stepPhysics(T.C.STEP, true, false);
        const cloaked = T.seenBy(0, b);
        b.cloak = 0; b.reveal = 0; T.boltT = 0.001; T.stepPhysics(T.C.STEP, true, false);
        return [before, after, cloaked, flash, T.boltT]; }""")
    before, after, cloaked, flash, nxt = await rain(True)
    check(before is False and after is True, f'lightning shows a tank hidden in grass ({before} -> {after})')
    check(cloaked is False, '...but not a cloaked one')
    check(flash > 0, '...with a flash on the screen')
    check(9 <= nxt <= 15, f'the next strike is 9 to 15 s off ({nxt:.1f})')
    before, after, *_ = await rain(False)
    check(after is False, 'with the rules off there is no lightning')

    # sand: a gust bends a shot (which keeps its speed) and pushes a tank standing still
    async def sand(rules):
      await ev(S, ON, ['sand', rules])
      return await ev(S, r"""() => { const T = __tank, [a, b] = T.tanksNow; b.x = 0.5; b.y = 0.5; b.alive = false;
        T.gust.next = 0.001; for (let i = 0; i < Math.round(0.7 / T.C.STEP); i++) T.stepPhysics(T.C.STEP, true, false);
        const k = T.gust.k; T.gust.x = 0; T.gust.y = 1; const gx = 0, gy = 1;
        // a shot along the open run, across the wind, and the tank's drift with it
        a.angle = 0; a.cool = 0; T.fire(a); const sh = T.bullets[T.bullets.length - 1], b0 = sh.bounces;
        const a0 = Math.atan2(sh.vy, sh.vx), s0 = Math.hypot(sh.vx, sh.vy), x0 = a.x, y0 = a.y;
        for (let i = 0; i < Math.round(0.3 / T.C.STEP); i++) T.stepPhysics(T.C.STEP, true, false);
        const live = T.bullets.includes(sh) && sh.bounces === b0, a1 = Math.atan2(sh.vy, sh.vx), s1 = Math.hypot(sh.vx, sh.vy);
        let turn = Math.abs(a1 - a0); if (turn > Math.PI) turn = 2 * Math.PI - turn;
        // the drift: the wind blowing along the open run, the tank back at its start
        a.x = x0; a.y = y0; T.gust.x = 1; T.gust.y = 0; T.gust.t = Math.max(T.gust.t, 2);
        for (let i = 0; i < Math.round(0.3 / T.C.STEP); i++) T.stepPhysics(T.C.STEP, true, false);
        return { k, turn, keep: Math.abs(s1 - s0) < 1e-6 * s0 + 1e-9, live, drift: (a.x - x0) * T.gust.x }; }""")
    g = await sand(True)
    check(g['k'] > 0.9, f"a gust gets up ({g['k']:.2f})")
    check(g['live'] and 0.05 < g['turn'] < 0.3 and g['keep'], f"it bends a shot ({g['turn']:.2f} rad in 0.3 s, no bounce: {g['live']}) that keeps its speed")
    check(g['drift'] > 0.08, f"and pushes a tank downwind ({g['drift']:.2f} cells)")
    g = await sand(False)
    check(g['k'] == 0 and g['turn'] < 1e-6, 'with the rules off no gust blows')

    # mist: a tank inside a fog bank is seen only close up, or just after it fires
    async def mist(rules):
      await ev(S, ON, ['mist', rules])
      return await ev(S, r"""() => { const T = __tank, [a, b] = T.tanksNow; const n = T.banks.length; if (!n) return [0];
        let spot = null;
        for (let r = 1; r < T.ROWS - 1 && !spot; r++) for (let c = 1; c < T.COLS - 1 && !spot; c++) {
          const i = r * T.COLS + c; if (T.walls[r][c] || T.grass[i] || T.water[i]) continue;
          for (const [dc, dr] of [[3, 0], [-3, 0], [0, 3], [0, -3]]) { const c2 = c + dc, r2 = r + dr, j = r2 * T.COLS + c2;
            if (c2 > 0 && r2 > 0 && c2 < T.COLS - 1 && r2 < T.ROWS - 1 && !T.walls[r2][c2] && !T.grass[j] && !T.water[j]) { spot = [c + 0.5, r + 0.5, c2 + 0.5, r2 + 0.5]; break; } } }
        b.x = spot[0]; b.y = spot[1]; b.reveal = 0; b.cloak = 0; a.x = spot[2]; a.y = spot[3];
        T.banks[0].x = b.x; T.banks[0].y = b.y; for (let i = 1; i < n; i++) { T.banks[i].x = -9; T.banks[i].y = -9; }
        const far = T.seenBy(0, b);
        b.reveal = 0.5; const fired = T.seenBy(0, b); b.reveal = 0;
        a.x = b.x + (spot[2] - b.x) / 3 * 1.2; a.y = b.y + (spot[3] - b.y) / 3 * 1.2; const near = T.seenBy(0, b);
        T.banks[0].x = -9; T.banks[0].y = -9; a.x = spot[2]; a.y = spot[3]; const out = T.seenBy(0, b);
        return [n, far, fired, near, out]; }""")
    n, *rest = await mist(True)
    check(n >= 2, f'a misty map has drifting fog banks ({n})')
    if n:
      far, fired, near, out = rest
      check(far is False and near is True, f'a tank inside one is hidden from 3 cells away ({far}) but seen close up ({near})')
      check(fired is True and out is True, f'...or just after it fires ({fired}); out of the fog it is seen ({out})')
    n, *_ = await mist(False)
    check(n == 0, 'with the rules off there are no fog banks')

    # online: the guest gets the setting, the slide and the flash
    H = await page('host'); G = await page('guest')
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'all', powerups:false, terrain:true, wxRules:true}))")
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(2500)
    check(await ev(G, '__tank.settings().wxRules') is True, 'the guest has the weather rules on too')
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {wxRules:false}))"); await H.wait_for_timeout(600)
    check(await ev(G, '__tank.settings().wxRules') is False, '...and off when the host switches them off')
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {wxRules:true}))"); await H.wait_for_timeout(600)
    got = None
    for _ in range(60):
      if await ev(H, "__tank.themeOf(__tank.mapId) === 'rain'"): got = await ev(H, '__tank.mapId'); break
      await ev(H, '__tank.startMatch()'); await H.wait_for_timeout(200)
    check(got is not None, f'a rainy map comes up online ({got})')
    if got is not None:
      await H.wait_for_timeout(4500)
      await ev(H, '__tank.boltT = 0.01'); await H.wait_for_timeout(250)
      check(await ev(G, '__tank.boltFlash') > 0, 'a strike on the host flashes on the guest')
    got = None
    for _ in range(80):
      if await ev(H, "__tank.themeOf(__tank.mapId) === 'mist'"): got = await ev(H, '__tank.mapId'); break
      await ev(H, '__tank.startMatch()'); await H.wait_for_timeout(200)
    if got is not None:
      await H.wait_for_timeout(4500)
      hb, gb = await ev(H, '__tank.banks.map(b => [b.x, b.y])'), await ev(G, '__tank.banks.map(b => [b.x, b.y])')
      check(len(hb) >= 2 and len(gb) == len(hb) and max(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(hb, gb)) < 0.5, f'the guest sees the fog banks where the host has them ({len(gb)} of {len(hb)})')
    got = None
    for _ in range(80):
      if await ev(H, "__tank.themeOf(__tank.mapId) === 'sand'"): got = await ev(H, '__tank.mapId'); break
      await ev(H, '__tank.startMatch()'); await H.wait_for_timeout(200)
    if got is not None:
      await H.wait_for_timeout(4500)
      await ev(H, '__tank.gust.next = 0.01'); await H.wait_for_timeout(900)
      hk, gk = await ev(H, '__tank.gust.k'), await ev(G, '__tank.gust.k')
      check(hk > 0.5 and gk > 0.3, f'a gust on the host blows on the guest too ({hk:.2f}, {gk:.2f})')

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
