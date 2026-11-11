import asyncio, math
from playwright.async_api import async_playwright
URL='http://127.0.0.1:8791/'
errs=[]
async def main():
  async with async_playwright() as pw:
    br=await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx=await br.new_context(viewport={'width':1000,'height':600})
      p=await ctx.new_page()
      p.on('pageerror', lambda e: errs.append(f'{name}: {e}'))
      p.on('console', lambda m: errs.append(f'{name}: {m.text}') if m.type=='error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(300); return p
    H=await page('host'); G=await page('guest')
    await H.evaluate('__tank.net.hostGame()'); await H.wait_for_timeout(800)
    code=await H.evaluate('__tank.net.code')
    await G.evaluate(f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await H.evaluate('__tank.net.hostStart()'); await H.wait_for_timeout(3500)
    print('guest state', await G.evaluate('__tank.state'))
    seat = await G.evaluate('__tank.net.mySeat')
    p0 = await G.evaluate(f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    # hold a direction and see how soon the guest's own tank moves on the guest
    await G.keyboard.down('ArrowLeft')
    await G.wait_for_timeout(120)
    p1 = await G.evaluate(f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y, __tank.tanksNow[{seat}].angle]')
    hp1 = await H.evaluate(f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    await G.wait_for_timeout(900)
    await G.keyboard.up('ArrowLeft')
    await G.wait_for_timeout(1500)
    pg = await G.evaluate(f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    ph = await H.evaluate(f'[__tank.tanksNow[{seat}].x, __tank.tanksNow[{seat}].y]')
    d=lambda a,b: math.hypot(a[0]-b[0],a[1]-b[1])
    print(f'after 120 ms held: guest moved {d(p0,p1):.2f} (angle {p1[2]:.2f}), host moved {d(p0,hp1):.2f}')
    print(f'after settling: guest vs host differ by {d(pg,ph):.3f} cells; total moved {d(p0,ph):.2f}')
    print('ping ms', await G.evaluate('Math.round(window.__tank.net.rtt || 0)'), 'interp', await G.evaluate('window.__tank.net.interp'))
    await br.close()
  print('errors', errs[:5])
asyncio.run(main())
