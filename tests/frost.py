# Frost: ice shards that break into slippery ice on walls; a nova that freezes enemies close by.
#   python3 tests/frost.py http://127.0.0.1:8790/
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
    check(await ev(P, "__tank.SKINS.some(s => s.id === 'frost')"), 'Frost is a hero')
    async def setup(gap=0):
      r = await ev(P, LOCAL, ['frost', 'classic', gap]); await ev(P, STEP, 2); await ev(P, '__tank.bullets.length = 0'); return r
    # the shard: no bounce; ice where it breaks
    await setup()
    await ev(P, "(() => { const [t, o] = __tank.tanksNow; o.inv = 99; t.angle = Math.PI; __tank.fire(t); t.inv = 99; })()")   # (both tanks spawn-safe, so the shard flies on to the far wall)       # straight at the wall behind it
    b = await ev(P, '__tank.bullets.filter(b => b.owner === 0).map(b => b.shard)')
    check(b == [True], f'it fires an ice shard ({b})')
    await ev(P, STEP, 30)
    n, bo = await ev(P, '[__tank.bullets.filter(b => b.owner === 0).length, __tank.bullets.filter(b => b.owner === 0).map(b => b.bounces)[0]]')
    check(n == 1 and bo == 1, f'the shard bounces once ({n} shots, {bo} bounces)')
    for _ in range(60):
      await ev(P, STEP, 10)
      if await ev(P, '__tank.bullets.filter(b => b.owner === 0).length') == 0: break
    n, f = await ev(P, '[__tank.bullets.filter(b => b.owner === 0).length, __tank.frost.length]')
    check(n == 0 and f == 1, f'at the next wall it breaks, leaving ice ({n} shots, {f} ice)')
    on = await ev(P, '(() => { const T = __tank, f = T.frost[0]; return [T.slipAt(1, f.x, f.y), T.slipAt(0, f.x, f.y)]; })()')
    check(on == [True, False], f'that ice makes the enemy slide, not the Frost ({on})')
    sp = await ev(P, '(() => { const T = __tank, f = T.frost[0], t = T.tanksNow[0], x = t.x, y = t.y, a = T.driveSpeed(t); t.x = f.x; t.y = f.y; const b = T.driveSpeed(t); t.x = x; t.y = y; return b / a; })()')
    check(abs(sp - 1.25) < 0.01, f'on ice the Frost skates 25% faster ({sp:.2f}x)')
    await ev(P, STEP, int(4.1 * SEC))
    check(await ev(P, '__tank.frost.length') == 0, 'the ice melts after 4 s')
    # the nova
    await setup()
    await ev(P, '(() => { const [a, b] = __tank.tanksNow; b.x = a.x + 2.7; b.y = a.y; })()')
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True, 'the skill goes off')
    check(await T1('frozen') > 1.9 and await T1('stun') > 1.9, 'an enemy 2.7 cells away is frozen solid for 2 s')
    check(await ev(P, '__tank.frost.length') == 1, 'ice spreads round the Frost')
    x1 = await T1('x'); await ev(P, '(() => { const t = __tank.tanksNow[1]; t.fireQ = 0.2; })()'); await ev(P, STEP, 30)
    check(abs(await T1('x') - x1) < 0.01 and await ev(P, '__tank.bullets.filter(b => b.owner === 1).length') == 0, 'frozen, it cannot drive or fire')
    await ev(P, STEP, int(1.9 * SEC))
    check(await T1('frozen') == 0 and await T1('alive'), 'it thaws after 2 s')
    await setup(); await ev(P, '(() => { const [a, b] = __tank.tanksNow; b.x = a.x + 3.6; b.y = a.y; })()')
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    check(not await T1('frozen'), 'one 3.6 cells away is not frozen')
    run = await setup(); await ev(P, '(() => { const [a, b] = __tank.tanksNow; b.x = a.x + 2; b.y = a.y; })()')
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 1] = 1')
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    check(not await T1('frozen'), 'a wall between shelters it')
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 1] = 0')
    await setup(); await ev(P, '(() => { const [a, b] = __tank.tanksNow; b.x = a.x + 1.5; b.y = a.y; b.shield = 1; })()')
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    check(not await T1('frozen') and await T1('shield') == 0, 'a shield takes the freeze instead')
    # frozen: one hit shatters it
    await setup(6); await ev(P, '(() => { const [a, b] = __tank.tanksNow; b.x = a.x + 1.8; b.y = a.y; })()')
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])'); await ev(P, '(() => { const t = __tank.tanksNow[0]; t.cool = 0; __tank.fire(t); })()')
    await ev(P, STEP, 40)
    check(not await T1('alive'), 'a frozen tank hit by a shot shatters')

    # online
    H = await page('host'); G = await page('guest')
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    await ev(G, "(async () => { for (let i = 0; i < 100 && __tank.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    await ev(H, "(() => { const T = __tank, [a, b] = T.tanksNow; a.skin = 'frost'; T.skins[0] = 'frost'; a.scool = 0; b.x = a.x + 1.2; b.y = a.y; b.inv = 0; b.invuln = 0; T.useSkill(a); })()")
    await H.wait_for_timeout(300)
    check(await ev(G, '__tank.tanksNow[1].frozen') > 0 and await ev(G, '__tank.frost.length') >= 1, 'the guest sees itself frozen and the ice')

    B = await page('bots')
    await ev(B, """(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { cpu: 3, game: 'dm', winScore: 7, powerups: true }));
      T.setMySkin('classic'); ['frost', 'frost', 'burner'].forEach((s, i) => T.setCpuSkin(i, s)); T.goMenu(); T.beginFromMenu(); })()""")
    await B.wait_for_timeout(15000)
    check(True, f"computer Frosts play for 15 s (scores {await ev(B, '__tank.scores')})")
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
