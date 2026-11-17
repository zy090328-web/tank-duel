# Decoy and Rewind, and hero records on the leaderboard. Needs the server:
#   python3 tests/heroes2.py http://127.0.0.1:8790/
import asyncio, sys, json, random, urllib.request
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

LOCAL = r"""
([a, b]) => { const T = __tank;
  T.setSettings(Object.assign({}, T.settings(), { cpu: 0, maps: 'classic', powerups: false, terrain: false, mode: 'classic' }));
  T.setMySkin(a); T.setP2Skin(b); T.setupLocal(); T.startMatch(); T.state = 'play';
  const [t0, t1] = T.tanksNow, W = T.walls;
  const open = (c, r) => c > 0 && r > 0 && c < T.COLS - 1 && r < T.ROWS - 1 && !W[r][c];
  // the longest run of open cells in a row: t0 at its left end facing right, t1 at its right end
  let best = null;
  for (let r = 1; r < T.ROWS - 1; r++) { let c0 = -1; for (let c = 0; c <= T.COLS; c++) { const o = c < T.COLS && open(c, r);
    if (o && c0 < 0) c0 = c; if (!o && c0 >= 0) { if (!best || c - c0 > best.n) best = { r, c0, n: c - c0 }; c0 = -1; } } }
  t0.x = best.c0 + 0.5; t0.y = best.r + 0.5; t0.angle = 0; t1.x = best.c0 + best.n - 0.5; t1.y = best.r + 0.5; t1.angle = Math.PI;
  t0.inv = t1.inv = 0; return best.n;
}"""
STEP = "(n) => { const T = __tank; for (let i = 0; i < n; i++) T.stepPhysics(T.C.STEP, true, true); }"

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    P = await page('local')

    # ---------- Decoy ----------
    run = await ev(P, LOCAL, ['decoy', 'classic']); await ev(P, STEP, 2)
    check(run >= 4, f'an open run of {run} cells to test in')
    x0 = await ev(P, '__tank.tanksNow[0].x')
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True, 'a Decoy uses its skill')
    d = await ev(P, '__tank.decoys.map(d => [d.x, d.y, d.owner])')
    check(len(d) == 1 and d[0][2] == 0 and abs(d[0][0] - x0) < 0.01, 'a decoy appears where the tank is')
    await ev(P, STEP, 60)
    dx = await ev(P, '__tank.decoys[0].x')
    check(dx - x0 > 0.8, f'it drives on the way the tank faced ({dx - x0:.2f} cells in 0.5 s)')
    check(abs(await ev(P, '__tank.tanksNow[0].x') - x0) < 0.01, 'while the real tank stays put')
    # an enemy shot pops it and the owner lives
    await ev(P, """(() => { const T = __tank, d = T.decoys[0]; T.bullets.push({ id: 9e6, x: d.x + 0.9, y: d.y, vx: -6.2, vy: 0, owner: 1, age: 1, bounces: 0, trail: [], tick: 0 }); })()""")
    await ev(P, STEP, 40)
    check(await ev(P, '__tank.decoys.length') == 0, 'an enemy shot pops the decoy')
    check(await ev(P, '__tank.tanksNow[0].alive'), '...and the real tank is unharmed')
    check(await ev(P, '__tank.bullets.filter(b => b.id === 9e6).length') == 0, '...and the shot is spent')
    # it fades on its own
    await ev(P, LOCAL, ['decoy', 'classic']); await ev(P, STEP, 2)
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])'); await ev(P, STEP, int(2.9 * 120))
    check(await ev(P, '__tank.decoys.length') == 1, 'a decoy is still there after 2.9 s')
    await ev(P, STEP, 20)
    check(await ev(P, '__tank.decoys.length') == 0, '...and gone after 3 s')
    # a computer tank takes a nearer decoy for its owner
    await ev(P, LOCAL, ['decoy', 'classic']); await ev(P, STEP, 2)
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])'); await ev(P, STEP, 70)
    seen = await ev(P, """(() => { const T = __tank; T.bots.add(1); const t1 = T.tanksNow[1]; t1.ai = null; T.botInput(1); const d = T.decoys[0]; const l = t1.ai.last;
      return [l ? l.x : null, d.x, T.tanksNow[0].x]; })()""")
    check(seen[0] is not None and abs(seen[0] - seen[1]) < 0.01, f'a computer tank goes for the nearer decoy (aims at {seen[0]}, decoy {seen[1]:.2f}, real {seen[2]:.2f})')
    await ev(P, '__tank.bots.clear()')

    # ---------- Rewind ----------
    await ev(P, LOCAL, ['rewind', 'classic']); await ev(P, STEP, 2)
    xs = await ev(P, """(() => { const T = __tank, t = T.tanksNow[0], xs = [];
      for (let i = 0; i < 300; i++) { t.x += 0.004; T.stepPhysics(T.C.STEP, true, true); xs.push(t.x); } return xs; })()""")
    before = xs[-1]; want = xs[-1 - 240]
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True, 'a Rewind uses its skill')
    now = await ev(P, '__tank.tanksNow[0].x')
    check(abs(now - want) < 0.06, f'it goes back to where it was 2 s ago ({now:.2f}, was {want:.2f} then, {before:.2f} now)')
    await ev(P, LOCAL, ['rewind', 'classic']); await ev(P, STEP, 2)
    await ev(P, """(() => { const T = __tank, t = T.tanksNow[0]; for (let i = 0; i < 300; i++) { t.x += 0.004; T.stepPhysics(T.C.STEP, true, true); } t.stun = 1; })()""")
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is False, 'not while stunned')
    await ev(P, """(() => { const t = __tank.tanksNow[0]; t.stun = 0; t.scool = 0; t.snare = 2; })()""")
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is True and await ev(P, '__tank.tanksNow[0].snare') == 0, 'it slips out of a snare')
    await ev(P, LOCAL, ['rewind', 'classic'])
    check(await ev(P, '__tank.useSkill(__tank.tanksNow[0])') is False and await ev(P, '__tank.tanksNow[0].scool') == 0, 'with nowhere to go back to it does nothing and costs nothing')

    # ---------- online ----------
    H = await page('host'); G = await page('guest')
    await ev(H, "__tank.setMySkin('decoy')"); await ev(G, "__tank.setMySkin('rewind')")
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'classic', powerups:false, terrain:false, mode:'classic'}))")
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(4200)
    check(await ev(G, '__tank.state') == 'play', 'online match running')
    await H.keyboard.press('e'); await H.wait_for_timeout(400)
    check(await ev(G, '__tank.decoys.length') == 1, 'a guest sees the host decoy')
    hd = await ev(H, '__tank.decoys.map(d => [d.x, d.y])'); gd = await ev(G, '__tank.decoys.map(d => [d.x, d.y])')
    check(hd and gd and abs(hd[0][0] - gd[0][0]) + abs(hd[0][1] - gd[0][1]) < 0.6, 'in about the same place')
    # the guest drives for a while, then rewinds
    for k in ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowUp']:
      await G.keyboard.down(k); await G.wait_for_timeout(700); await G.keyboard.up(k)
    seat = await ev(G, '__tank.net.mySeat')
    before = await ev(H, f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    await G.keyboard.press('e'); await G.wait_for_timeout(700)
    hpos = await ev(H, f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    gpos = await ev(G, f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    moved = ((hpos[0] - before[0]) ** 2 + (hpos[1] - before[1]) ** 2) ** 0.5
    gap = ((hpos[0] - gpos[0]) ** 2 + (hpos[1] - gpos[1]) ** 2) ** 0.5
    check(await ev(H, f'__tank.tanksNow[{seat}].scool') > 0, 'the guest rewound on the host')
    check(gap < 0.15, f"and the guest's own tank is where the host has it ({gap:.2f} apart; jumped {moved:.2f})")

    # ---------- hero records ----------
    tag = str(random.randint(1, 10**9))
    def post(r): urllib.request.urlopen(urllib.request.Request(URL + 'result', data=json.dumps(r).encode(), headers={'content-type': 'application/json'}, method='POST'), timeout=3)
    def board(): return json.loads(urllib.request.urlopen(URL + 'board', timeout=3).read())
    old = {h['id']: h for h in board().get('heroes', [])}
    post({ 'id': 'h' + tag + 'a', 'm': 'classic', 'p': [{ 'n': 'Ann', 'w': True, 'k': 3, 'd': 1, 's': 'decoy' }, { 'n': 'Bo', 'w': False, 'k': 1, 'd': 3, 's': 'rewind' }, { 'n': 'CPU', 'w': False, 'k': 0, 'd': 1, 'bot': True, 's': 'heavy' }] })
    post({ 'id': 'h' + tag + 'b', 'm': 'classic', 'p': [{ 'n': 'Ann', 'w': False, 'k': 0, 'd': 2, 's': 'decoy' }, { 'n': 'Bo', 'w': True, 'k': 2, 'd': 0, 's': 'bad<skin>' }] })
    new = {h['id']: h for h in board().get('heroes', [])}
    dd = lambda hid, f: new.get(hid, {}).get(f, 0) - old.get(hid, {}).get(f, 0)
    check(dd('decoy', 'games') == 2 and dd('decoy', 'wins') == 1 and dd('decoy', 'kills') == 3 and dd('decoy', 'deaths') == 3, 'the board adds up games, wins, kills and deaths per hero')
    check(dd('rewind', 'games') == 1 and dd('rewind', 'wins') == 0, '...for each hero')
    check(dd('heavy', 'games') == 0, 'computer tanks are left out')
    check(not any('<' in k for k in new), 'a made-up hero name is not stored')
    # the screen
    await ev(P, '__tank.openBoard ? __tank.openBoard() : 0'); await P.wait_for_timeout(1200)

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
