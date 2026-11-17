# Hero changes: Heavy's armour (one hit only knocks it back, grows back after 8 s), Cyber's EMP holds enemies
# 0.8 s, Recon's radar marks where enemies were without breaking a cloak, and guests see all of it.
# Needs the server: python3 tests/heroes.py http://127.0.0.1:8790/
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# a local two-player match on an open map with the two tanks a little apart; returns nothing
LOCAL = r"""
([a, b]) => { const T = __tank;
  T.setSettings(Object.assign({}, T.settings(), { cpu: 0, maps: 'classic', powerups: false, terrain: false, mode: 'classic' }));
  T.setMySkin(a); T.setP2Skin(b); T.setupLocal(); T.startMatch(); T.state = 'play';
  const [t0, t1] = T.tanksNow, W = T.walls;
  // two tanks 2 cells apart in a run of 5 open cells in one row
  const open = (c, r) => c > 0 && r > 0 && c < T.COLS - 1 && r < T.ROWS - 1 && !W[r][c];
  for (let r = 1; r < T.ROWS - 1; r++) for (let c = 1; c < T.COLS - 4; c++) {
    let ok = true; for (let dc = -1; dc <= 3; dc++) if (!open(c + dc, r)) ok = false;
    if (ok) { t0.x = c + 0.5; t0.y = r + 0.5; t1.x = c + 2.5; t1.y = r + 0.5; t0.angle = 0; t1.angle = Math.PI; t0.inv = t1.inv = 0; return; }
  }
  throw new Error('no open row');
}"""
STEP = "(n) => { const T = __tank; for (let i = 0; i < n; i++) T.stepPhysics(T.C.STEP, true, true); }"

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    P = await page('local')

    # ---------- Heavy armour ----------
    await ev(P, LOCAL, ['heavy', 'classic']); await ev(P, STEP, 2)
    check(await ev(P, '__tank.tanksNow[0].armor') == 1, 'a Heavy starts with armour')
    check(await ev(P, '__tank.tanksNow[1].armor') == 0, 'other tanks have none')
    x0 = await ev(P, '__tank.tanksNow[0].x')
    killed = await ev(P, '__tank.hit(__tank.tanksNow[0], 1)')
    check(killed is False and await ev(P, '__tank.tanksNow[0].alive'), 'the first hit does not kill a Heavy')
    check(await ev(P, '__tank.tanksNow[0].armor') == 0, '...and breaks its armour')
    check(await ev(P, '__tank.hit(__tank.tanksNow[0], 1)') is False, 'a second pellet of the same volley glances off')
    await ev(P, STEP, 36)
    x1 = await ev(P, '__tank.tanksNow[0].x')
    check(0.2 < x0 - x1 < 0.6, f'the hit knocks it back, away from the shooter ({x0 - x1:.2f} cells)')
    check(await ev(P, '__tank.hit(__tank.tanksNow[0], 1)') is True and not await ev(P, '__tank.tanksNow[0].alive'), 'the next hit kills it')
    await ev(P, LOCAL, ['heavy', 'classic']); await ev(P, STEP, 2)
    await ev(P, '__tank.hit(__tank.tanksNow[0], 1)'); await ev(P, STEP, int(7.5 * 120))
    check(await ev(P, '__tank.tanksNow[0].armor') == 0, 'the armour is still broken after 7.5 s')
    await ev(P, STEP, 70)
    check(await ev(P, '__tank.tanksNow[0].armor') == 1, '...and back after 8 s')
    await ev(P, LOCAL, ['heavy', 'classic']); await ev(P, STEP, 2)
    await ev(P, '(() => { const t = __tank.tanksNow[0]; t.shield = 2; })()')
    __ = await ev(P, '__tank.hit(__tank.tanksNow[0], 1)')
    check(await ev(P, '__tank.tanksNow[0].armor') == 1, 'a shield takes a hit before the armour does')

    # ---------- Cyber EMP ----------
    await ev(P, LOCAL, ['cyber', 'classic']); await ev(P, STEP, 2)
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])')
    st = await ev(P, '__tank.tanksNow[1].stun')
    check(abs(st - 0.8) < 0.02, f'an EMP holds an enemy 0.8 s ({st:.2f})')

    # ---------- Recon radar ----------
    await ev(P, LOCAL, ['recon', 'stealth']); await ev(P, STEP, 2)
    await ev(P, '__tank.useSkill(__tank.tanksNow[1])'); await ev(P, STEP, 2)       # the stealth tank cloaks
    check(await ev(P, '__tank.tanksNow[1].cloak') > 2, 'the stealth tank is cloaked')
    pos = await ev(P, '[__tank.tanksNow[1].x, __tank.tanksNow[1].y]')
    await ev(P, '__tank.useSkill(__tank.tanksNow[0])'); await ev(P, STEP, 2)
    check(await ev(P, '__tank.tanksNow[1].cloak') > 2, 'a radar scan no longer breaks a cloak')
    pg = await ev(P, '__tank.pings.map(p => [p.x, p.y, p.kind, p.owner])')
    check(any(k == 0 and o == 0 and abs(x - pos[0]) < 0.02 and abs(y - pos[1]) < 0.02 for x, y, k, o in pg), 'it marks where the enemy was at that moment')
    await ev(P, '(() => { const t = __tank.tanksNow[1]; t.x += 1; })()'); await ev(P, STEP, 2)
    pg2 = await ev(P, '__tank.pings.filter(p => p.kind === 0).map(p => p.x)')
    check(pg2 and abs(pg2[0] - pos[0]) < 0.02, 'the mark stays put when the enemy moves')
    check(await ev(P, '__tank.tanksNow[1].reveal || 0') == 0, 'and does not reveal the tank itself')
    await ev(P, '(n) => { for (let i = 0; i < n; i++) __tank.update(__tank.C.STEP); }', int(2.1 * 120))
    check(await ev(P, '__tank.pings.length') == 0, 'the marks fade after 2 s')

    # ---------- online: guests see the armour and their own radar marks ----------
    H = await page('host'); G = await page('guest')
    await ev(H, "__tank.setMySkin('heavy')"); await ev(G, "__tank.setMySkin('recon')")
    await ev(H, "__tank.setSettings(Object.assign({}, __tank.settings(), {maps:'classic', powerups:false, terrain:false, mode:'classic'}))")
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(4200)
    check(await ev(G, '__tank.state') == 'play', 'online match running')
    check(await ev(G, '__tank.tanksNow[0].armor') == 1, "a guest sees the host Heavy's armour")
    await G.keyboard.press('e'); await G.wait_for_timeout(500)
    gp = await ev(G, '__tank.pings.filter(p => p.kind === 0).length')
    hp = await ev(H, '__tank.pings.filter(p => p.owner === __tank.net.mySeat).length')     # the host keeps them all but draws only its own side's
    check(gp >= 1, f'the guest who scanned sees the mark ({gp})')
    check(hp == 0, 'the scanned host does not')

    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
