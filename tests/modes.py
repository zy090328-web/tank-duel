# New game modes, computer tanks, teams, names and the match-end table: one screen, a server-run room and a tablet-hosted game.
# Needs the game server: cd tank-duel && PORT=8790 node server.js
import asyncio, os, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots', '')
os.makedirs(OUT, exist_ok=True)
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js: p.evaluate(js)
    async def tap(p, find, items='__tank.net.netItems()'):
      # a real tap on a chip, found by a JS test on the item
      q = await ev(p, f"(() => {{ const it = {items}.find(it => {find}); return it ? [it.x + it.w / 2, it.y + it.h / 2] : null; }})()")
      assert q, 'no chip: ' + find
      await p.mouse.click(q[0], q[1]); await p.wait_for_timeout(120)
    async def set_name(p, name):
      await tap(p, "it.kind === 'name'")
      await p.fill('#nameinput', name); await p.click('#nameok'); await p.wait_for_timeout(100)
    async def wait_state(p, st, secs):
      for _ in range(int(secs * 4)):
        if await ev(p, '__tank.state') == st: return True
        await p.wait_for_timeout(250)
      return False

    # ---------- one screen: menu taps, solo against computer tanks ----------
    S = await page('solo', 820, 1180)
    await tap(S, "it.kind === 'game' && it.v === 'dm'", '__tank.menuItems()')
    await tap(S, "it.kind === 'cpu' && it.v === 2", '__tank.menuItems()')
    await tap(S, "it.kind === 'soft' && it.v === 1", '__tank.menuItems()')
    await tap(S, "it.kind === 'win' && it.v === 7", '__tank.menuItems()')
    st = await ev(S, '__tank.settings()')
    check(st['game'] == 'dm' and st['cpu'] == 2 and st['soft'] is True and st['terrain'] is False and st['winScore'] == 7, f'menu steps set mode, CPU, walls and length {st}')
    await ev(S, "__tank.setSettings(Object.assign({}, __tank.settings(), { winScore: 3 }))")
    await tap(S, "it.kind === 'start'", '__tank.menuItems()')
    await S.wait_for_timeout(2600)
    check(await ev(S, '__tank.state') == 'play' and await ev(S, '__tank.NP') == 3 and await ev(S, '__tank.solo'), 'solo match: 1 player + 2 computer tanks')
    check(await ev(S, '[...__tank.bots].join()') == '1,2', 'seats 1 and 2 are computer tanks')
    a = await ev(S, '__tank.tanksNow.map(t => [t.x, t.y])'); await S.wait_for_timeout(1500)
    b = await ev(S, '__tank.tanksNow.map(t => [t.x, t.y])')
    moved = [abs(a[i][0] - b[i][0]) + abs(a[i][1] - b[i][1]) > 0.2 for i in (1, 2)]
    check(any(moved), f'computer tanks drive {moved}')
    # deathmatch rules: a kill is a point, destroying yourself costs one, and the tank comes back
    await ev(S, "(() => { const T = __tank; T.scores[0] = 2; T.kill(T.tanksNow[1], 0); T.kill(T.tanksNow[0], 0); })()")
    sc = await ev(S, '__tank.scores'); t1 = await ev(S, '[__tank.tanksNow[1].alive, __tank.tanksNow[1].respawn]')
    check(sc[0] == 2 and not t1[0] and t1[1] > 0, f'kill +1, own goal -1, tank waits to come back {sc} {t1}')
    await S.wait_for_timeout(2600)
    t1 = await ev(S, '[__tank.tanksNow[1].alive, __tank.tanksNow[1].shield > 0 || __tank.tanksNow[1].alive]')
    check(t1[0], 'destroyed tank came back')
    check(await ev(S, '__tank.state') == 'play', 'match goes on after kills')
    check(await wait_state(S, 'matchEnd', 150), 'solo deathmatch reaches its end')
    sc = await ev(S, '__tank.scores'); check(max(sc) >= 5, f'somebody reached 5 kills {sc}')
    await S.close()

    # two people on one screen still works in every mode
    for game in ['teams', 'hill']:
      L = await page('local-' + game, 820, 1180)
      await ev(L, f"__tank.setSettings(Object.assign({{}}, __tank.settings(), {{ game: '{game}', cpu: 0, winScore: 3 }}))")
      await L.keyboard.press('Enter'); await L.wait_for_timeout(2500)
      check(await ev(L, '__tank.state') == 'play' and await ev(L, '__tank.NP') == 2 and not await ev(L, '__tank.solo'), f'two players on one screen, {game}')
      if game == 'hill':
        await ev(L, "(() => { const T = __tank, t = T.tanksNow[1]; t.x = T.COLS / 2; t.y = T.ROWS / 2; })()")
        await L.wait_for_timeout(2300)
        sc = await ev(L, '__tank.scores'); check(sc[1] >= 1 and sc[0] == 0 and await ev(L, '__tank.hillHolder') == 1, f'holding the hill scores {sc}')
        await L.screenshot(path=OUT + 'local_hill.png')
      else:
        await ev(L, "__tank.kill(__tank.tanksNow[1], 0)"); await L.wait_for_timeout(1500)
        if await ev(L, '__tank.state') == 'replay': await ev(L, '__tank.skipReplay()')   # the replay of the kill comes first
        await L.wait_for_timeout(300)
        check(await ev(L, '__tank.scores[0]') == 1, 'teams with 2 tanks plays as classic')
      await L.close()

    # ---------- server-run room: names, teams, computer tanks ----------
    A = await page('ann'); B = await page('bo')
    await ev(A, "__tank.setSettings({ ammo: 'unlimited', powerups: true, maps: 'all', winScore: 3, game: 'teams', soft: true })")
    await ev(A, '__tank.net.goOnline()'); await A.wait_for_timeout(600)
    await set_name(A, 'Ann')
    check(await ev(A, '__tank.myName') == 'Ann', 'name typed into the name box is kept')
    await A.screenshot(path=OUT + 'online_screen.png')
    await ev(A, '__tank.net.startHosting()'); await A.wait_for_timeout(1500)
    code = await ev(A, '__tank.net.code')
    check(len(code or '') == 4 and await ev(A, '__tank.net.isLeader'), f'room {code} created, Ann leads')
    await ev(B, '__tank.net.goOnline()'); await B.wait_for_timeout(400); await set_name(B, 'Bo')
    await ev(B, f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(1500)
    check(await ev(B, '__tank.settings().game') == 'teams' and await ev(B, '__tank.settings().soft'), "leader's mode and walls reached the room")
    await tap(A, "it.kind === 'bots' && it.v === 1"); await tap(A, "it.kind === 'bots' && it.v === 1")
    await A.wait_for_timeout(700)
    nm = await ev(B, '__tank.lobby.names'); tm = await ev(B, '__tank.lobby.teams')
    check(nm == ['Ann', 'Bo', 'CPU 1', 'CPU 2'], f'everyone sees the names {nm}')
    check(tm == [0, 1, 0, 1], f'teams fill evenly {tm}')
    # Bo (not the leader) swaps his own team by tapping his chip; he cannot change Ann's
    await ev(B, "__tank.net.sendCmd('team', 0)"); await ev(B, "__tank.net.sendCmd('bots', 0)")
    await tap(B, "it.kind === 'team' && it.v === 1"); await B.wait_for_timeout(700)
    tm = await ev(A, '__tank.lobby.teams')
    check(tm == [0, 0, 0, 1] and len(await ev(A, '__tank.lobby.seats')) == 4, f'a guest swaps only its own team {tm}')
    await tap(A, "it.kind === 'team' && it.v === 2"); await A.wait_for_timeout(600)       # leader moves CPU 1 to Blue
    tm = await ev(B, '__tank.lobby.teams'); check(tm == [0, 0, 1, 1], f'leader moves a computer tank {tm}')
    await A.screenshot(path=OUT + 'lobby_leader.png'); await B.screenshot(path=OUT + 'lobby_guest.png')
    await tap(A, "it.kind === 'start'")
    check(await wait_state(B, 'play', 8), 'team match starts')
    check(await ev(B, '__tank.NP') == 4 and await ev(B, '__tank.teamOf') == [0, 0, 1, 1] and await ev(B, '__tank.names') == ['Ann', 'Bo', 'CPU 1', 'CPU 2'], 'guest knows teams and names in the match')
    check(len(await ev(B, '__tank.scores')) == 2, 'score is kept per team')
    a = await ev(B, '__tank.tanksNow.map(t => [t.x, t.y])'); await B.wait_for_timeout(2000)
    b = await ev(B, '__tank.tanksNow.map(t => [t.x, t.y])')
    check(any(abs(a[i][0] - b[i][0]) + abs(a[i][1] - b[i][1]) > 0.2 for i in (2, 3)), 'computer tanks drive on the server')
    await B.screenshot(path=OUT + 'teams_play_guest.png')
    check(await wait_state(B, 'matchEnd', 240), 'team match reaches its end')
    await B.wait_for_timeout(1600)
    st = await ev(B, '__tank.stats'); sc = await ev(B, '__tank.scores')
    check(len(st) == 4 and sum(v['d'] for v in st) > 0 and max(sc) == 3, f'match-end table arrives {sc} {st}')
    await B.screenshot(path=OUT + 'teams_end_guest.png'); await A.screenshot(path=OUT + 'teams_end_leader.png')
    await tap(A, "it.kind === 'lobby'", '__tank.endItems()'); await A.wait_for_timeout(900)
    check(await ev(B, '__tank.state') == 'guestWait' and len(await ev(B, '__tank.lobby.seats')) == 4, 'back in the waiting room with the computer tanks')
    await tap(A, "it.kind === 'bots' && it.v === -1"); await A.wait_for_timeout(600)
    check(len(await ev(B, '__tank.lobby.seats')) == 3, 'a computer tank can be removed')
    await A.close(); await B.close()

    # ---------- Same Wi-Fi game (this tablet hosts): hill, breakable walls, one computer tank ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'reload', powerups: false, maps: 'all', winScore: 3, game: 'hill', soft: true })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(500)
    await tap(H, "it.kind === 'lan'"); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await tap(H, "it.kind === 'bots' && it.v === 1"); await H.wait_for_timeout(600)
    check(await ev(G, '__tank.lobby.seats.length') == 3, 'host + guest + computer tank seated')
    await H.screenshot(path=OUT + 'lobby_host_hill.png'); await G.screenshot(path=OUT + 'lobby_guest_phone.png')
    await tap(H, "it.kind === 'start'")
    check(await wait_state(G, 'play', 8), 'hill match starts')
    print('   direct links:', await ev(H, '__tank.net.direct'))
    # a wall broken on the host breaks on the guest
    await ev(H, "(() => { const T = __tank; const i = T.soft.indexOf(1); if (i >= 0) T.breakWall(i); })()")
    await G.wait_for_timeout(500)
    wh = await ev(H, '__tank.walls.map(r => r.map(v => v ? 1 : 0).join("")).join("/")'); wg = await ev(G, '__tank.walls.map(r => r.map(v => v ? 1 : 0).join("")).join("/")')
    check(await ev(G, '__tank.broken.length') >= 1 and wh == wg, 'broken wall reaches the guest; maps agree')
    # the guest's tank is destroyed and comes back
    await ev(H, "__tank.kill(__tank.tanksNow[1], 0)"); await G.wait_for_timeout(400)
    check(not await ev(G, '__tank.tanksNow[1].alive') and await ev(G, '__tank.tanksNow[1].respawn') > 0, 'guest sees its tank waiting to come back')
    await G.screenshot(path=OUT + 'hill_guest_dead.png')
    await G.wait_for_timeout(2600)
    check(await ev(G, '__tank.tanksNow[1].alive'), 'guest tank is back')
    # host parks on the hill
    for _ in range(3):
      await ev(H, "(() => { const T = __tank, t = T.tanksNow[0]; t.x = T.COLS / 2; t.y = T.ROWS / 2; })()"); await H.wait_for_timeout(700)
    sc = await ev(G, '__tank.scores'); print('   hill scores on guest', sc, 'holder', await ev(G, '__tank.hillHolder'))
    check(sum(sc) >= 1, 'hill seconds are counted and reach the guest')
    await G.screenshot(path=OUT + 'hill_play_guest.png'); await H.screenshot(path=OUT + 'hill_play_host.png')
    check(await wait_state(G, 'matchEnd', 200), 'hill match reaches its end')
    await G.wait_for_timeout(1500)
    sc = await ev(G, '__tank.scores'); check(max(sc) >= 20, f'winner held the hill for 20 s {sc}')
    await G.screenshot(path=OUT + 'hill_end_guest.png')
    await tap(H, "it.kind === 'rematch'", '__tank.endItems()')
    check(await wait_state(G, 'play', 8), 'rematch starts')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
