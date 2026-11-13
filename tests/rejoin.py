# Dropping out and coming back: a guest whose line drops reconnects by itself to its own seat; a guest who closed
# the page can rejoin from the online screen; a tablet host whose line drops takes its room back; a server-run
# room stays open after everyone dropped out; leaving on purpose frees the seat at once.
# Needs the server on port 8790 (TEST_HOOKS=1).
import asyncio, sys, json, urllib.request
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
SHOTS = '/tmp/terr/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False
def rooms():
  return json.loads(urllib.request.urlopen(URL + 'relay.json', timeout=3).read())['rooms']

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def context(w=1180, h=820):
      return await br.new_context(viewport={'width': w, 'height': h}, has_touch=True)
    async def page(ctx, name):
      p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)
    async def until(p, js, ms=15000):
      for _ in range(ms // 250):
        if await ev(p, js): return True
        await p.wait_for_timeout(250)
      return False

    # ---------- a tablet-hosted room ----------
    hc = await context(); H = await page(hc, 'host')
    gc = await context(844, 390); G = await page(gc, 'guest')
    kc = await context(844, 390)
    await kc.add_init_script("window.RTCPeerConnection = undefined;")     # this guest has no direct link: everything goes through the server
    K = await page(kc, 'guest2')
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 7, game: 'dm', soft: false, terrain: false, mut: 'off' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(300)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await ev(K, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    gid = await ev(G, '__tank.myId'); key = await ev(G, '__tank.myKey')
    check(gid == 'k' + key, f'a guest\'s id comes from the key its device keeps ({gid})')
    await ev(H, '__tank.net.hostStart()'); await G.wait_for_timeout(3000)
    seat = await ev(G, '__tank.net.mySeat')
    check(seat >= 1 and await ev(G, '__tank.state') == 'play', f'guest plays in seat {seat}')

    # 1. the guest's line drops (as when the browser goes to the background): it comes back by itself
    await ev(G, '__tank.peer.ws.close()')
    away = await until(H, f"(() => {{ const g = __tank.net.guests.get('{gid}'); return !!g && !!g.away; }})()", 6000)
    check(away, 'the host keeps the seat and marks the guest away')
    back = await until(H, f"(() => {{ const g = __tank.net.guests.get('{gid}'); return !!g && !g.away; }})()", 15000)
    st = await ev(G, "[__tank.myId, __tank.net.mySeat, __tank.state, __tank.awaySince]")
    check(back and st[0] == gid and st[1] == seat and st[2] == 'play' and st[3] == 0, f'the guest reconnected by itself to the same seat {st}')
    # its stick works again
    await ev(G, "(() => { __tank.players[0].stickId = 9; __tank.players[0].vx = 0; __tank.players[0].vy = -0.9; })()")
    await G.wait_for_timeout(800)
    inp = await ev(H, f"__tank.net.guests.get('{gid}').inp")
    check(inp[2] > 0.5, f'the host gets its stick again {inp}')
    await ev(G, "(() => { __tank.players[0].stickId = null; __tank.players[0].vx = 0; __tank.players[0].vy = 0; })()")

    # 1b. the same for a guest with no direct link
    kid0 = await ev(K, '__tank.myId'); kseat = await ev(K, '__tank.net.mySeat')
    await ev(K, "(() => { window.__p0 = __tank.peer; __tank.peer.ws.close(); })()")
    down = await until(K, '__tank.peer !== window.__p0', 3000)                # it opened a new line
    ok = await until(K, f"__tank.myId === '{kid0}' && __tank.net.mySeat === {kseat} && __tank.awaySince === 0 && __tank.peer && !__tank.peer.dead && __tank.state === 'play'", 15000)
    check(down and ok, f'a guest without a direct link notices its line dropped and comes back to seat {kseat} ' + str(await ev(K, "[__tank.myId, __tank.net.mySeat, __tank.awaySince, __tank.state, !!__tank.peer && __tank.peer.dead]")))
    await K.screenshot(path=SHOTS + 'rj_k.png')

    # 2. the guest closes the page and opens it again: the online screen offers the game back
    await G.close()
    away = await until(H, f"(() => {{ const g = __tank.net.guests.get('{gid}'); return !!g && !!g.away; }})()", 12000)
    tk = await ev(H, f"__tank.tanksNow[{seat}].gone")
    check(away and not tk, f'closing the page: seat kept, tank still in the match ({away}, gone={tk})')
    G = await page(gc, 'guest-again')
    await ev(G, '__tank.net.goOnline()'); await G.wait_for_timeout(500)
    items = await ev(G, "__tank.net.netItems().map(i => [i.kind, i.text])")
    rj = [t for k, t in items if k == 'rejoin']
    check(rj == [f'Rejoin game {code}'], f'the online screen offers the game back {rj}')
    await G.screenshot(path=SHOTS + 'rj_online.png')
    await ev(G, "(() => { const it = __tank.net.netItems().find(i => i.kind === 'rejoin'); __tank.applyMenu(it); })()")
    ok = await until(G, f"__tank.net.mySeat === {seat} && __tank.state === 'play'", 10000)
    check(ok, 'rejoined into the same seat')

    # 3. the host's line drops: guests wait, the host takes its room back, play goes on
    await ev(H, '__tank.peer.ws.close()')
    await H.wait_for_timeout(300)
    back = await until(H, "!!__tank.peer && !__tank.peer.dead && __tank.awaySince === 0 && __tank.net.guests.size === 2 && [...__tank.net.guests.values()].every(g => !g.away)", 20000)
    gs = await ev(G, "[__tank.state, __tank.net.mySeat]"); ks = await ev(K, "__tank.state")
    check(back and gs == ['play', seat] and ks == 'play', f'host took its room back; guests still playing {gs} {ks}')

    # 4. leaving on purpose frees the seat at once
    kid = await ev(K, '__tank.myId')
    await ev(K, "__tank.goMenu()")
    gone = await until(H, f"!__tank.net.guests.has('{kid}')", 4000)
    check(gone, 'a guest who leaves on purpose is dropped at once')
    await hc.close(); await gc.close(); await kc.close()

    # 5. a room run by the server stays open after everyone dropped out, and takes them back
    ac = await context(); A = await page(ac, 'a')
    bc = await context(844, 390); B = await page(bc, 'b')
    await ev(A, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 7, game: 'dm', soft: false, terrain: false, mut: 'off' })")
    await ev(A, "__tank.net.goOnline()"); await A.wait_for_timeout(300)
    await ev(A, "__tank.net.createGame()"); await A.wait_for_timeout(2500)
    code = await ev(A, "__tank.net.code")
    await ev(B, f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(2500)
    await ev(A, "__tank.net.sendCmd('start')"); await A.wait_for_timeout(3500)
    sa = await ev(A, "__tank.net.mySeat"); sb = await ev(B, "__tank.net.mySeat")
    n0 = rooms()
    await A.close(); await B.close()
    await asyncio.sleep(20)
    n1 = rooms()
    check(n1 == n0 and n0 >= 1, f'20 s after everyone dropped out the room is still there ({n0} -> {n1})')
    A = await page(ac, 'a-again')
    await ev(A, "__tank.net.goOnline()"); await A.wait_for_timeout(300)
    await ev(A, "(() => { const it = __tank.net.netItems().find(i => i.kind === 'rejoin'); __tank.applyMenu(it); })()")
    ok = await until(A, f"__tank.net.mySeat === {sa} && ['play', 'ending', 'result', 'replay', 'matchEnd', 'countdown'].includes(__tank.state)", 10000)
    check(ok, f'back in the server-run room, same seat {sa}')
    await A.screenshot(path=SHOTS + 'rj_back.png')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
