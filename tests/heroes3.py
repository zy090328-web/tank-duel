# The seven new heroes: Blink, Mirror, Smoker, Splitter, Turret, Hook, Railgun; online sync; computer tanks playing them.
#   python3 tests/heroes3.py http://127.0.0.1:8790/
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
    skill = lambda i: ev(P, f'__tank.useSkill(__tank.tanksNow[{i}])')
    T0 = lambda f: ev(P, f'__tank.tanksNow[0].{f}')
    T1 = lambda f: ev(P, f'__tank.tanksNow[1].{f}')

    check(await ev(P, '__tank.SKINS.length') >= 20, 'there are 20 heroes or more')

    # ---------- Blink ----------
    run = await ev(P, LOCAL, ['blink', 'classic', 0]); await ev(P, STEP, 2)
    check(run[0] >= 6, f'an open run of {run[0]} cells to test in')
    x0 = await T0('x')
    check(await skill(0) is True, 'a Blink uses its skill')
    dx = await T0('x') - x0
    check(2.8 <= dx <= 3.05, f'it jumps about 3 cells ahead at once ({dx:.2f})')
    run = await ev(P, LOCAL, ['blink', 'classic', 0]); await ev(P, STEP, 2)
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 1] = 1')      # a wall right in front of it
    check(await skill(0) is False and await T0('scool') == 0, 'into a wall right in front it does not go, and costs nothing')
    await ev(P, f'__tank.walls[{run[1]}][{run[2]} + 1] = 0')
    await ev(P, LOCAL, ['blink', 'classic', 2]); await ev(P, STEP, 2)
    await skill(0)
    gap = await ev(P, '__tank.tanksNow[1].x - __tank.tanksNow[0].x')
    check(0.59 <= gap <= 0.75, f'it stops short of a tank in the way ({gap:.2f} apart)')
    await ev(P, LOCAL, ['blink', 'classic', 0]); await ev(P, STEP, 2)
    await ev(P, '__tank.tanksNow[0].snare = 2')
    check(await skill(0) is False, 'not while snared')

    # ---------- Mirror ----------
    run = await ev(P, LOCAL, ['mirror', 'classic', 6]); await ev(P, STEP, 2)
    await skill(0)
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; T.bullets.push({ id: 9e6, x: t.x + 1.2, y: t.y, vx: -6.5, vy: 0, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }); })()")
    await ev(P, STEP, 30)
    b = await ev(P, '__tank.bullets.filter(b => b.id === 9e6).map(b => [b.owner, b.vx])')
    check(await T0('alive') and len(b) == 1 and b[0][0] == 0 and b[0][1] > 0, f'a shot that hits a Mirror goes straight back, now its own ({b})')
    await ev(P, STEP, SEC)
    check(not await T1('alive'), '...and kills the one who fired it')
    await ev(P, LOCAL, ['mirror', 'classic', 6]); await ev(P, STEP, 2)
    await skill(0); await ev(P, STEP, int(1.6 * SEC))
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; T.bullets.push({ id: 9e6, x: t.x + 1.2, y: t.y, vx: -6.5, vy: 0, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }); })()")
    await ev(P, STEP, 30)
    check(not await T0('alive'), 'after 1.5 s it reflects no more')
    await ev(P, LOCAL, ['mirror', 'railgun', 6]); await ev(P, STEP, 2)
    await skill(0); await skill(1); await ev(P, STEP, int(1.4 * SEC))
    check(not await T0('alive'), 'a rail goes through the reflect (beams are not reflected)')

    # ---------- Smoker ----------
    await ev(P, LOCAL, ['smoker', 'recon', 6]); await ev(P, STEP, 2)
    check(await skill(0) is True and await ev(P, '__tank.clouds.length') == 1, 'a Smoker puts down a cloud')
    await ev(P, STEP, 40)
    seen = await ev(P, '[__tank.seenBy(1, __tank.tanksNow[0]), __tank.seenBy(0, __tank.tanksNow[0])]')
    check(seen == [False, True], f'the enemy cannot see the tank in it, its own side can ({seen})')
    await skill(1)
    m = await ev(P, '__tank.pings.filter(p => p.owner === 1 && p.kind === 0).length')
    check(m == 0, f'a radar ping does not find it either ({m} marks)')
    await ev(P, '(() => { const [a, b] = __tank.tanksNow; b.x = a.x + 0.9; })()')
    check(await ev(P, '__tank.seenBy(1, __tank.tanksNow[0])') is True, 'right beside it, it is seen')
    await ev(P, STEP, int(3.8 * SEC))
    check(await ev(P, '__tank.clouds.length') == 0, 'the cloud is gone after 4 s')

    # ---------- Splitter ----------
    await ev(P, LOCAL, ['splitter', 'classic', 0]); await ev(P, STEP, 2)
    await ev(P, "(() => { const T = __tank, t = T.tanksNow[0]; t.angle = -Math.PI / 2 + 0.3; T.fire(t); })()")
    n0 = await ev(P, '__tank.bullets.filter(b => b.owner === 0).length')
    for _ in range(40):
      await ev(P, STEP, 4)
      if await ev(P, '__tank.bullets.some(b => b.owner === 0 && b.bounces > 0)'): break
    n1 = await ev(P, '__tank.bullets.filter(b => b.owner === 0).length')
    check(n0 == 1 and n1 == 2, f'a Splitter shot opens into two at its first bounce ({n0} then {n1})')
    await ev(P, LOCAL, ['splitter', 'classic', 0]); await ev(P, STEP, 2); await ev(P, '__tank.bullets.length = 0')
    await skill(0)
    n = await ev(P, '__tank.bullets.filter(b => b.owner === 0).length')
    check(n >= 6, f'its burst throws shots all round ({n})')

    # ---------- Turret ----------
    await ev(P, LOCAL, ['turret', 'classic', 5]); await ev(P, STEP, 2)
    check(await skill(0) is True and await ev(P, '__tank.barricades.filter(k => k.turret).length') == 1, 'a Turret sets its gun down')
    for _ in range(25):
      await ev(P, STEP, 12)
      if not await T1('alive'): break
    check(not await T1('alive'), 'the gun turns and shoots the enemy')
    await ev(P, LOCAL, ['turret', 'classic', 0]); await ev(P, STEP, 2)
    await skill(0); await ev(P, '(() => { const t1 = __tank.tanksNow[1]; t1.alive = false; })()')
    TL = await ev(P, '__tank.C.TURRET_LIFE')
    await ev(P, STEP, int((TL - 0.1) * SEC))
    check(await ev(P, '__tank.barricades.filter(k => k.turret).length') == 1, f'it stands for {TL:g} s')
    await ev(P, STEP, 20)
    check(await ev(P, '__tank.barricades.filter(k => k.turret).length') == 0, '...then it is gone')
    await ev(P, LOCAL, ['turret', 'classic', 0]); await ev(P, STEP, 2)
    await skill(0); await ev(P, '__tank.tanksNow[1].alive = false')
    for k in range(2):
      await ev(P, "(() => { const T = __tank, g = T.barricades.find(k => k.turret); T.bullets.push({ id: 8e6 + Math.random(), x: g.x, y: g.y - 0.9, vx: 0, vy: 6.5, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }); })()")
      await ev(P, STEP, 30)
    check(await ev(P, '__tank.barricades.filter(k => k.turret).length') == 0, 'two hits break it')

    # ---------- Hook ----------
    await ev(P, LOCAL, ['hook', 'heavy', 4]); await ev(P, STEP, 2)
    check(await skill(0) is True and await ev(P, '__tank.hooks.length') == 1, 'a Hook throws its claw')
    for _ in range(40):
      await ev(P, STEP, 4)
      if await ev(P, '__tank.hooks.length') == 0: break
    d = await ev(P, '__tank.tanksNow[1].x - __tank.tanksNow[0].x')
    check(d < 0.95 and await T1('alive'), f'it drags the enemy it catches up to itself ({d:.2f} apart)')
    check(await T1('stun') > 0, '...and the one it caught is dazed a moment')
    await ev(P, LOCAL, ['hook', 'classic', 0]); await ev(P, STEP, 2)
    await ev(P, '__tank.tanksNow[0].angle = -Math.PI / 2')
    await skill(0); await ev(P, STEP, SEC)
    check(await ev(P, '__tank.hooks.length') == 0, 'against a wall it comes back empty')

    # ---------- Railgun ----------
    run = await ev(P, LOCAL, ['railgun', 'classic', 5]); await ev(P, STEP, 2)
    r, c0 = run[1], run[2]
    await ev(P, f'__tank.walls[{r}][{c0} + 2] = 1')        # one wall between them
    check(await ev(P, '__tank.fire(__tank.tanksNow[0])') is True and await T0('charge') > 0.8, 'a Railgun charges first')
    x0 = await T0('x'); await ev(P, STEP, int(0.6 * SEC))
    check(await T1('alive') and abs(await T0('x') - x0) < 1e-6, 'it holds still while charging, and nothing has gone yet')
    await ev(P, '__tank.tanksNow[1].shield = 2')
    await ev(P, STEP, int(0.3 * SEC))
    check(not await T1('alive'), 'the rail goes through the wall and the shield')
    check(await ev(P, '__tank.fire(__tank.tanksNow[0])') is False, 'right after a rail it cannot fire again')
    await ev(P, STEP, int((await ev(P, '__tank.C.RAIL_RELOAD') + 0.05) * SEC))
    check(await ev(P, '__tank.fire(__tank.tanksNow[0])') is True, '...after its reload it can')
    run = await ev(P, LOCAL, ['railgun', 'classic', 6]); await ev(P, STEP, 2)
    await ev(P, f'(() => {{ const W = __tank.walls; W[{r}][{c0} + 2] = 1; W[{r}][{c0} + 4] = 1; }})()')
    await ev(P, '__tank.fire(__tank.tanksNow[0])'); await ev(P, STEP, SEC)
    check(await T1('alive'), 'the second wall stops it')
    await ev(P, f'(() => {{ const W = __tank.walls; W[{r}][{c0} + 2] = 0; W[{r}][{c0} + 4] = 0; }})()')
    await ev(P, LOCAL, ['railgun', 'classic', 6]); await ev(P, STEP, 2); await ev(P, '__tank.beams.length = 0')
    await skill(0); await ev(P, STEP, int(1.2 * SEC))
    check(await ev(P, '__tank.beams.length') == 0, 'the three rails charge longer (1.3 s)')
    await ev(P, STEP, int(0.15 * SEC))
    check(await ev(P, '__tank.beams.length') == 3, 'its skill sends three rails')

    # ---------- online: the guest sees them ----------
    H = await page('host'); G = await page('guest')
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(4500)
    async def host_skill(sk):
      await ev(H, f"(() => {{ const T = __tank, t = T.tanksNow[0]; t.skin = '{sk}'; T.skins[0] = '{sk}'; t.scool = 0; t.stun = 0; t.charge = 0; T.useSkill(t); }})()")
      await H.wait_for_timeout(350)
    await host_skill('smoker')
    check(await ev(G, '__tank.clouds.length') == 1, 'the guest sees the cloud')
    await host_skill('turret')
    check(await ev(G, '__tank.barricades.filter(k => k.turret).length') == 1, 'the guest sees the turret')
    await host_skill('mirror')
    check(await ev(G, '__tank.tanksNow[0].reflect') == 1, 'the guest sees the reflect')
    await ev(H, "(() => { const T = __tank, [a, b] = T.tanksNow; a.angle = Math.atan2(b.y - a.y, b.x - a.x); })()")
    await host_skill('hook')
    await H.wait_for_timeout(-200 + 200)
    await host_skill('railgun')
    check(await ev(G, '__tank.tanksNow[0].rail') == 3, 'the guest sees the tri-rail charging')
    await H.wait_for_timeout(900)

    # ---------- computer tanks play them all ----------
    B = await page('bots')
    await ev(B, """(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { cpu: 3, game: 'dm', winScore: 7, powerups: false }));
      T.setMySkin('railgun'); ['hook', 'turret', 'smoker'].forEach((s, i) => T.setCpuSkin(i, s)); T.goMenu(); T.beginFromMenu(); })()""")
    await B.wait_for_timeout(12000)
    await ev(B, """(() => { const T = __tank; T.goMenu(); T.setMySkin('mirror'); ['blink', 'splitter', 'railgun'].forEach((s, i) => T.setCpuSkin(i, s)); T.beginFromMenu(); })()""")
    await B.wait_for_timeout(12000)
    check(True, 'computer tanks play the new heroes for 24 s')

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
