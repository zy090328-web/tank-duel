# The Burner: a flamethrower (short reach, a moment in it burns you up, walls stop it) and a firebomb thrown over walls.
#   python3 tests/burner.py http://127.0.0.1:8790/
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# t0 at the left end of the longest open row, facing right; t1 `gap` cells to its right (or at the far end), facing left
LOCAL = r"""
([a, b, gap]) => { const T = __tank;
  T.setSettings(Object.assign({}, T.settings(), { cpu: 0, maps: 'classic', powerups: false, terrain: false, game: 'classic', soft: false, mut: '' }));
  T.setMySkin(a); T.setP2Skin(b); T.setupLocal(); T.startMatch(); T.state = 'play';
  const [t0, t1] = T.tanksNow, W = T.walls;
  const open = (c, r) => c > 0 && r > 0 && c < T.COLS - 1 && r < T.ROWS - 1 && !W[r][c];
  let best = null;
  for (let r = 1; r < T.ROWS - 1; r++) { let c0 = -1; for (let c = 0; c <= T.COLS; c++) { const o = c < T.COLS && open(c, r);
    if (o && c0 < 0) c0 = c; if (!o && c0 >= 0) { if (!best || c - c0 > best.n) best = { r, c0, n: c - c0 }; c0 = -1; } } }
  const n = gap ? Math.min(best.n - 1, gap) : best.n - 1;
  t0.x = best.c0 + 0.5; t0.y = best.r + 0.5; t0.angle = 0; t1.x = best.c0 + 0.5 + n; t1.y = best.r + 0.5; t1.angle = Math.PI;
  t0.inv = t1.inv = 0; t0.scool = t1.scool = 0; t0.shield = t1.shield = 0;
  return [best.n, best.r, best.c0];
}"""
STEP = "(n) => { const T = __tank; for (let i = 0; i < n; i++) T.stepPhysics(T.C.STEP, true, true); }"
SEC = 120

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    P = await page('local')
    T0 = lambda f: ev(P, f'__tank.tanksNow[0].{f}')
    T1 = lambda f: ev(P, f'__tank.tanksNow[1].{f}')
    fire = lambda: ev(P, '__tank.fire(__tank.tanksNow[0])')
    put = lambda d, a=0: ev(P, f'(() => {{ const [x, y] = __tank.tanksNow; y.x = x.x + Math.cos({a}) * {d}; y.y = x.y + Math.sin({a}) * {d}; y.heat = 0; }})()')
    hold = "(() => { const t = __tank.tanksNow[1]; t.stun = 99; })()"
    check(await ev(P, '__tank.SKINS.length') >= 22 and await ev(P, "__tank.SKINS.some(s => s.id === 'burner')"), 'the Burner is a hero')

    async def setup(gap=0):
      r = await ev(P, LOCAL, ['burner', 'classic', gap]); await ev(P, STEP, 2); await ev(P, hold); await ev(P, '__tank.bullets.length = 0'); return r
    run = await setup(); await put(1.5)
    check(await fire() is True and await ev(P, '__tank.bullets.length') == 0 and await T0('flame') > 0.6, 'fire is a flame: no bullet')
    await ev(P, STEP, int(0.2 * SEC))
    check(await T1('alive') and await T1('heat') > 0.1, 'a moment in the fire heats a tank up, it is not dead at once')
    await ev(P, STEP, int(0.2 * SEC))
    check(not await T1('alive'), '...a third of a second burns it up (1.5 cells in front)')
    await setup(); await put(2.6); await fire(); await ev(P, STEP, int(0.8 * SEC))
    check(await T1('alive'), 'one 2.6 cells away is out of reach')
    await setup(); await put(1.2, 3.14159); await fire(); await ev(P, STEP, int(0.8 * SEC))
    check(await T1('alive'), 'one behind it does not burn')
    await setup(); await put(1.5, 1.2); await fire(); await ev(P, STEP, int(0.8 * SEC))
    check(await T1('alive'), 'one well off to the side does not burn (the cone is narrow)')
    run = await setup(); await put(1.8)
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 1] = 1')
    await fire(); await ev(P, STEP, int(0.8 * SEC))
    check(await T1('alive'), 'a wall between stops the fire')
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 1] = 0')
    # a brush with the fire is not fatal: the heat goes away
    await setup(); await put(1.5); await fire(); await ev(P, STEP, int(0.2 * SEC))
    await put(4); await ev(P, '__tank.tanksNow[1].heat = 0.2'); await ev(P, STEP, int(0.6 * SEC))
    check(await T1('alive') and await T1('heat') < 0.01, 'out of the fire it cools down')
    # how long it goes, and the wait after
    await setup(); await put(4); await fire()
    await ev(P, STEP, int(0.72 * SEC))
    check(await T0('flame') == 0, 'the flame goes for 0.7 s')
    check(await fire() is False, 'no new flame straight away')
    await ev(P, STEP, int(0.47 * SEC))
    check(await fire() is True, '...0.45 s after it ends there can be')
    # firebomb
    run = await setup(); await put(4)
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 2] = 1')        # a wall in the way: it goes over
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True and await ev(P, '__tank.firebombs.length') == 1, 'the skill throws a firebomb')
    await ev(P, STEP, int(0.65 * SEC))
    pool = await ev(P, '__tank.pools.map(p => [p.x - __tank.tanksNow[0].x, p.y - __tank.tanksNow[0].y])')
    check(len(pool) == 1 and 3.6 < pool[0][0] < 4.05, f'it lands about 4 cells ahead, over the wall, as a pool of fire ({pool})')
    await ev(P, STEP, int(0.45 * SEC))
    check(not await T1('alive'), 'a tank standing in the pool burns up')
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 2] = 0')
    await ev(P, STEP, int(3.1 * SEC))
    check(await ev(P, '__tank.pools.length') == 0, 'the pool burns out after 3.5 s')
    await setup(); await ev(P, '__tank.useSkill(__tank.tanksNow[0])'); await ev(P, STEP, int(0.65 * SEC))
    await ev(P, '(() => { const T = __tank, p = T.pools[0], t = T.tanksNow[0]; t.x = p.x; t.y = p.y; })()'); await ev(P, STEP, int(0.6 * SEC))
    check(await T0('alive'), "its own fire does not burn it")

    # online: a guest sees the flame and the pool
    H = await page('host'); G = await page('guest')
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    await ev(G, "(async () => { for (let i = 0; i < 100 && __tank.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    await ev(H, "(() => { const T = __tank, t = T.tanksNow[0]; t.skin = 'burner'; T.skins[0] = 'burner'; t.cool = 0; T.fire(t); })()"); await H.wait_for_timeout(250)
    check(await ev(G, '__tank.tanksNow[0].flame') == 1 and await ev(G, '__tank.flames.length') > 5, 'the guest sees the flame')
    await ev(H, "(() => { const T = __tank, t = T.tanksNow[0]; t.scool = 0; T.useSkill(t); })()"); await H.wait_for_timeout(1000)
    check(await ev(G, '__tank.pools.length') == 1, 'the guest sees the pool of fire')

    B = await page('bots')
    await ev(B, """(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { cpu: 3, game: 'dm', winScore: 7, powerups: true }));
      T.setMySkin('classic'); ['burner', 'burner', 'blade'].forEach((s, i) => T.setCpuSkin(i, s)); T.goMenu(); T.beginFromMenu(); })()""")
    await B.wait_for_timeout(15000)
    check(True, f"computer Burners play for 15 s (scores {await ev(B, '__tank.scores')})")
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
