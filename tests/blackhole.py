# Black Hole: for 2 s it swallows what is fired at it (shots, missiles, hooks, firebombs, rails and lasers, flame, nova)
# and lets the last of it loose as its own.   python3 tests/blackhole.py http://127.0.0.1:8790/
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
    held = lambda: ev(P, '(() => { const h = __tank.tanksNow[0].held; return h ? [h.kind, h.n] : null; })()')
    check(await ev(P, "__tank.SKINS.some(s => s.id === 'blackhole')"), 'Black Hole is a hero')
    async def setup(other='classic', gap=5):
      r = await ev(P, LOCAL, ['blackhole', other, gap]); await ev(P, STEP, 2); await ev(P, '__tank.bullets.length = 0'); return r
    shot = lambda dx, vy=0: ev(P, f"(() => {{ const T = __tank, t = T.tanksNow[0]; T.bullets.push({{ id: 9e6 + Math.random(), x: t.x + {dx}, y: t.y + {vy}, vx: -6.5, vy: 0, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }}); }})()")

    await setup()
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True and await T0('absorb') > 1.9, 'the skill opens the hole for 2 s')
    for dx in (1.6, 2.4, 3.2): await shot(dx)
    await ev(P, STEP, 70)
    check(await T0('alive') and await held() == ['shots', 3], f'three shots fired at it are swallowed, it lives ({await held()})')
    await ev(P, STEP, int(1.6 * SEC))
    check(await T0('absorb') == 0, 'the hole closes after 2 s')
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True and await held() is None, 'what it holds goes with the next press, cooldown or not')
    own = await ev(P, '__tank.bullets.filter(b => b.owner === 0).length')
    check(own == 3, f'...as a fan of the three shots, its own ({own})')
    await setup(); await shot(1.2); await ev(P, STEP, 40)
    check(not await T0('alive'), 'with no hole open a shot kills it')

    # a rail
    await setup('railgun'); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    await ev(P, '(() => { const T = __tank, o = T.tanksNow[1]; o.angle = Math.PI; T.fire(o); })()'); await ev(P, STEP, int(1.2 * SEC))
    check(await T0('alive') and (await held())[0] == 'rail', f'a rail ends in the hole ({await held()})')
    await ev(P, '(() => { const T = __tank, [a, o] = T.tanksNow; o.shield = 2; a.absorb = 0; T.useSkill(a); })()')
    check(not await T1('alive'), '...and let loose it goes through the shield of the one who fired it')
    # a hook
    await setup('hook', 4); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    x0 = await T0('x')
    await ev(P, '(() => { const T = __tank, o = T.tanksNow[1]; o.angle = Math.PI; T.useSkill(o); })()'); await ev(P, STEP, int(0.6 * SEC))
    check(abs(await T0('x') - x0) < 0.05 and (await held())[0] == 'hook', 'a hook is swallowed, it is not pulled')
    # nova
    await setup('frost', 2); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    await ev(P, '__tank.useSkill(__tank.tanksNow[1])')
    check(not await T0('frozen') and (await held())[0] == 'nova', 'a frost nova is swallowed, it is not frozen')
    await ev(P, STEP, int(2.1 * SEC)); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    check(await T1('frozen') > 1.5, '...let loose, it freezes the Frost')
    # flame
    await setup('burner', 1); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    await ev(P, '(() => { const T = __tank, o = T.tanksNow[1]; o.angle = Math.PI; T.fire(o); })()'); await ev(P, STEP, int(0.6 * SEC))
    check(await T0('alive') and (await held())[0] == 'flame', 'it drinks a flame and does not burn')
    # firebomb
    await setup('burner', 4); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    await ev(P, '(() => { const T = __tank, o = T.tanksNow[1]; o.angle = Math.PI; T.useSkill(o); })()'); await ev(P, STEP, int(0.8 * SEC))
    check(await ev(P, '__tank.pools.length') == 0 and (await held())[0] == 'firebomb', 'a firebomb is swallowed before it bursts')
    # missile
    await setup('classic', 3); await ev(P, '__tank.useSkill(__tank.tanksNow[0])')   # (a homing missile is slow: close by, so it arrives while the hole is open)
    await ev(P, "(() => { const T = __tank, o = T.tanksNow[1]; o.power = 'homing'; o.cool = 0; o.angle = Math.PI; T.fire(o); })()"); await ev(P, STEP, int(1.2 * SEC))
    check(await T0('alive') and (await held() or [''])[0] == 'missile', f'a homing missile is swallowed ({await held()})')

    # online
    H = await page('host'); G = await page('guest')
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    await ev(G, "(async () => { for (let i = 0; i < 100 && __tank.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    await ev(H, "(() => { const T = __tank, a = T.tanksNow[0]; a.skin = 'blackhole'; T.skins[0] = 'blackhole'; a.scool = 0; T.useSkill(a); a.held = { kind: 'rail', n: 0 }; })()")
    await H.wait_for_timeout(300)
    g = await ev(G, '(() => { const t = __tank.tanksNow[0]; return [t.absorb, t.held && t.held.kind]; })()')
    check(g == [1, 'rail'], f'the guest sees the hole open and what it holds ({g})')

    B = await page('bots')
    await ev(B, """(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { cpu: 3, game: 'dm', winScore: 7, powerups: true }));
      T.setMySkin('classic'); ['blackhole', 'blackhole', 'railgun'].forEach((s, i) => T.setCpuSkin(i, s)); T.goMenu(); T.beginFromMenu(); })()""")
    await B.wait_for_timeout(15000)
    check(True, f"computer Black Holes play for 15 s (scores {await ev(B, '__tank.scores')})")
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
