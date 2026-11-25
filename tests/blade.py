# The Blade: no gun, a slash in front that also cuts shots; its spin cuts all round.
#   python3 tests/blade.py http://127.0.0.1:8790/
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
    put = lambda d, a=0: ev(P, f'(() => {{ const [x, y] = __tank.tanksNow; y.x = x.x + Math.cos({a}) * {d}; y.y = x.y + Math.sin({a}) * {d}; }})()')
    check(await ev(P, '__tank.SKINS.length') >= 21 and await ev(P, "__tank.SKINS.some(s => s.id === 'blade')"), 'the Blade is the 21st hero')

    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await ev(P, '__tank.bullets.length = 0')
    await put(0.95)
    check(await fire() is True and await ev(P, '__tank.bullets.length') == 0, 'fire is a slash: no bullet')
    check(not await T1('alive'), 'it cuts an enemy right in front')
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(1.5)
    await fire(); check(await T1('alive'), 'one 1.5 cells away is out of reach')
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(0.9, 3.14159)
    await fire(); check(await T1('alive'), 'one behind it is not cut')
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2)
    await ev(P, '(() => { const T = __tank, [x, y] = T.tanksNow; y.x = x.x + Math.cos(0.8) * 0.9; y.y = x.y + Math.sin(0.8) * 0.9; T.fire(x); })()')   # (in one go: the running game would push it out of a wall)
    check(not await T1('alive'), 'one off to the front side is (the swing is wide)')
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(3)
    await fire(); check(await fire() is False, 'it swings again only after a moment')
    await ev(P, STEP, int(0.5 * SEC) + 2); check(await fire() is True, '...half a second later')
    # cutting a shot
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(4); await ev(P, '__tank.bullets.length = 0')
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; T.bullets.push({ id: 9e6, x: t.x + 0.95, y: t.y, vx: -6.5, vy: 0, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }); })()")
    await fire(); await ev(P, STEP, 20)
    check(not await T0('alive'), 'a plain slash does not stop a shot (only the spin does)')
    # armour: the first cut breaks it
    await ev(P, LOCAL, ['blade', 'heavy', 0]); await ev(P, STEP, 2); await put(0.95)
    await ev(P, '__tank.tanksNow[1].armor = 1')
    await fire(); check(await T1('alive') and await T1('armor') == 0, "a Heavy's armour takes the first cut")
    # spin
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(4)
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True and await T0('spin') > 1.0, 'the skill spins')
    check(await fire() is False, 'no slashing while spinning')
    await put(0.9, 3.14159 / 2); await ev(P, STEP, 2)
    check(not await T1('alive'), 'the spin cuts one beside it')
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; T.bullets.push({ id: 9e6, x: t.x + 2.2, y: t.y, vx: -6.5, vy: 0, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }); })()")
    await ev(P, STEP, 40)
    check(await T0('alive') and not await ev(P, '__tank.bullets.some(b => b.id === 9e6)'), 'the spin cuts a shot in two: it does not get through')
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(5)
    # pickups: a shield yes, a laser no
    await ev(P, LOCAL, ['blade', 'classic', 0]); await ev(P, STEP, 2); await put(5)
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; T.pickups.push({ x: t.x, y: t.y, type: 'laser', age: 0 }); })()"); await ev(P, STEP, 2)
    check(await T0('power') is None, 'it does not pick up a laser')
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; T.pickups.length = 0; T.pickups.push({ x: t.x, y: t.y, type: 'shield', age: 0 }); })()"); await ev(P, STEP, 2)
    check(await T0('power') == 'shield', 'it picks up a shield')

    # online: a guest sees the slash and the spin
    H = await page('host'); G = await page('guest')
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    await ev(G, "(async () => { for (let i = 0; i < 100 && __tank.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    await ev(H, "(() => { const T = __tank, t = T.tanksNow[0]; t.skin = 'blade'; T.skins[0] = 'blade'; t.cool = 0; T.fire(t); })()"); await H.wait_for_timeout(250)
    check(await ev(G, '!!__tank.tanksNow[0].slashAt'), 'the guest sees the slash')
    await ev(H, "(() => { const T = __tank, t = T.tanksNow[0]; t.scool = 0; T.useSkill(t); })()"); await H.wait_for_timeout(300)
    check(await ev(G, '__tank.tanksNow[0].spin') == 1, 'the guest sees the spin')

    # computer tanks with blades
    B = await page('bots')
    await ev(B, """(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { cpu: 3, game: 'dm', winScore: 7, powerups: true }));
      T.setMySkin('classic'); ['blade', 'blade', 'heavy'].forEach((s, i) => T.setCpuSkin(i, s)); T.goMenu(); T.beginFromMenu(); })()""")
    await B.wait_for_timeout(15000)
    k = await ev(B, '__tank.scores')
    check(True, f'computer Blades play for 15 s (scores {k})')
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
