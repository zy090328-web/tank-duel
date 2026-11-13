# Deflectors, portals and explosive barrels. Needs the server on port 8790 (TEST_HOOKS=1).
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
SHOTS = '/tmp/terr/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# a local match on a chosen map, every other tank out of the way
START = """([o, map]) => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { ammo: 'unlimited', powerups: false, terrain: false, soft: false, mut: 'off', winScore: 5, cpu: 1 }, o));
  T.beginFromMenu(); T.mapOrder.length = 0; T.mapOrder.push(map); T.startRound();
  for (let i = 0; i < 120 * 2.05; i++) T.update(1 / 120); T.tanksNow.forEach(t => { t.inv = 0; }); return [T.state, T.mapId]; }"""
# the first cell of a kind, as [row, col]
FIND = "(k) => { const T = __tank; for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (T.mirror[r * T.COLS + c] === k) return [r, c]; return null; }"

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    L = await page('local', 820, 1180)

    # ---------- which maps have them ----------
    info = await ev(L, "(() => { const T = __tank; return [[...T.GADGET_MAPS], Object.keys(T.GADGETS).map(Number)]; })()")
    check(len(info[0]) == 4 and len(info[1]) >= 5, f'four maps built round gadgets, gadgets added to older maps {info}')
    await ev(L, START, [{'game': 'dm', 'terrain': False}, 8])
    off = await ev(L, "[__tank.portals.length, __tank.barrels.length]")
    await ev(L, START, [{'game': 'dm', 'terrain': True}, 8])
    on = await ev(L, "[__tank.portals.length, __tank.barrels.length]")
    await ev(L, START, [{'game': 'dm', 'terrain': False}, 20])
    own = await ev(L, "__tank.portals.length")
    check(off == [0, 0] and on == [4, 1] and own == 4, f'older maps get them with terrain on; their own maps always have them {off} {on} {own}')

    # ---------- deflectors ----------
    await ev(L, START, [{'game': 'dm'}, 19])
    for k, want in [(1, 'up'), (2, 'down')]:
      cell = await ev(L, FIND, k)
      r = await ev(L, """([r, c, k]) => { const T = __tank; T.bullets.length = 0; T.tanksNow.forEach(t => { t.x = 0.5; t.y = 0.5; t.inv = 99; });
        // a shot coming in from the left along the row, or from the right if the left is a wall
        const fromLeft = c > 0 && !T.walls[r][c - 1] && !T.mirror[r * T.COLS + c - 1];
        const x = fromLeft ? c - 0.3 : c + 1.3, vx = fromLeft ? 4 : -4;
        T.bullets.push({ id: 9999, x, y: r + 0.5, vx, vy: 0, owner: 0, age: 1, bounces: 0, trail: [], tick: 0, life: 9 });
        for (let i = 0; i < 40; i++) T.stepPhysics(1 / 120, false, true);
        const b = T.bullets.find(b => b.id === 9999); return b ? [fromLeft, Math.round(b.vx), Math.round(b.vy), b.bounces] : null; }""", [cell[0], cell[1], k])
      # '/' coming from the left turns up (vy < 0); from the right turns down. '\\' the other way round.
      exp_vy = (-4 if r[0] else 4) if k == 1 else (4 if r[0] else -4)
      check(r and r[1] == 0 and r[2] == exp_vy and r[3] == 1, f"a shot meeting a {'/' if k == 1 else chr(92)} deflector turns 90 degrees {r}")
    cell = await ev(L, FIND, 1)
    r = await ev(L, """([r, c]) => { const T = __tank; const p = T.tracePath(c - 0.5 > 0 ? c - 0.5 : c + 1.5, r + 0.5, c - 0.5 > 0 ? 0 : Math.PI);
      const turn = p[1]; return [Math.abs(turn.x - (c + 0.5)) < 0.05 && Math.abs(turn.y - (r + 0.5)) < 0.05, p.length >= 3, Math.abs(p[2].x - turn.x) < 0.01]; }""", cell)
    check(r == [True, True, True], f'a laser turns on the deflector line, then runs straight up or down {r}')
    r = await ev(L, """([r, c]) => { const T = __tank, o = { x: c + 0.5, y: r + 0.5 }; return [T.circleHitsWall(c + 0.5, r + 0.5, 0.33, true), T.distField(0, 0)[r * T.COLS + c]]; }""", cell)
    check(r == [True, -1], f'tanks cannot drive into a deflector cell {r}')

    # ---------- portals ----------
    await ev(L, START, [{'game': 'dm'}, 20])
    r = await ev(L, """(() => { const T = __tank, p = T.portals[0], q = T.portals[p.to], t = T.tanksNow[0]; T.tanksNow[1].x = 0.5; T.tanksNow[1].y = 0.5;
      t.x = p.x - 0.4; t.y = p.y; t.angle = 0; t.portLock = -1;
      for (let i = 0; i < 30; i++) { t.x += 0.02; T.stepPhysics(1 / 120, true, false); if (Math.hypot(t.x - q.x, t.y - q.y) < 0.6) break; }
      const there = Math.hypot(t.x - q.x, t.y - q.y) < 0.6;
      for (let i = 0; i < 60; i++) T.stepPhysics(1 / 120, true, false);     // standing on the far portal does not send it back
      return [there, Math.hypot(t.x - q.x, t.y - q.y) < 0.6]; })()""")
    check(r == [True, True], f'a tank driving onto a portal comes out of its partner, and stays {r}')
    r = await ev(L, """(() => { const T = __tank, p = T.portals[0], q = T.portals[p.to]; T.tanksNow.forEach(t => { t.x = 0.5; t.y = 0.5; t.inv = 99; }); T.bullets.length = 0;
      T.bullets.push({ id: 7777, x: p.x - 0.6, y: p.y, vx: 4, vy: 0, owner: 0, age: 1, bounces: 0, trail: [1, 1, 2, 2], tick: 0, life: 9 });
      for (let i = 0; i < 25; i++) T.stepPhysics(1 / 120, false, true);
      const b = T.bullets.find(b => b.id === 7777); if (!b) return null; let jump = false; for (let i = 2; i < b.trail.length; i += 2) if (Math.hypot(b.trail[i] - b.trail[i - 2], b.trail[i + 1] - b.trail[i - 1]) > 1.5) jump = true;
      return [Math.hypot(b.x - q.x, b.y - q.y) < 0.8, b.vx > 0, !jump]; })()""")
    check(r == [True, True, True], f'a shot goes through a portal and keeps going the same way {r}')
    await L.screenshot(path=SHOTS + 'gd_portal.png')

    # ---------- barrels ----------
    await ev(L, START, [{'game': 'classic', 'cpu': 2, 'soft': True}, 21])
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow, bs = T.barrels;
      // two barrels next to each other: a shot at one sets off the other too
      const a = bs[2], b = { x: a.x, y: a.y - 1, alive: true, fuse: -1, by: -1, back: 0 }; bs.push(b);     // a second barrel right beside it
      const victim = tk[1]; victim.x = a.x + 0.9; victim.y = a.y; victim.inv = 0; victim.shield = 0;
      const shooter = tk[0]; shooter.x = 0.5; shooter.y = 0.5; shooter.inv = 99;
      tk[2].x = T.COLS - 0.5; tk[2].y = 0.5; tk[2].inv = 99;
      T.bullets.length = 0;
      T.bullets.push({ id: 5555, x: a.x - 0.8, y: a.y, vx: 5, vy: 0, owner: 0, age: 1, bounces: 0, trail: [], tick: 0, life: 9 });
      for (let i = 0; i < 120; i++) T.stepPhysics(1 / 120, true, true);
      return [a.alive, b ? b.alive : null, victim.alive, T.stats[0].k]; })()""")
    check(r[0] is False and r[2] is False and r[3] == 1, f'a shot sets a barrel off: the tank beside it is out, the kill is the shooter\'s {r}')
    check(r[1] is False, f'a barrel caught in the blast goes off too {r}')
    r = await ev(L, """(() => { const T = __tank, br = T.barrels.find(b => b.alive), t = T.tanksNow[0]; t.x = br.x - 1; t.y = br.y; for (let i = 0; i < 60; i++) { t.x += 0.03; T.stepPhysics(1 / 120, false, false); }
      return Math.hypot(t.x - br.x, t.y - br.y) >= T.C.TANK_R + T.C.BARREL_R - 0.01; })()""")
    check(r, 'tanks cannot drive through a barrel')
    await L.screenshot(path=SHOTS + 'gd_barrel.png')
    # in deathmatch a new barrel stands there after a while; in classic they come back next round
    await ev(L, START, [{'game': 'dm', 'cpu': 1}, 21])
    r = await ev(L, """(() => { const T = __tank, br = T.barrels[0]; T.tanksNow.forEach(t => { t.x = 6.5; t.y = 6.5; t.inv = 99; }); T.lightBarrel(br, -1, 0);
      for (let i = 0; i < 10; i++) T.update(1 / 120); const gone = !br.alive; for (let i = 0; i < 120 * 21; i++) { T.update(1 / 120); T.tanksNow.forEach(t => { t.inv = 99; }); } return [gone, br.alive]; })()""")
    check(r == [True, True], f'deathmatch: a barrel comes back {r}')
    # computer tanks set barrels off next to their enemies
    r = await ev(L, """(() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'dm', cpu: 3, terrain: false })); T.beginFromMenu(); T.mapOrder.length = 0; T.mapOrder.push(21); T.startRound(); T.bots.add(0);
      let n = 0; const was = T.barrels.map(b => b.alive);
      for (let i = 0; i < 120 * 90; i++) { T.update(1 / 120); T.barrels.forEach((b, k) => { if (was[k] && !b.alive && b.by >= 0) n++; was[k] = b.alive; }); }
      return n; })()""")
    check(r >= 1, f'computer tanks set barrels off ({r} in 90 s)')

    # ---------- a replay shows a barrel kill ----------
    await ev(L, START, [{'game': 'classic', 'cpu': 1}, 21])
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow, a = T.barrels[0]; const v = tk[1]; v.x = a.x + 0.9; v.y = a.y; v.inv = 0; v.shield = 0; tk[0].x = 6.5; tk[0].y = 6.5; tk[0].inv = 99;
      T.lightBarrel(a, 0, 0.05); const seen = []; for (let i = 0; i < 120 * 3; i++) { T.update(1 / 120); if (seen[seen.length - 1] !== T.state) seen.push(T.state); } return seen; })()""")
    check('replay' in r, f'a barrel kill gets its replay {r}')
    await L.close()

    # ---------- online: the guest sees barrels go and tanks warp ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 5, game: 'dm', soft: false, terrain: false, mut: 'off' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(300)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, "(() => { const T = __tank; T.net.hostStart(); T.mapOrder.length = 0; T.mapOrder.push(22); T.startRound(); })()")
    await G.wait_for_timeout(3500)
    g0 = await ev(G, "[__tank.mapId, __tank.portals.length, __tank.barrels.length, [...__tank.mirror].filter(Boolean).length]")
    check(g0 == [22, 2, 2, 8], f'guest has the same gadgets {g0}')
    await ev(H, "(() => { const T = __tank; T.tanksNow.forEach(t => { t.inv = 99; }); T.lightBarrel(T.barrels[0], 0, 0); })()")
    await G.wait_for_timeout(800)
    gb = await ev(G, "__tank.barrels.map(b => b.alive)")
    check(gb[0] is False, f'guest sees the barrel gone {gb}')
    # the guest drives its tank onto a portal (the host moves it there)
    await ev(H, "(() => { const T = __tank, s = 1, t = T.tanksNow[s], p = T.portals[0]; t.x = p.x - 0.35; t.y = p.y; t.portLock = -1; })()")
    await G.wait_for_timeout(1200)
    r = await ev(H, "(() => { const T = __tank, t = T.tanksNow[1], q = T.portals[T.portals[0].to], p = T.portals[0]; return [Math.hypot(t.x - q.x, t.y - q.y) < 1.2, Math.hypot(t.x - p.x, t.y - p.y) < 1.2]; })()")
    gr = await ev(G, "(() => { const T = __tank, t = T.tanksNow[T.net.mySeat]; return [t.x, t.y]; })()")
    hr = await ev(H, "[__tank.tanksNow[1].x, __tank.tanksNow[1].y]")
    check((r[0] or r[1]) and abs(gr[0] - hr[0]) < 1.2 and abs(gr[1] - hr[1]) < 1.2, f'guest\'s tank follows the host through the portal {r} host {hr} guest {gr}')
    await G.screenshot(path=SHOTS + 'gd_guest.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
