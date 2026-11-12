# Leaderboard: a server-run room and a Same Wi-Fi game report their results; unnamed players do not count;
# the board shows totals, the week's leaders and head-to-head records; results survive a server restart.
# Starts its own server on port 8796 with a fresh data folder.
import asyncio, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
from playwright.async_api import async_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8796; URL = f'http://127.0.0.1:{PORT}/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False
DATA = tempfile.mkdtemp()
def start():
  env = dict(os.environ, PORT=str(PORT), DATA_DIR=DATA, TEST_HOOKS='1')
  p = subprocess.Popen(['node', os.path.join(ROOT, 'server.js')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  for _ in range(50):
    try: urllib.request.urlopen(URL + 'healthz', timeout=1); return p
    except Exception: time.sleep(0.1)
  return p
def get_board(): return json.loads(urllib.request.urlopen(URL + 'board', timeout=3).read())
def post(path): urllib.request.urlopen(urllib.request.Request(URL + path, data=b'', method='POST'), timeout=3)

async def main():
  srv = start()
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.add_init_script(f"localStorage.setItem('tankduel-name', '{name}')")
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    async def until(p, js, secs):
      for _ in range(int(secs * 4)):
        if await ev(p, js): return True
        await p.wait_for_timeout(250)
      return False

    check(get_board()['total'] == 0, 'the board starts empty')
    # server-run room: Ann and Bo
    A = await page('Ann'); B = await page('Bo')
    await ev(A, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 3, game: 'classic', soft: false, terrain: false })")
    await ev(A, '__tank.net.goOnline()'); await A.wait_for_timeout(400)
    await ev(A, '__tank.net.startHosting()'); await A.wait_for_timeout(1500)
    code = await ev(A, '__tank.net.code')
    await ev(B, f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(1500)
    await ev(A, "__tank.net.sendCmd('start')")
    for _ in range(40):
      if await ev(B, '__tank.state') == 'matchEnd': break
      post('test/endround'); await B.wait_for_timeout(700)
    await B.wait_for_timeout(1500)
    b = get_board()
    names = sorted(p['name'] for p in b['players'])
    check(b['total'] == 1 and names == ['Ann', 'Bo'], f'server-run room recorded {b["total"]} match, players {names}')
    w = [p for p in b['players'] if p['wins'] == 1]
    check(len(w) == 1 and sum(p['games'] for p in b['players']) == 2, f'one winner, two games played {b["players"]}')
    await A.close(); await B.close()

    # Same Wi-Fi game: Cy hosts, Di joins, plus a computer tank (not counted)
    H = await page('Cy'); G = await page('Di', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 3, game: 'classic', soft: false, terrain: false })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(400)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, "__tank.applyMenu({ kind: 'bots', v: 1 })"); await H.wait_for_timeout(300)
    await ev(H, '__tank.net.hostStart()'); await H.wait_for_timeout(2600)
    check(await ev(H, '__tank.names') == ['Cy', 'Di', 'CPU 1'], f"host knows the names {await ev(H, '__tank.names')}")
    await ev(H, "(() => { const T = __tank; T.scores[0] = 3; T.state = 'result'; })()")
    check(await until(H, "__tank.state === 'matchEnd'", 6), 'Wi-Fi match ends')
    await H.wait_for_timeout(1000)
    b = get_board()
    cy = next((p for p in b['players'] if p['name'] == 'Cy'), None)
    check(b['total'] == 2 and cy and cy['wins'] == 1 and not any(p['name'].startswith('CPU') for p in b['players']), f'Wi-Fi host reported it; computer tanks are left out {b["players"]}')
    check(b['h2h'].get('cy', {}).get('di') == 1, f"head to head: Cy beat Di once {b['h2h']}")
    check(any(t['label'] == 'most wins' for t in b['titles']), f"this week's titles {b['titles']}")
    # the same result again is not counted twice
    await ev(H, '__tank.reportResult()'); await H.wait_for_timeout(500)
    check(get_board()['total'] == 2, 'a result sent twice counts once')
    await H.close(); await G.close()

    # players without names do not count
    X = await page(''); Y = await page('')
    await ev(X, '__tank.net.goOnline()'); await X.wait_for_timeout(400)
    await ev(X, '__tank.net.hostGame()'); await X.wait_for_timeout(1500)
    code = await ev(X, '__tank.net.code')
    await ev(Y, f'__tank.net.joinGame("{code}")'); await Y.wait_for_timeout(2500)
    await ev(X, '__tank.net.hostStart()'); await X.wait_for_timeout(2600)
    await ev(X, "(() => { const T = __tank; T.scores[0] = 5; T.state = 'result'; })()")
    await until(X, "__tank.state === 'matchEnd'", 6); await X.wait_for_timeout(800)
    check(get_board()['total'] == 2, 'a game between players without names is not recorded')
    await X.close(); await Y.close()

    # the board screen
    S = await page('Cy', 820, 1180)
    q = await ev(S, "(() => { const it = __tank.menuItems().find(it => it.kind === 'board'); return [it.x + it.w / 2, it.y + it.h / 2]; })()")
    await S.mouse.click(q[0], q[1])
    check(await until(S, "__tank.boardData && __tank.boardData.players.length === 4", 5), 'Leaderboard button on the title opens the board with 4 players')
    rows = await ev(S, "__tank.net.netItems().filter(it => it.kind === 'brow').map(it => [it.x + it.w / 2, it.y + it.h / 2])")
    await S.mouse.click(rows[0][0], rows[0][1]); await S.wait_for_timeout(200)
    await S.screenshot(path='/tmp/terr/board.png')
    await S.keyboard.press('Escape'); await S.wait_for_timeout(200)
    check(await ev(S, '__tank.state') == 'title', 'Escape goes back to the title')
    await br.close()
  # results survive a restart
  srv.terminate(); srv.wait(); time.sleep(1.8)
  srv = start()
  check(get_board()['total'] == 2, 'results are still there after the server restarts')
  srv.terminate(); shutil.rmtree(DATA, ignore_errors=True)
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
