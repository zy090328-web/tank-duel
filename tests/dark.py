# Lights-out maps: in the dark a tank is seen only by enemies close by or just after it fires; under a lamp it is
# seen; a shot or a blast puts a lamp out, for everyone; the starts cannot see each other.
# Needs the server:  python3 tests/dark.py http://127.0.0.1:8790/
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# a solo match against one computer tank on lights-out map `id`, held still (state play, both tanks placed by hand)
SETUP = r"""
(id) => { const T = __tank;
  T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 1, maps: 'all', powerups: false, terrain: false, soft: false }));
  T.goMenu(); T.beginFromMenu(); T.loadMap(id); T.resetEntities(); T.state = 'play';
  const [a, b] = T.tanksNow; a.inv = b.inv = 0; a.reveal = b.reveal = 0; return T.lamps.length; }"""
# an open cell at least `d` from every lamp (dark), or the open cell nearest a lit lamp (lit)
FIND = r"""
([kind, d]) => { const T = __tank, W = T.walls; let best = null;
  for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) { if (W[r][c]) continue;
    const x = c + 0.5, y = r + 0.5, near = Math.min(...T.lamps.filter(l => l.alive).map(l => Math.hypot(l.x - x, l.y - y)));
    if (kind === 'dark' && near > d) return [x, y];
    if (kind === 'lit' && near > 0.4 && T.litAt(x, y) && (!best || near < best[2])) best = [x, y, near]; }
  return best; }"""

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    S = await page('solo')
    ids = await ev(S, '[...__tank.DARK_MAPS]')
    check(len(ids) == 3, f'three lights-out maps {ids}')
    pools = await ev(S, """(() => { const T = __tank, out = {};
      for (const mp of ['all', 'classic', 'complex', 'dark']) { T.setSettings(Object.assign({}, T.settings(), { maps: mp, cpu: 1 })); out[mp] = T.mapPool(); }
      return out; })()""")
    check(all(not set(pools[k]) & set(ids) for k in ('all', 'classic', 'complex')), f'the other pools leave the lights-out maps out {pools}')
    check(sorted(pools['dark']) == sorted(ids), f'the Dark pool is the lights-out maps {pools["dark"]}')
    # a wall between a lamp and a cell in its reach keeps that cell dark
    shade = await ev(S, """(id) => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { maps: 'dark', cpu: 1 }));
      let found = null;
      for (const m of T.DARK_MAPS) { T.loadMap(m); T.resetEntities();
        for (const l of T.lamps) for (let r = 0; r < T.ROWS && !found; r++) for (let c = 0; c < T.COLS && !found; c++) {
          const x = c + 0.5, y = r + 0.5;
          if (!T.walls[r][c] && Math.hypot(l.x - x, l.y - y) < T.C.LAMP_R * 0.7 && !T.lightReaches(l.x, l.y, x, y) && !T.lamps.some(o => o !== l && Math.hypot(o.x - x, o.y - y) < T.C.LAMP_R)) found = [m, x, y, T.litAt(x, y)];
        }
        if (found) break; }
      return found; }""")
    check(shade is not None and shade[3] is False, f'a cell a lamp would reach but for a wall stays dark {shade}')
    for id in ids:
      await ev(S, SETUP, id)
      sp = await ev(S, '__tank.spawn.map(s => [s.x, s.y])')
      check(not await ev(S, f'__tank.lineClear({sp[0][0]}, {sp[0][1]}, {sp[1][0]}, {sp[1][1]}, 0.08)'), f'map {id}: the two starts cannot see each other')
    id = ids[0]
    n = await ev(S, SETUP, id)
    check(n >= 4, f'map {id} has {n} lamps')
    dark = await ev(S, FIND, ['dark', 3.2]); lit = await ev(S, FIND, ['lit', 0])
    put = lambda who, xy: ev(S, f"(() => {{ const t = __tank.tanksNow[{who}]; t.x = {xy[0]}; t.y = {xy[1]}; t.reveal = 0; }})()")
    # the computer tank in the dark, far from me: not seen
    await put(1, dark); far = await ev(S, FIND, ['dark', 0])
    me = await ev(S, f"""(() => {{ const T = __tank, W = T.walls, b = T.tanksNow[1];
      for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (!W[r][c] && Math.hypot(c + 0.5 - b.x, r + 0.5 - b.y) > 4) return [c + 0.5, r + 0.5]; }})()""")
    await put(0, me)
    check(await ev(S, '__tank.inDark(__tank.tanksNow[1])'), 'a tank away from the lamps is in the dark')
    check(not await ev(S, '__tank.seenBy(0, __tank.tanksNow[1])'), '...and I cannot see it from afar')
    check(not await ev(S, '__tank.seenBy(1, __tank.tanksNow[0])') or not await ev(S, '__tank.inDark(__tank.tanksNow[0])'), '...nor can it see me in the dark')
    await ev(S, "(() => { const [a, b] = __tank.tanksNow; a.x = b.x + 1.6; a.y = b.y; })()")
    check(await ev(S, '__tank.seenBy(0, __tank.tanksNow[1])'), 'close by, I see it')
    await put(0, me); await ev(S, '__tank.tanksNow[1].reveal = 0.5')
    check(await ev(S, '__tank.seenBy(0, __tank.tanksNow[1])'), 'just after it fires, I see it')
    await put(1, lit[:2])
    check(not await ev(S, '__tank.inDark(__tank.tanksNow[1])') and await ev(S, '__tank.seenBy(0, __tank.tanksNow[1])'), 'under a lamp, I see it')
    # put that lamp out with a shot
    lamp = await ev(S, f"""(() => {{ const T = __tank, b = T.tanksNow[1]; let k = -1, d = 9;
      T.lamps.forEach((l, i) => {{ const e = Math.hypot(l.x - b.x, l.y - b.y); if (l.alive && e < d) {{ d = e; k = i; }} }}); return k; }})()""")
    await ev(S, f"""(() => {{ const T = __tank, l = T.lamps[{lamp}]; T.tanksNow[0].x = 0.5; T.tanksNow[0].y = 0.5;
      T.bullets.push({{ id: 7e6, x: l.x + 0.6, y: l.y, vx: -6.2, vy: 0, owner: 0, age: 1, bounces: 0, trail: [], tick: 0 }}); }})()""")
    await ev(S, '(n) => { for (let i = 0; i < n; i++) __tank.stepPhysics(__tank.C.STEP, true, false); }', 30)
    check(not await ev(S, f'__tank.lamps[{lamp}].alive'), 'a shot puts a lamp out')
    check(await ev(S, '__tank.bullets.filter(b => b.id === 7e6).length') == 0, '...and is spent')
    # a new round lights them all again
    await ev(S, SETUP, id)
    check(await ev(S, '__tank.lamps.every(l => l.alive)'), 'a new round lights every lamp again')
    # a two-player shared screen hides nobody
    await ev(S, """(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { cpu: 0 })); T.setupLocal(); T.startMatch(); })()""")
    check(await ev(S, '__tank.viewer()') == -1, 'two players on one screen: everyone is shown')

    # online: a lamp put out on the host goes out for the guest
    H = await page('host'); G = await page('guest')
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'dark', powerups:false, terrain:false, mode:'classic'}))")
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(2500)
    got = None
    for _ in range(40):
      if await ev(H, '__tank.DARK_MAPS.has(__tank.mapId)'): got = await ev(H, '__tank.mapId'); break
      await ev(H, '__tank.startMatch()'); await H.wait_for_timeout(250)
    check(got is not None, f'the online Dark pool plays lights-out maps (got {got})')
    if got is not None:
      await H.wait_for_timeout(1200)
      check(await ev(G, '__tank.mapId') == got and await ev(G, '__tank.lamps.length') == await ev(H, '__tank.lamps.length'), 'the guest has the same map and lamps')
      await ev(H, '__tank.lampOut(__tank.lamps[0])'); await H.wait_for_timeout(500)
      check(await ev(G, '__tank.lamps[0].alive') is False, 'a lamp put out on the host is out for the guest')

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
