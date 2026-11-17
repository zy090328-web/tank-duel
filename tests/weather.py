# Weather: the host picks it each round (about a third clear), every guest gets the same, and each screen can
# switch it off for itself. Needs the server:  python3 tests/weather.py http://127.0.0.1:8790/
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
    async def page(name):
      ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    L = await page('local')
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'classic', terrain:true}))")
    await ev(L, "(() => { __tank.setupLocal(); __tank.startMatch(); })()")
    n = await ev(L, "(() => { const n = {}; for (let i = 0; i < 600; i++) { const w = __tank.pickWeather(); n[w] = (n[w] || 0) + 1; } return n; })()")
    check(150 <= n.get('clear', 0) <= 250, f'about a third of rounds are clear {n}')
    check(all(n.get(k, 0) > 0 for k in ['rain', 'mist', 'embers']), 'and every kind of weather comes up')
    # every round gets its own pick
    seen = set()
    for _ in range(12):
      await ev(L, "__tank.startMatch()"); seen.add(await ev(L, '__tank.weather'))
    check(len(seen) >= 2, f'a new match picks again ({sorted(seen)})')
    # each screen can switch it off; the choice is remembered
    await ev(L, '__tank.setWeatherOn(false)')
    await L.reload(); await L.wait_for_timeout(400)
    check(await ev(L, '__tank.weatherOn') is False, 'switching it off is remembered')
    await ev(L, '__tank.setWeatherOn(true)')

    # online: guests get the host's weather
    H = await page('host'); G = await page('guest')
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'classic', powerups:false, terrain:true, mode:'classic'}))")
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    for w in ['rain', 'mist', 'embers', 'clear']:
      await ev(H, f"__tank.weather = '{w}'"); await H.wait_for_timeout(500)
      check(await ev(G, '__tank.weather') == w, f'a guest gets the host weather: {w}')
    # a server-run room sends it too
    A = await page('a'); B = await page('b')
    await ev(A, '__tank.net.createGame()'); await A.wait_for_timeout(1200)
    code = await ev(A, '__tank.net.code'); await ev(B, f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(1500)
    await ev(A, "__tank.net.sendCmd('start')"); await A.wait_for_timeout(3500)
    wa, wb = await ev(A, '__tank.weather'), await ev(B, '__tank.weather')
    check(wa == wb and wa in ['clear', 'rain', 'mist', 'embers'], f'a server-run room gives both players the same weather ({wa}, {wb})')

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
