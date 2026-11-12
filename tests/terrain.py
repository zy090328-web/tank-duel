# Grass and water: water stops tanks but not shots; grass hides a tank from enemies (and computer
# tanks) unless they are close or it has just fired; a shared screen hides nobody; guests get the
# same terrain and see the same things. Needs the server on port 8790.
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# helpers run in the page: find cells by kind
FIND = r"""
(kind) => {
  const T = __tank, C = T.COLS, R = T.ROWS, W = T.walls, open = (c, r) => c >= 0 && r >= 0 && c < C && r < R && !W[r][c] && !T.water[r * C + c];
  for (let r = 1; r < R - 1; r++) for (let c = 0; c < C; c++) {
    const i = r * C + c;
    if (kind === 'water' && T.water[i] && open(c, r + 1) && open(c, r + 2) && !T.water[(r - 1) * C + c] ) return [c, r];
    if (kind === 'grass' && T.grass[i] && !W[r][c]) return [c, r];
  }
  return null;
}
"""
FAR = r"""
([cx, cy, d]) => { const T = __tank, W = T.walls; for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++)
  if (!W[r][c] && !T.water[r * T.COLS + c] && !T.grass[r * T.COLS + c] && Math.hypot(c + 0.5 - cx, r + 0.5 - cy) > d) return [c, r]; return null; }
"""

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)

    # ---------- menu ----------
    M = await page('menu', 820, 1180)
    check(await ev(M, '__tank.settings().terrain') is True, 'terrain is on by default')
    seen = []
    for _ in range(4):
      q = await ev(M, "(() => { const it = __tank.menuItems().find(it => it.kind === 'soft'); return [it.x + it.w / 2, it.y + it.h / 2, it.text]; })()")
      seen.append(q[2]); await M.mouse.click(q[0], q[1]); await M.wait_for_timeout(100)
    check(seen == ['Grass & water', 'All terrain', 'Plain map', 'Breakable walls'], f'map extras chip steps through four choices {seen}')
    await M.close()

    # ---------- two players on one screen: water blocks, shots cross, grass hides no one ----------
    L = await page('local', 820, 1180)
    await ev(L, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'dm', cpu: 0, soft: false, terrain: true, powerups: false, winScore: 7 }))")
    await ev(L, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()"); await L.wait_for_timeout(2400)
    w = None
    for k in range(12):
      await ev(L, f"__tank.showMap({k})")
      w = await ev(L, FIND, 'water')
      if w: break
    check(w is not None, f'a water cell with room below it {w}')
    c, r = w
    check(await ev(L, f"__tank.circleHitsWall({c} + 0.5, {r} + 0.5, 0.05) === false"), 'water is not a wall for shots')
    # tank 0 just below the water, facing up, driving up for a second
    await ev(L, f"(() => {{ const a = __tank.tanksNow[0]; a.x = {c} + 0.5; a.y = {r} + 1.5; a.angle = -Math.PI / 2; const b = __tank.tanksNow[1]; b.x = 1e3; }})()")
    await ev(L, "(([cx, cy]) => { const T = __tank, W = T.walls, b = T.tanksNow[1]; for (let r = 0; r < T.ROWS; r++) for (let c = 0; c < T.COLS; c++) if (!W[r][c] && !T.water[r * T.COLS + c] && Math.hypot(c + 0.5 - cx, r + 0.5 - cy) > 4) { b.x = c + 0.5; b.y = r + 0.5; return; } })", [c + 0.5, r + 0.5])
    await L.keyboard.down('ArrowUp'); await L.wait_for_timeout(1000); await L.keyboard.up('ArrowUp')
    y = await ev(L, '__tank.tanksNow[0].y')
    check(y >= r + 1 + 0.3 - 0.02, f'tank stopped at the water edge (y {y:.2f}, water ends at {r + 1})')
    await ev(L, "(() => { const a = __tank.tanksNow[0]; a.angle = -Math.PI / 2; a.cool = 0; __tank.fire(a); })()")
    await L.wait_for_timeout(250)
    by = await ev(L, "__tank.bullets.filter(b => b.owner === 0).map(b => b.y)")
    check(any(v < r + 0.5 for v in by), f'a shot flies over the water {by}')
    # grass hides nobody on a shared screen
    g = await ev(L, FIND, 'grass')
    await ev(L, f"(() => {{ const b = __tank.tanksNow[1]; b.x = {g[0]} + 0.5; b.y = {g[1]} + 0.5; b.reveal = 0; }})()")
    check(await ev(L, "__tank.concealed(__tank.tanksNow[1])") and await ev(L, "__tank.viewer()") == -1 and await ev(L, "__tank.seenBy(__tank.viewer(), __tank.tanksNow[1])"), 'shared screen: a tank in grass is still drawn')
    await L.screenshot(path='/tmp/terr/local.png')
    await L.close()

    # ---------- alone against a computer tank: grass hides from you and from it ----------
    S = await page('solo', 1180, 820)
    await ev(S, "__tank.setSettings(Object.assign({}, __tank.settings(), { game: 'dm', cpu: 1, soft: false, terrain: true, powerups: false, winScore: 7 }))")
    await ev(S, "(() => { __tank.goMenu(); __tank.beginFromMenu(); })()"); await S.wait_for_timeout(2400)
    g = await ev(S, FIND, 'grass')
    far = await ev(S, FAR, [g[0] + 0.5, g[1] + 0.5, 4])
    # the computer tank sits in grass; I am far away
    await ev(S, f"(() => {{ const T = __tank, [a, b] = T.tanksNow; b.x = {g[0]} + 0.5; b.y = {g[1]} + 0.5; b.reveal = 0; a.x = {far[0]} + 0.5; a.y = {far[1]} + 0.5; }})()")
    check(await ev(S, "__tank.viewer()") == 0 and not await ev(S, "__tank.seenBy(0, __tank.tanksNow[1])"), 'my screen does not show the computer tank in grass')
    await ev(S, "(() => { const [a, b] = __tank.tanksNow; a.x = b.x + 1.2; a.y = b.y; })()")
    check(await ev(S, "__tank.seenBy(0, __tank.tanksNow[1])"), 'right beside it, I see it')
    await ev(S, f"(() => {{ const [a, b] = __tank.tanksNow; a.x = {far[0]} + 0.5; a.y = {far[1]} + 0.5; b.reveal = 0.8; }})()")
    check(await ev(S, "__tank.seenBy(0, __tank.tanksNow[1])"), 'after it fires, I see it for a moment')
    # now I hide in the grass and the computer tank forgets me
    await ev(S, f"(() => {{ const T = __tank, [a, b] = T.tanksNow; a.x = {g[0]} + 0.5; a.y = {g[1]} + 0.5; a.reveal = 0; b.x = {far[0]} + 0.5; b.y = {far[1]} + 0.5; b.ai = null; }})()")
    lasts = []
    for _ in range(8):
      await ev(S, f"(() => {{ const a = __tank.tanksNow[0]; a.x = {g[0]} + 0.5; a.y = {g[1]} + 0.5; a.reveal = 0; }})()")
      await S.wait_for_timeout(200)
      d, last = await ev(S, "(() => { const [a, b] = __tank.tanksNow; return [Math.hypot(a.x - b.x, a.y - b.y), b.ai && b.ai.last ? 1 : 0]; })()")
      if d < 1.7: break
      lasts.append(last)
    check(lasts and not any(lasts), f'the computer tank never saw me while I hid {lasts}')
    await S.screenshot(path='/tmp/terr/solo.png')
    # it still plays: run 8 s of normal play
    await ev(S, "(() => { __tank.tanksNow[0].x = 1e-3; })()")
    await S.wait_for_timeout(300)
    for _ in range(8):
      await S.wait_for_timeout(1000)
    check(await ev(S, "__tank.state") in ('play', 'ending', 'result', 'matchEnd'), 'solo match keeps running with terrain')
    await S.close()

    # ---------- online: the guest gets the same terrain and the same hiding ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 7, game: 'dm', soft: false, terrain: true })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(500)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()')
    for _ in range(40):
      if await ev(G, '__tank.state') == 'play': break
      await G.wait_for_timeout(250)
    check(await ev(G, '__tank.settings().terrain') is True, 'guest knows terrain is on')
    same = await ev(H, '[...__tank.water].join("") + "/" + [...__tank.grass].join("")') == await ev(G, '[...__tank.water].join("") + "/" + [...__tank.grass].join("")')
    check(same and await ev(G, '__tank.water.reduce((a, b) => a + b, 0)') > 0, 'guest has the same water and grass as the host')
    g = await ev(H, FIND, 'grass'); far = await ev(H, FAR, [g[0] + 0.5, g[1] + 0.5, 4])
    await ev(H, f"(() => {{ const [a, b] = __tank.tanksNow; a.x = {g[0]} + 0.5; a.y = {g[1]} + 0.5; a.reveal = 0; b.x = {far[0]} + 0.5; b.y = {far[1]} + 0.5; }})()")
    await G.wait_for_timeout(500)
    check(await ev(G, '__tank.net.mySeat') == 1 and not await ev(G, "__tank.seenBy(__tank.viewer(), __tank.tanksNow[0])"), "guest's screen hides the host tank in grass")
    check(await ev(H, "__tank.seenBy(__tank.viewer(), __tank.tanksNow[0])"), 'host still sees its own tank')
    await G.screenshot(path='/tmp/terr/guest_hidden.png'); await H.screenshot(path='/tmp/terr/host_hiding.png')
    await ev(H, "(() => { const a = __tank.tanksNow[0]; a.cool = 0; a.fireQ = 0.15; })()")
    await G.wait_for_timeout(250)
    check(await ev(G, "__tank.tanksNow[0].reveal") > 0 and await ev(G, "__tank.seenBy(__tank.viewer(), __tank.tanksNow[0])"), 'firing gives the host away on the guest screen')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
