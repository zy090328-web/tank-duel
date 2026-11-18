# Weather rules: on snow maps tanks slide, on rainy maps lightning shows every tank for a moment (a cloak still
# hides); a setting, on unless switched off, the same for everyone online.  python3 tests/wxrules.py http://127.0.0.1:8790/
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

    # online: the guest gets the setting, the slide and the flash
    H = await page('host'); G = await page('guest')
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'all', powerups:false, terrain:true, wxRules:true}))")
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(2500)
    check(await ev(G, '__tank.settings().wxRules') is True, 'the guest has the weather rules on too')
    got = None
    for _ in range(60):
      if await ev(H, "__tank.themeOf(__tank.mapId) === 'rain'"): got = await ev(H, '__tank.mapId'); break
      await ev(H, '__tank.startMatch()'); await H.wait_for_timeout(200)
    check(got is not None, f'a rainy map comes up online ({got})')
    if got is not None:
      await H.wait_for_timeout(4500)
      await ev(H, '__tank.boltT = 0.01'); await H.wait_for_timeout(250)
      check(await ev(G, '__tank.boltFlash') > 0, 'a strike on the host flashes on the guest')

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
