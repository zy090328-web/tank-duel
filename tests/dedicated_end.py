import asyncio, urllib.request
from playwright.async_api import async_playwright
URL='http://127.0.0.1:8790/'
def post(path): urllib.request.urlopen(urllib.request.Request(URL + path, method='POST')).read()
def check(c, m): print(('PASS ' if c else 'FAIL ') + m)
async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    P = []
    for i in range(3):
      ctx = await br.new_context(viewport={'width': 900, 'height': 600}); p = await ctx.new_page(); await p.goto(URL); await p.wait_for_timeout(300); P.append(p)
    await P[0].evaluate("__tank.setSettings({ammo:'unlimited', powerups:false, maps:'classic', winScore:3})")
    await P[0].evaluate('__tank.net.startHosting()'); await P[0].wait_for_timeout(1500)
    code = await P[0].evaluate('__tank.net.code')
    for p in P[1:]: await p.evaluate(f'__tank.net.joinGame("{code}")')
    await P[0].wait_for_timeout(1200)
    await P[0].evaluate("__tank.net.sendCmd('start')"); await P[0].wait_for_timeout(3000)
    await P[0].close(); await P[1].wait_for_timeout(1200)          # the creator leaves; p2 leads now
    for _ in range(30):
      if await P[1].evaluate('__tank.state') == 'matchEnd': break
      post('test/endround'); await P[1].wait_for_timeout(700)
    check(await P[1].evaluate('__tank.state') == 'matchEnd', f"match ended, scores {await P[1].evaluate('__tank.scores')}")
    await P[1].wait_for_timeout(1400)
    check(await P[1].evaluate('__tank.endItems().map(i => i.kind)') == ['rematch', 'lobby'], 'new leader gets Rematch / Lobby')
    check(await P[2].evaluate('__tank.endItems().map(i => i.kind)') == ['leave'], 'other player gets Leave')
    await P[2].evaluate("__tank.net.sendCmd('rematch')"); await P[2].wait_for_timeout(700)
    check(await P[2].evaluate('__tank.state') == 'matchEnd', 'non-leader cannot start a rematch')
    await P[1].evaluate("__tank.net.sendCmd('rematch')"); await P[1].wait_for_timeout(800)
    st = await P[2].evaluate('__tank.state')
    check(st in ('countdown', 'play'), f'rematch starts for everyone ({st}), {await P[2].evaluate("__tank.net.NP")} tanks')
    for _ in range(30):
      if await P[1].evaluate('__tank.state') == 'matchEnd': break
      post('test/endround'); await P[1].wait_for_timeout(700)
    await P[1].wait_for_timeout(1400)
    await P[1].evaluate("__tank.net.sendCmd('lobby')"); await P[1].wait_for_timeout(800)
    check(await P[2].evaluate('__tank.state') == 'guestWait', 'lobby returns everyone to the waiting room')
    await br.close()
asyncio.run(main())
