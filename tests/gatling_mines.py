# The gatling on its spot, and hidden mines. Needs the server on port 8790 (TEST_HOOKS=1).
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
SHOTS = '/tmp/terr/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# a local match on a chosen map (the map order is set before the first round)
START = """([o, map]) => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { ammo: 'unlimited', powerups: false, terrain: false, soft: false, mut: 'off', winScore: 5 }, o));
  T.beginFromMenu(); if (map >= 0) { T.mapOrder.length = 0; T.mapOrder.push(map); T.startRound(); }
  for (let i = 0; i < 120 * 2.05; i++) T.update(1 / 120); return [T.state, T.mapId]; }"""

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    L = await page('local', 820, 1180)

    # ---------- the gatling ----------
    st = await ev(L, START, [{'game': 'classic', 'cpu': 2}, 3])
    pad = await ev(L, "__tank.gatPad()")
    check(st[1] == 3 and pad and abs(pad['x'] - 6.5) < 0.01, f'map 3 has a gatling spot in the middle {st} {pad}')
    r = await ev(L, "(() => { const T = __tank; T.tanksNow.forEach((t, i) => { if (i) t.alive = false; }); const a = T.pickups.filter(k => k.type === 'gatling').length; for (let i = 0; i < 120 * 6.2; i++) T.update(1 / 120); return [a, T.pickups.filter(k => k.type === 'gatling').length]; })()")
    check(r == [0, 1], f'it appears a few seconds into the round, power-ups off or not {r}')
    await L.screenshot(path=SHOTS + 'gm_spot.png')
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0], k = T.pickups.find(k => k.type === 'gatling');
      t.x = k.x; t.y = k.y; t.inv = 9; T.update(1 / 120); const got = t.power; t.cool = 0; t.angle = 0; T.fire(t); const n0 = T.bullets.length;
      for (let i = 0; i < 120; i++) T.update(1 / 120); const mid = T.bullets.filter(b => b.owner === 0).length;
      for (let i = 0; i < 120 * 2; i++) T.update(1 / 120);
      return [got, mid, t.gat, T.pickups.filter(k => k.type === 'gatling').length, T.gatT > 10]; })()""")
    check(r[0] == 'gatling' and r[1] >= 10 and r[2] == 0 and r[3] == 0 and r[4], f'taking it gives a stream of shots; the spot waits before it comes back {r}')
    # (that stream may have taken out its own tank; check the spot again on a fresh round)
    await ev(L, START, [{'game': 'classic', 'cpu': 2}, 3])
    r = await ev(L, """(() => { const T = __tank, t = T.tanksNow[0]; T.tanksNow.forEach((o, i) => { if (i) o.alive = false; }); T.gatT = 0.001; T.update(1 / 120);
      const k = T.pickups.find(k => k.type === 'gatling'); t.x = k.x; t.y = k.y; T.update(1 / 120); const took = t.power === 'gatling' && T.gatT > 10;
      t.x += 2; T.gatT = 0.01; for (let i = 0; i < 3; i++) T.update(1 / 120); const k2 = T.pickups.find(k => k.type === 'gatling');
      return took && !!k2 && k2.x === k.x && k2.y === k.y; })()""")
    check(r == 1, 'and it comes back to the same spot')
    for m in [1, 2]:
      st = await ev(L, START, [{'game': 'classic', 'cpu': 1}, m])
      check(await ev(L, "__tank.gatPad()") is None, f'map {m} has no gatling spot')
    for g in ['hill', 'potato', 'gun', 'soccer']:
      await ev(L, START, [{'game': g, 'cpu': 2}, -1])
      check(await ev(L, "__tank.gatPad()") is None, f'no gatling in {g}')
    # a computer tank goes for it and uses it
    st = await ev(L, START, [{'game': 'dm', 'cpu': 3}, 9])
    r = await ev(L, """(() => { const T = __tank; T.bots.add(0); T.gatT = 0; let got = false, fired = false;
      for (let i = 0; i < 120 * 120 && !fired; i++) { T.update(1 / 120); if (T.tanksNow.some(t => t.power === 'gatling')) got = true; if (T.tanksNow.some(t => t.gat > 0)) fired = true; }
      return [got, fired]; })()""")
    check(r == [True, True], f'computer tanks take the gatling and fire it {r}')
    await ev(L, "(() => { const T = __tank; const t = T.tanksNow.find(t => t.gat > 0) || T.tanksNow[0]; for (let i = 0; i < 20; i++) T.update(1 / 120); })()")
    await L.wait_for_timeout(100); await L.screenshot(path=SHOTS + 'gm_fire.png')

    # ---------- hidden mines ----------
    st = await ev(L, START, [{'game': 'classic', 'cpu': 2, 'powerups': True}, 1])
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow; tk.forEach(t => { t.inv = 99; });
      const a = tk[1]; a.power = 'mine'; a.cool = 0; T.fire(a); const mn = T.mines[0];
      const fresh = T.mineAlpha(mn);
      a.x += 2; for (let i = 0; i < 120 * 2; i++) T.update(1 / 120);
      const me = tk[0]; me.x = mn.x + 4; me.y = mn.y; const far = T.mineAlpha(mn); me.x = mn.x + 1; const near = T.mineAlpha(mn);
      return [fresh, mn.armed, far, near]; })()""")
    check(r[0] == 1 and r[1] and r[2] == 0 and r[3] > 0.5, f'one of their mines: seen while it is laid, hidden once armed, seen from right beside it {r}')
    r = await ev(L, """(() => { const T = __tank, tk = T.tanksNow, me = tk[0]; me.power = 'mine'; me.cool = 0; T.fire(me); const mn = T.mines[T.mines.length - 1]; me.x += 3;
      for (let i = 0; i < 120 * 2; i++) T.update(1 / 120); return [mn.armed, T.mineAlpha(mn)]; })()""")
    check(r[0] and 0.3 < r[1] < 1, f'my own mine stays faintly visible to me {r}')
    await L.screenshot(path=SHOTS + 'gm_mines_solo.png')
    st = await ev(L, START, [{'game': 'classic', 'cpu': 0, 'powerups': True}, 1])
    r = await ev(L, """(() => { const T = __tank, a = T.tanksNow[1]; a.inv = 99; a.power = 'mine'; a.cool = 0; T.fire(a); const mn = T.mines[0]; a.x += 2; T.tanksNow[0].inv = 99;
      for (let i = 0; i < 120 * 2; i++) T.update(1 / 120); return [mn.armed, T.mineAlpha(mn)]; })()""")
    check(r[0] and 0 < r[1] <= 0.15, f'two on one screen: an armed mine is just a smudge {r}')
    await L.close()

    # ---------- online: a guest does not see the host's armed mine, and sees the gatling ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: true, maps: 'all', winScore: 5, game: 'dm', soft: false, terrain: false, mut: 'off' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(300)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, "(() => { const T = __tank; T.mapOrder.length = 0; T.mapOrder.push(5); T.net.hostStart(); })()")
    await ev(H, "(() => { const T = __tank; T.mapOrder.length = 0; T.mapOrder.push(5); T.startRound(); })()")
    await G.wait_for_timeout(3000)
    await ev(H, "(() => { const T = __tank, a = T.tanksNow[0]; a.inv = 99; T.tanksNow[1].inv = 99; a.power = 'mine'; a.cool = 0; T.fire(a); a.x = Math.min(T.COLS - 1, a.x + 2); T.gatT = 0; })()")
    await G.wait_for_timeout(2500)
    r = await ev(G, "(() => { const T = __tank, mn = T.mines[0], me = T.tanksNow[T.net.mySeat]; return mn ? [mn.armed, T.mineAlpha(mn), Math.hypot(me.x - mn.x, me.y - mn.y) > 1.3, T.pickups.some(k => k.type === 'gatling')] : null; })()")
    check(r and r[0] and r[1] == 0 and r[2] and r[3], f'guest: the host\'s armed mine is hidden; the gatling is on its spot {r}')
    hr = await ev(H, "(() => { const T = __tank, mn = T.mines[0]; return T.mineAlpha(mn); })()")
    check(0.3 < hr < 1, f'host still sees its own mine faintly ({hr})')
    await G.screenshot(path=SHOTS + 'gm_guest.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
