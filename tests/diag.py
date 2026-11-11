import asyncio
from playwright.async_api import async_playwright
URL='http://127.0.0.1:8804/'
async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    P=[]
    for i in range(2):
      ctx = await br.new_context(viewport={'width': 900, 'height': 600}); p = await ctx.new_page(); await p.goto(URL); await p.wait_for_timeout(300); P.append(p)
    await P[0].evaluate('__tank.net.startHosting()'); await P[0].wait_for_timeout(1500)
    code = await P[0].evaluate('__tank.net.code')
    await P[1].evaluate(f'__tank.net.joinGame("{code}")'); await P[1].wait_for_timeout(1000)
    await P[0].evaluate("__tank.net.sendCmd('start')")
    for _ in range(6):
      await P[0].keyboard.down('ArrowUp'); await P[0].wait_for_timeout(1000); await P[0].keyboard.up('ArrowUp'); await P[0].wait_for_timeout(1000)
    print('game ms', round(await P[0].evaluate('__tank.net.rtt')), 'net ms', await P[0].evaluate('__tank.net.netRtt'))
    await br.close()
asyncio.run(main())
