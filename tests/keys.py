# Keyboard: W A S D or the arrow keys drive, J fires, K uses the skill.  python3 tests/keys.py http://127.0.0.1:8790/
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page():
      c = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await c.new_page()
      p.on('pageerror', lambda e: errors.append(str(e))); await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js: p.evaluate(js)
    PLAY = "(async () => { const T = __tank; for (let i = 0; i < 80 && T.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()"
    # one person against a computer tank: W moves, J fires, K is the skill, the arrows still drive
    L = await page()
    await ev(L, "(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 1, winScore: 7 })); T.goMenu(); T.beginFromMenu(); })()")
    await ev(L, PLAY)
    await ev(L, "(() => { const [a, b] = __tank.tanksNow; b.x = -5; b.y = -5; b.stun = 999; })()")   # the computer tank out of the way (alive, so the round goes on)
    # a cell with two open cells on every side, to drive about in
    spot = await ev(L, """(() => { const T = __tank, W = T.walls, ok = (c, r) => c >= 0 && r >= 0 && c < T.COLS && r < T.ROWS && !W[r][c];
      for (const k of [2, 1]) for (let r = k; r < T.ROWS - k; r++) for (let c = k; c < T.COLS - k; c++) { let good = true; for (let dr = -k; dr <= k && good; dr++) for (let dc = -k; dc <= k; dc++) if (!ok(c + dc, r + dr)) { good = false; break; } if (good) return [c + 0.5, r + 0.5]; }
      return [8, 6]; })()""")
    for key, dim in (('w', 'y'), ('s', 'y'), ('a', 'x'), ('d', 'x'), ('ArrowUp', 'y')):
      await ev(L, f"(() => {{ const a = __tank.tanksNow[0]; a.x = {spot[0]}; a.y = {spot[1]}; a.angle = 0; }})()")
      before = await ev(L, "(() => { const a = __tank.tanksNow[0]; return [a.x, a.y]; })()")
      await L.keyboard.down(key); await L.wait_for_timeout(700); await L.keyboard.up(key)
      after = await ev(L, "(() => { const a = __tank.tanksNow[0]; return [a.x, a.y]; })()")
      d = (after[1] - before[1]) if dim == 'y' else (after[0] - before[0])
      want = {'w': -1, 's': 1, 'a': -1, 'd': 1, 'ArrowUp': -1}[key]
      check(d * want > 0.15, f'{key} drives the tank ({dim} {d:+.2f})')
    n0 = await ev(L, '__tank.tanksNow[0].shots !== undefined ? __tank.tanksNow[0].shots : __tank.bullets.length')
    await ev(L, '__tank.bullets.length = 0')
    await L.keyboard.press('j'); await L.wait_for_timeout(120)
    check(await ev(L, '__tank.bullets.length') >= 1, 'J fires')
    await ev(L, "(() => { const a = __tank.tanksNow[0]; a.scool = 0; })()")
    await L.keyboard.press('k'); await L.wait_for_timeout(120)
    sk2 = await ev(L, "(() => { const a = __tank.tanksNow[0]; return a.scool; })()")
    check(sk2 > 0.5, f'K uses the skill (cooldown now {sk2:.1f} s)')
    # two players on one screen: W A S D + J K are the second player's, the arrows + Enter the first's
    P = await page()
    await ev(P, "(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 0, winScore: 7 })); T.goMenu(); T.beginFromMenu(); })()")
    await ev(P, PLAY)
    await ev(P, '__tank.bullets.length = 0')
    await P.keyboard.press('j'); await P.wait_for_timeout(120)
    own = await ev(P, '__tank.bullets.map(b => b.owner)')
    check(len(own) >= 1 and all(o == 1 for o in own), f'two on one screen: J fires for the W A S D player ({own})')
    await ev(P, "(() => { __tank.tanksNow[1].scool = 0; })()")
    await P.keyboard.press('k'); await P.wait_for_timeout(120)
    check(await ev(P, '__tank.tanksNow[1].scool') > 0.5, 'two on one screen: K is that player\'s skill')
    await ev(P, '__tank.bullets.length = 0')
    await P.keyboard.press('Enter'); await P.wait_for_timeout(120)
    own = await ev(P, '__tank.bullets.map(b => b.owner)')
    check(len(own) >= 1 and all(o == 0 for o in own), 'two on one screen: Enter still fires for the arrow-key player')
    # online guest: J and K reach the host
    H = await page(); G = await page()
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    await ev(G, "(async () => { for (let i = 0; i < 100 && __tank.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    await G.wait_for_timeout(300)
    await ev(H, '__tank.bullets.length = 0')
    await G.keyboard.press('j'); await H.wait_for_timeout(400)
    own = await ev(H, '__tank.bullets.map(b => b.owner)')
    check(1 in own, f"online: the guest's J fires on the host ({own})")
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
