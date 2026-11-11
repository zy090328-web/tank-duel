# Measures how smoothly a guest draws the host's tank: record the host's true path and the guest's
# drawn path on one clock, find the best constant delay between them, and report what is left over.
import asyncio, sys, math, bisect
from playwright.async_api import async_playwright
REC = '''(() => { window.__rec = []; const f = () => { const t = __tank.tanksNow[0];
  if (t) __rec.push([performance.timeOrigin + performance.now(), t.x, t.y]); requestAnimationFrame(f); };
  requestAnimationFrame(f); })()'''
async def run(url):
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    pages = []
    for _ in range(2):
      ctx = await br.new_context(viewport={'width': 900, 'height': 600}); p = await ctx.new_page(); await p.goto(url); await p.wait_for_timeout(300); pages.append(p)
    H, G = pages
    await H.evaluate("__tank.setSettings({ammo:'unlimited', powerups:false, maps:'classic', winScore:7})")
    await H.evaluate('__tank.net.hostGame()'); await H.wait_for_timeout(800)
    code = await H.evaluate('__tank.net.code')
    await G.evaluate(f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await H.evaluate('__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    await H.evaluate(REC); await G.evaluate(REC)
    keys = ['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft']
    for i in range(16):                       # the host drives around for about 6 s
      k = keys[i % 4]; await H.keyboard.down(k); await H.wait_for_timeout(380); await H.keyboard.up(k)
    h = await H.evaluate('__rec'); g = await G.evaluate('__rec')
    await br.close()
  ht = [r[0] for r in h]
  def host_at(t):
    i = bisect.bisect_left(ht, t)
    if i <= 0 or i >= len(h): return None
    a, b = h[i-1], h[i]; k = (t - a[0]) / max(1e-6, b[0] - a[0])
    return (a[1] + (b[1]-a[1])*k, a[2] + (b[2]-a[2])*k)
  best = None
  for D in range(0, 400, 5):
    errs = []
    for t, x, y in g[30:]:
      p = host_at(t - D)
      if p: errs.append(math.hypot(x - p[0], y - p[1]))
    if len(errs) < 100: continue
    rms = math.sqrt(sum(e*e for e in errs) / len(errs))
    if not best or rms < best[1]: best = (D, rms, max(errs), errs)
  D, rms, mx, errs = best
  steps = [math.hypot(g[i][1]-g[i-1][1], g[i][2]-g[i-1][2]) for i in range(31, len(g))]
  moving = [s for s in steps if s > 1e-4]
  # a 'hitch' is a frame where the drawn tank stood still or jumped more than twice its usual step
  med = sorted(moving)[len(moving)//2] if moving else 0
  hitches = sum(1 for s in steps if s < 1e-4 or s > 2.5 * med)
  return D, rms, mx, hitches, len(steps)
for label, url in [('before', 'http://127.0.0.1:8801/'), ('after', 'http://127.0.0.1:8802/')]:
  D, rms, mx, hitch, n = asyncio.run(run(url))
  print(f'{label:6}: delay {D:3d} ms | wobble rms {rms*100:5.1f}% of a cell, worst {mx*100:5.1f}% | hitch frames {hitch}/{n} ({100*hitch/n:.0f}%)')
