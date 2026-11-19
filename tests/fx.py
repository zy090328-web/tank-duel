# Explosions and shaded tanks: a tank going up throws a fireball and bits that land; locally the game holds still for
# an instant; shading drops itself on a device that is too slow.  python3 tests/fx.py http://127.0.0.1:8790/
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
    L = await page()
    ev = lambda p, js: p.evaluate(js)
    await ev(L, "(() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 1, winScore: 7 })); T.goMenu(); T.beginFromMenu(); })()")
    await ev(L, "(async () => { const T = __tank; for (let i = 0; i < 60 && T.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    r = await ev(L, "(() => { const T = __tank, [a, b] = T.tanksNow; T.kill(b, a.id); return [T.fireballs.length, T.debris.length, T.hitstop]; })()")
    check(r[0] >= 1 and r[1] >= 6, f'a tank going up throws a fireball and bits of itself ({r[0]}, {r[1]})')
    check(r[2] > 0.05, f'playing on one screen, the game holds still for an instant ({r[2]:.2f} s)')
    await L.wait_for_timeout(2500)
    r = await ev(L, '[__tank.fireballs.length, __tank.debris.length]')
    check(r == [0, 0], f'the fire dies and the bits come down and stay on the floor ({r})')
    # shading drops itself if frames stay slow in a match
    await ev(L, "(() => { const T = __tank; T.goMenu(); T.beginFromMenu(); })()")
    await ev(L, "(async () => { const T = __tank; for (let i = 0; i < 60 && T.state !== 'play'; i++) await new Promise(r => setTimeout(r, 100)); })()")
    on = await ev(L, '__tank.tankLit')
    await ev(L, "(() => { for (let i = 0; i < 100; i++) __tank.watchFrames(0.04); })()")
    check(on is True and await ev(L, '__tank.tankLit') is False, 'tank shading is on, and goes off when frames stay slow')
    # online: a kill on the host shows its explosion on the guest, and neither screen holds still
    H = await page(); G = await page()
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(4500)
    await ev(H, "(() => { const T = __tank, [a, b] = T.tanksNow; T.kill(b, a.id); })()"); await H.wait_for_timeout(150)
    g = await ev(G, '[__tank.fireballs.length + __tank.debris.length, __tank.hitstop]'); h = await ev(H, '__tank.hitstop')
    check(g[0] > 0, f'the guest sees the explosion ({g[0]})')
    check(g[1] <= 0 and h <= 0, 'online, no screen holds still')
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
