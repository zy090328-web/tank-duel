# Party rules: every rule runs with computer tanks; the tuning goes back after; random picks change;
# a guest gets the round's rule and the same tuning. Needs the server on port 8790.
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
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    L = await page('local', 820, 1180)
    base = await ev(L, "JSON.stringify(__tank.C)")
    for mid in ['bouncy', 'fast', 'big', 'rapid', 'storm', 'slow', 'bank', 'fog']:
      r = await ev(L, f"""() => {{ const T = __tank; T.goMenu(); T.setSettings(Object.assign({{}}, T.settings(), {{ game: 'dm', cpu: 3, mut: '{mid}', powerups: false, winScore: 7 }})); T.beginFromMenu(); T.bots.add(0);
        for (let i = 0; i < 120 * 15; i++) T.update(1 / 120);
        return [T.mutNow, T.state, T.pickups.length]; }}""")
      check(r[0] == mid and r[1] == 'play' and (mid != 'storm' or r[2] >= 2), f'{mid}: 15 s with computer tanks {r}')
    await ev(L, "__tank.goMenu()")
    check(await ev(L, "JSON.stringify(__tank.C)") == base, 'back at the menu the tuning is as it was')
    picks = await ev(L, """() => { const T = __tank; T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 0, mut: 'random' })); const out = [];
      for (let i = 0; i < 12; i++) { T.goMenu(); T.beginFromMenu(); out.push(T.mutNow); } return out; }""")
    check(len(set(picks)) >= 4 and 'fog' not in picks, f'random rules vary, and no fog on a shared screen {picks}')
    await L.close()
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 5, game: 'classic', soft: false, terrain: false, mut: 'big' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(400)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()'); await G.wait_for_timeout(2500)
    check(await ev(G, "[__tank.mutNow, __tank.C.TANK_R]") == ['big', 0.42], 'guest plays the round with the same rule and tuning')
    await G.screenshot(path='/tmp/terr/party_guest.png')
    await ev(H, "__tank.net.hostLobby()"); await G.wait_for_timeout(800)
    check(await ev(G, "[__tank.mutNow, __tank.C.TANK_R]") == ['', 0.3], 'back in the waiting room the rule is off')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
