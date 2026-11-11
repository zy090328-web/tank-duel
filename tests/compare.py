# Player A drives, player B watches. Both are guests. Compare how far behind (and how steadily)
# B sees A's tank, in a room hosted by a third tablet vs a room run by the server.
import asyncio, math, bisect
from playwright.async_api import async_playwright
URL = 'http://127.0.0.1:8803/'
REC = '''(s => { window.__rec = []; const f = () => { const t = __tank.tanksNow[s];
  if (t) __rec.push([performance.timeOrigin + performance.now(), t.x, t.y]); requestAnimationFrame(f); }; requestAnimationFrame(f); })'''
async def run(server_run):
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    pages = []
    for _ in range(3):
      ctx = await br.new_context(viewport={'width': 900, 'height': 600}); p = await ctx.new_page(); await p.goto(URL); await p.wait_for_timeout(300); pages.append(p)
    H, A, B = pages
    if server_run:
      await A.evaluate("__tank.setSettings({ammo:'unlimited', powerups:false, maps:'classic', winScore:7})")
      await A.evaluate('__tank.net.startHosting()'); await A.wait_for_timeout(1800)
      code = await A.evaluate('__tank.net.code')
      await B.evaluate(f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(1500)
      await A.evaluate("__tank.net.sendCmd('start')")
    else:
      await H.evaluate("__tank.setSettings({ammo:'unlimited', powerups:false, maps:'classic', winScore:7})")
      await H.evaluate('__tank.net.hostGame()'); await H.wait_for_timeout(1000)
      code = await H.evaluate('__tank.net.code')
      for p in (A, B): await p.evaluate(f'__tank.net.joinGame("{code}")')
      await A.wait_for_timeout(1500)
      await H.evaluate('__tank.net.hostStart()')
    await A.wait_for_timeout(3500)
    seat = await A.evaluate('__tank.net.mySeat')
    await A.evaluate(REC + f'({seat})'); await B.evaluate(REC + f'({seat})')
    keys = ['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft']
    for i in range(16):
      k = keys[i % 4]; await A.keyboard.down(k); await A.wait_for_timeout(380); await A.keyboard.up(k)
    rtt = await A.evaluate('__tank.net.rtt')
    a = await A.evaluate('__rec'); b = await B.evaluate('__rec')
    await br.close()
  at = [r[0] for r in a]
  def a_at(t):
    i = bisect.bisect_left(at, t)
    if i <= 0 or i >= len(a): return None
    p, q = a[i-1], a[i]; k = (t - p[0]) / max(1e-6, q[0] - p[0])
    return (p[1] + (q[1]-p[1])*k, p[2] + (q[2]-p[2])*k)
  best = None
  for D in range(0, 600, 5):
    errs = [math.hypot(x - p[0], y - p[1]) for t, x, y in b[30:] if (p := a_at(t - D))]
    if len(errs) < 100: continue
    rms = math.sqrt(sum(e*e for e in errs) / len(errs))
    if not best or rms < best[1]: best = (D, rms, max(errs))
  return rtt, best
for label, sr in [('tablet hosts', False), ('server runs', True)]:
  rtt, (D, rms, mx) = asyncio.run(run(sr))
  print(f'{label:12}: A\'s ping {rtt:5.0f} ms | B sees A {D:3d} ms late | wobble rms {rms*100:4.1f}% of a cell, worst {mx*100:4.1f}%')
