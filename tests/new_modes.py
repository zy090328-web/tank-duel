# Tank Soccer, Hot Potato and Gun Game. Needs the server on port 8790 (TEST_HOOKS=1).
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
SHOTS = '/tmp/terr/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

START = """(o) => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { ammo: 'unlimited', powerups: false, terrain: false, soft: false, mut: 'off', winScore: 5 }, o)); T.beginFromMenu();
  for (let i = 0; i < 120 * 2.05; i++) T.update(1 / 120); return T.state; }"""
STEP = "(n) => { for (let i = 0; i < n; i++) __tank.update(1 / 120); return __tank.state; }"

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    L = await page('local', 820, 1180)

    # ---------- the menu ----------
    await ev(L, "__tank.goMenu()"); await L.wait_for_timeout(300)
    geo = await ev(L, """(() => { const it = __tank.menuItems(), Lt = __tank.layout; const g = it.filter(i => i.kind === 'game' || i.kind === 'online' || i.kind === 'board');
      const ov = g.some((a, i) => g.some((b, j) => j > i && !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y)));
      return [g.length, ov, Math.min(...g.map(i => i.y)) >= Lt.AY, Math.max(...g.map(i => i.y + i.h)) <= Lt.AY + Lt.AH]; })()""")
    check(geo == [11, False, True, True], f'nine mode cards, Play online and Leaderboard fit in the arena without overlapping {geo}')
    await L.screenshot(path=SHOTS + 'nm_menu.png')

    # ---------- soccer ----------
    st = await ev(L, START, {'game': 'soccer', 'cpu': 0})
    info = await ev(L, "(() => { const T = __tank; return [T.SOCCERMAPS.has(T.mapId), [...T.goalCell].filter(v => v === 1).length, [...T.goalCell].filter(v => v === 2).length, !!T.ball, T.teamOf.join(',')]; })()")
    check(st == 'play' and info[0] and info[1] == 3 and info[2] == 3 and info[3] and info[4] == '0,1', f'soccer: a pitch with two goals and a ball, red against blue {info}')
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0], b = T.ball; t.x = b.x; t.y = b.y + 1.2; t.angle = -Math.PI / 2; t.cool = 0; T.fire(t);
      for (let i = 0; i < 40; i++) T.update(1 / 120); return [b.vy < -1, b.last]; })()""")
    check(r == [True, 0], f'a shot knocks the ball on {r}')
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[1], b = T.ball; b.vx = b.vy = 0; b.x = 5.5; b.y = 6.5; t.x = 3.5; t.y = 6.5; t.angle = 0; t.stun = 0;
      for (let i = 0; i < 120; i++) { t.x += 2.6 / 120; T.update(1 / 120); } return [b.x > 6, b.last]; })()""")
    check(r[0] and r[1] == 1, f'driving into the ball pushes it {r}')
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0]; t.inv = 0; t.shield = 0; T.hit(t, 1); const a = [t.alive, t.stun > 0]; t.stun = 0; T.hit(t, 1); return a.concat([t.stun > 0]); })()""")
    check(r == [True, True, False], f'shots only stun, and not again straight away {r}')
    # a goal: the ball rolled into the top goal (blue's) scores for red
    r = await ev(L, """(() => { const T = __tank, b = T.ball, c = T.goalCell.findIndex(v => v === 2); b.x = c % T.COLS + 0.5; b.y = 1.6; b.vx = 0; b.vy = -5; b.last = 0; b.touchT = T.rec.t - 1;
      const seen = []; for (let i = 0; i < 120 * 3; i++) { T.update(1 / 120); if (seen[seen.length - 1] !== T.state) seen.push(T.state); } return [seen, T.goalBy, T.replayText()]; })()""")
    check('ending' in r[0] and 'replay' in r[0] and r[1] == 0 and 'scores for Red' in r[2], f'a goal: replay, then the point {r}')
    await L.screenshot(path=SHOTS + 'nm_soccer_replay.png')
    await ev(L, STEP, 120 * 5)
    check(await ev(L, "__tank.scores.join(',')") == '1,0', 'red has the goal')
    tanks_out = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0], c = T.goalCell.findIndex(v => v === 1); t.x = c % T.COLS + 0.5; t.y = T.ROWS - 1 - T.C.TANK_R + 0.15; T.resolveCircle(t, T.C.TANK_R, true); return t.y <= T.ROWS - 1 - T.C.TANK_R + 0.001; })()""")
    check(tanks_out, 'tanks cannot drive into a goal')
    # computer tanks score
    r = await ev(L, """(() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'soccer', cpu: 3, winScore: 3 })); T.beginFromMenu(); T.bots.add(0);
      for (let i = 0; i < 120 * 400 && T.state !== 'matchEnd'; i++) T.update(1 / 120); return [T.state, T.scores.join(','), T.COLS]; })()""")
    check(r[0] == 'matchEnd' and r[2] == 15, f'four computer tanks play a match to the end on the big pitch {r}')
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'nm_soccer_end.png')
    await ev(L, START, {'game': 'soccer', 'cpu': 0})
    await ev(L, "(() => { const T = __tank; T.bots.add(0); T.bots.add(1); for (let i = 0; i < 120 * 6; i++) T.update(1 / 120); })()")
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'nm_soccer.png')

    # ---------- hot potato ----------
    st = await ev(L, START, {'game': 'potato', 'cpu': 2})
    r = await ev(L, """(() => { const T = __tank; const a = T.pot.holder; for (let i = 0; i < 120 * 2.1; i++) T.update(1 / 120); return [a, T.pot.holder, T.pot.fuse > 5]; })()""")
    check(r[0] == -1 and r[1] >= 0 and r[2], f'the bomb appears after a moment {r}')
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow, h = tk[T.pot.holder], o = tk.find(t => t !== h); T.pot.cd = 0;
      o.x = h.x + 0.5; o.y = h.y; T.stepPhysics(1 / 120, true, false); const first = T.pot.holder === o.id;
      T.pot.cd = 0; h.x = o.x + 0.5; h.y = o.y; T.stepPhysics(1 / 120, true, false); const back = T.pot.holder;
      return [first, back === o.id, o.id]; })()""")
    check(r[0] and r[1], f'touching passes the bomb, not straight back {r}')
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow, h = tk[T.pot.holder]; const o = tk.find(t => t !== h && t.alive); o.x = h.x + 1; o.y = h.y; o.stun = 0;
      T.pot.fuse = 0.01; for (let i = 0; i < 3; i++) T.update(1 / 120); return [h.alive, o.stun > 0, T.pot.holder, T.hl && T.hl.v === h.id]; })()""")
    check(r[0] is False and r[1] and r[2] == -1 and r[3], f'the bomb goes off: the carrier is out, the one beside it dizzy {r}')
    await L.wait_for_timeout(100)
    r = await ev(L, """(() => { const T = __tank; for (let i = 0; i < 120 * 2; i++) T.update(1 / 120); const tk = T.tanksNow, h = tk[T.pot.holder]; if (!h) return null;
      const o = tk.find(t => t !== h && t.alive); o.inv = 0; o.shield = 0; T.hit(o, h.id); return [o.alive, o.stun > 0]; })()""")
    check(r == [True, True], f'shots only stun in hot potato {r}')
    r = await ev(L, """(() => { const T = __tank; const seen = []; for (let i = 0; i < 120 * 40 && T.state !== 'result'; i++) { if (T.pot.holder >= 0) T.pot.fuse = Math.min(T.pot.fuse, 0.5); T.update(1 / 120); if (seen[seen.length - 1] !== T.state) seen.push(T.state); }
      return [T.state, T.tanksNow.filter(t => t.alive).length, T.winner, T.scores.join(','), seen]; })()""")
    check(r[0] == 'result' and r[1] == 1 and r[2] >= 0 and 'replay' in r[4], f'last one left wins the round, after a replay {r}')
    await ev(L, START, {'game': 'potato', 'cpu': 3})
    await ev(L, "(() => { const T = __tank; T.bots.add(0); for (let i = 0; i < 120 * 4; i++) T.update(1 / 120); })()")
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'nm_potato.png')

    # ---------- gun game ----------
    st = await ev(L, START, {'game': 'gun', 'cpu': 2, 'winScore': 5, 'powerups': True})
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0]; return [T.gunLadder().join(','), T.gunWeapon(0), t.power, T.target()]; })()""")
    check(r == ['shot,spread,pierce,bomb,laser', 'shot', None, 5], f'gun game starts everyone on the plain gun {r}')
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow, t = tk[0]; tk[1].inv = 0; tk[1].shield = 0; T.kill(tk[1], 0); T.update(1 / 120); T.update(1 / 120);
      const w = [T.scores[0], T.gunWeapon(0), t.power]; t.cool = 0; const n = T.bullets.length; T.fire(t); return w.concat([T.bullets.length - n, t.power, t.cool > 0.4]); })()""")
    check(r == [1, 'spread', 'spread', 3, None, True], f'a kill moves you to the next weapon, which fires as that weapon {r}')
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0]; T.tanksNow.forEach(o => { if (o !== t) o.alive = false; }); t.inv = 5; for (let i = 0; i < 120; i++) T.update(1 / 120); const back = t.power;
      t.inv = 0; t.shield = 0; T.kill(t, 0); return [back, T.scores[0]]; })()""")
    check(r == ['spread', 0], f'the weapon comes back after its pause; destroying yourself costs a weapon {r}')
    r = await ev(L, """(() => { const T = __tank; for (let i = 0; i < 120 * 30; i++) T.update(1 / 120); return T.pickups.length; })()""")
    check(r == 0, 'no pickups in gun game, even with power-ups on')
    r = await ev(L, """(() => { const T = __tank; T.bots.add(0); for (let i = 0; i < 120 * 300 && T.state !== 'matchEnd'; i++) T.update(1 / 120); return [T.state, Math.max(...T.scores)]; })()""")
    check(r == ['matchEnd', 5], f'the first to finish the five weapons wins {r}')
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'nm_gun_end.png')
    await ev(L, START, {'game': 'gun', 'cpu': 2, 'winScore': 7})
    await ev(L, "(() => { const T = __tank; T.scores[0] = 4; T.tanksNow[0].power = null; for (let i = 0; i < 120 * 1; i++) T.update(1 / 120); })()")
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'nm_gun.png')
    await L.close()

    # ---------- online: a guest sees the ball and the bomb ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 5, game: 'soccer', soft: false, terrain: false, mut: 'off' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(400)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()'); await G.wait_for_timeout(3500)
    await ev(H, "(() => { const b = __tank.ball; b.vx = 3; b.vy = 1; })()"); await G.wait_for_timeout(600)
    hb = await ev(H, "[__tank.ball.x, __tank.ball.y]"); gb = await ev(G, "__tank.ball && [__tank.ball.x, __tank.ball.y]")
    check(gb is not None and abs(hb[0] - gb[0]) < 1.2 and abs(hb[1] - gb[1]) < 1.2, f'the guest sees the ball where the host has it {hb} {gb}')
    await G.screenshot(path=SHOTS + 'nm_soccer_guest.png')
    await ev(H, "__tank.net.hostLobby()"); await H.wait_for_timeout(300)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 5, game: 'potato', soft: false, terrain: false, mut: 'off' })")
    await ev(H, '__tank.net.hostStart()'); await G.wait_for_timeout(5000)
    hh = await ev(H, "__tank.pot.holder"); gh = await ev(G, "__tank.pot.holder")
    check(hh >= 0 and hh == gh, f'the guest knows who has the bomb {hh} {gh}')
    await G.screenshot(path=SHOTS + 'nm_potato_guest.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
