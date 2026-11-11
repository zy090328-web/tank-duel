# Same Wi-Fi game: a tablet hosts; guests link to it directly; one guest without WebRTC falls back to the server.
# The server adds ~60 ms to everything it relays, so direct links should show a much smaller ping.
import asyncio, math
from playwright.async_api import async_playwright
URL = 'http://127.0.0.1:8805/'
NO_RTC = 'delete window.RTCPeerConnection;'
errors = []
def check(c, m): print(('PASS ' if c else 'FAIL ') + m)
async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows','--disable-features=WebRtcHideLocalIpsWithMdns'])
    async def page(name, no_rtc=False):
      ctx = await br.new_context(viewport={'width': 1000, 'height': 640})
      if no_rtc: await ctx.add_init_script(NO_RTC)
      p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(300); return p
    H = await page('host'); G1 = await page('g1'); G2 = await page('g2'); G3 = await page('g3-noRTC', True)
    await H.evaluate('__tank.net.goOnline()'); await H.wait_for_timeout(500)
    items = await H.evaluate('__tank.net.netItems().map(i => i.kind)')
    check(items[:3] == ['host', 'lan', 'join'], f'online screen offers {items}')
    await H.screenshot(path='/home/claude/tests/lan_online.png')
    await H.evaluate('__tank.net.hostGame()'); await H.wait_for_timeout(1000)
    code = await H.evaluate('__tank.net.code')
    for g in (G1, G2, G3): await g.evaluate(f'__tank.net.joinGame("{code}")')
    await H.wait_for_timeout(4000)
    nd = await H.evaluate('__tank.net.direct')
    d = [await g.evaluate('__tank.net.direct') for g in (G1, G2, G3)]
    check(nd == 2 and d == [1, 1, 0], f'host has {nd}/3 direct links; guests {d}')
    await H.evaluate('__tank.net.hostStart()'); await H.wait_for_timeout(3200)
    st = [await g.evaluate('__tank.state') for g in (G1, G2, G3)]
    check(all(s == 'play' for s in st), f'all guests playing {st}')
    for i in range(4):
      for g in (G1, G2, G3): await g.keyboard.down('ArrowUp')
      await H.wait_for_timeout(500)
      for g in (G1, G2, G3): await g.keyboard.up('ArrowUp')
      await H.wait_for_timeout(500)
    r = [round(await g.evaluate('__tank.net.rtt')) for g in (G1, G2, G3)]
    check(r[0] < 40 and r[1] < 40 and r[2] > 60, f'ping: direct guests {r[0]} / {r[1]} ms, fallback guest {r[2]} ms')
    s3 = await G3.evaluate('__tank.net.mySeat')
    hp = await H.evaluate(f'[__tank.tanksNow[{s3}].x, __tank.tanksNow[{s3}].y]'); gp = await G3.evaluate(f'[__tank.tanksNow[{s3}].x, __tank.tanksNow[{s3}].y]')
    check(math.hypot(hp[0]-gp[0], hp[1]-gp[1]) < 0.3, 'fallback guest still plays normally through the server')
    for g in (G1, G2, G3): await g.keyboard.press('Enter')
    await H.wait_for_timeout(300)
    owners = await H.evaluate("__tank.net.buildSnap().E.filter(e => e[1] === 'shot').map(e => e[2])")
    check(len(set(owners)) >= 3, f'shots from every guest reached the host {sorted(set(owners))}')
    await G1.screenshot(path='/home/claude/tests/lan_guest.png')
    await G1.close(); await H.wait_for_timeout(1500)
    check(await H.evaluate('__tank.net.direct') == 1, 'a guest leaving closes its link')
    await br.close()
  print('\nERRORS:' if errors else '\nno console errors')
  for e in errors[:10]: print('  ', e)
asyncio.run(main())
