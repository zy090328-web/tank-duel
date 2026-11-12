# Coming back in deathmatch / hill: nothing can hurt the tank for 2 s, shots pass through it, and the
# protection ends early when it fires or steps on the hill. A guest sees it too. Needs the server on port 8790.
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
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)

    L = await page('local', 820, 1180)
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'dm', cpu: 0, terrain: false, soft: false, powerups: false, winScore: 7 }))")
    await ev(L, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()"); await L.wait_for_timeout(2400)
    await ev(L, "__tank.kill(__tank.tanksNow[1], 0)"); await L.wait_for_timeout(2300)
    t = await ev(L, "(t => [t.alive, t.inv, t.shield])(__tank.tanksNow[1])")
    check(t[0] and t[1] > 1.5 and t[2] == 0, f'came back protected for about 2 s {t}')
    check(await ev(L, "__tank.hit(__tank.tanksNow[1], 0)") is False and await ev(L, "__tank.tanksNow[1].alive"), 'a hit does nothing while protected')
    # a shot aimed straight at it passes through
    await ev(L, "(() => { const [a, b] = __tank.tanksNow; a.x = b.x; a.y = b.y + 2; a.angle = -Math.PI / 2; a.cool = 0; a.inv = 0; __tank.fire(a); })()")
    await L.wait_for_timeout(500)
    check(await ev(L, "__tank.tanksNow[1].alive"), 'a shot passes through it')
    await ev(L, "__tank.kill(__tank.tanksNow[1], 0)"); await L.wait_for_timeout(2300)
    await L.keyboard.press('Space'); await L.wait_for_timeout(150)          # player 2 fires
    check(await ev(L, "__tank.tanksNow[1].inv") == 0, 'firing ends the protection')
    await ev(L, "__tank.kill(__tank.tanksNow[1], 0)"); await L.wait_for_timeout(2300 + 2100)
    check(await ev(L, "__tank.tanksNow[1].inv") == 0 and await ev(L, "__tank.hit(__tank.tanksNow[1], 0)") is True, 'after 2 s it can be hit again')
    await L.close()

    # hill: stepping on the hill ends it
    L = await page('hill', 820, 1180)
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'hill', cpu: 0, terrain: false, soft: false, powerups: false, winScore: 7 }))")
    await ev(L, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()"); await L.wait_for_timeout(2400)
    await ev(L, "__tank.kill(__tank.tanksNow[1], 0)"); await L.wait_for_timeout(2300)
    await ev(L, "(() => { const T = __tank, b = T.tanksNow[1]; b.x = T.COLS / 2; b.y = T.ROWS / 2; })()"); await L.wait_for_timeout(100)
    check(await ev(L, "__tank.tanksNow[1].inv") == 0, 'stepping on the hill ends the protection')
    await L.close()

    # a guest sees the protection
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 7, game: 'dm', soft: false, terrain: false })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(500)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(2600)
    await ev(H, "__tank.kill(__tank.tanksNow[1], 0)"); await G.wait_for_timeout(2400)
    check(await ev(G, "__tank.tanksNow[1].alive") and await ev(G, "__tank.tanksNow[1].inv") > 0, 'guest sees its tank come back protected')
    await G.screenshot(path='/tmp/terr/inv_guest.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
