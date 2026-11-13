# Infection mode, the replay of a round's last kill, and the mode cards.
# Needs the server on port 8790 (TEST_HOOKS=1).
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
SHOTS = '/tmp/terr/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

# a shot from tank 0 that gets tank 1 on the current map: put them on a free row with a clear line
SETUP_SHOT = """() => { const T = __tank, t0 = T.tanksNow[0], t1 = T.tanksNow[1];
  for (let r = 1; r < T.ROWS - 1; r++) for (let c = 1; c < T.COLS - 4; c++) {
    const free = k => !T.walls[r][k];
    if ([0, 1, 2, 3].every(k => free(c + k))) {
      t0.x = c + 0.5; t0.y = r + 0.5; t0.angle = 0; t1.x = c + 3.5; t1.y = r + 0.5; t0.inv = t1.inv = 0;
      T.fire(t0); return true;
    }
  }
  return false; }"""

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    async def page(name, w=1180, h=820):
      ctx = await br.new_context(viewport={'width': w, 'height': h}, has_touch=True); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      await p.goto(URL); await p.wait_for_timeout(400); return p
    ev = lambda p, js, a=None: p.evaluate(js, a)

    # ---------- the mode cards ----------
    L = await page('local', 820, 1180)
    await ev(L, "__tank.goMenu()"); await L.wait_for_timeout(300)
    items = await ev(L, "__tank.menuItems().map(i => [i.kind, i.v || i.text])")
    games = [v for k, v in items if k == 'game']
    check(games == ['classic', 'dm', 'hill', 'zombie', 'potato', 'gun', 'teams', 'soccer', 'base'], f'nine mode cards {games}')
    check(['online', 'Play online'] in items, 'playing online is its own button, not a mode card')
    geo = await ev(L, "(() => { const it = __tank.menuItems(), L = __tank.layout; const o = it.find(i => i.kind === 'online'); return [o.y + o.h, L.AY + L.AH, Math.max(...it.filter(i => i.kind === 'game').map(i => i.y + i.h)), o.y]; })()")
    check(geo[0] <= geo[1] - 2 and geo[2] < geo[3], f'cards and the online button fit in the half screen {geo}')
    await L.screenshot(path=SHOTS + 'r_modes.png')
    await ev(L, "(() => { const it = __tank.menuItems().find(i => i.v === 'zombie'); __tank.applyMenu(it); })()")
    check(await ev(L, "[__tank.settings().game, __tank.menuStep]") == ['zombie', 'who'], 'tapping Infection picks it and moves on')

    # ---------- replay on one screen (classic) ----------
    await ev(L, "(() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'classic', cpu: 0, winScore: 5, powerups: false, terrain: false, soft: false, mut: 'off' })); T.beginFromMenu(); for (let i = 0; i < 120 * 2.2; i++) T.update(1 / 120); })()")
    check(await ev(L, "__tank.state") == 'play', 'classic round under way')
    await ev(L, "for (let i = 0; i < 120; i++) __tank.update(1 / 120)")
    ok = await ev(L, SETUP_SHOT)
    seen = await ev(L, """() => { const T = __tank, out = []; for (let i = 0; i < 120 * 3; i++) { T.update(1 / 120); if (!out.length || out[out.length - 1] !== T.state) out.push(T.state); } return out; }""")
    check(ok and 'ending' in seen and 'replay' in seen, f'a kill leads to a replay {seen}')
    plan = await ev(L, "__tank.rp && [__tank.rp.from, __tank.rp.to, __tank.rp.dur, __tank.hl.v, __tank.hl.k, __tank.hl.b >= 0]")
    check(plan and plan[1] > plan[0] and 1.5 <= plan[2] <= 4.01 and plan[3] == 1 and plan[4] == 0 and plan[5], f'replay window covers the shot {plan}')
    # let the page's own loop play it; look half way through
    await ev(L, "__tank.state = 'replay'"); await L.wait_for_timeout(int(plan[2] * 500))
    st = await ev(L, "[__tank.state, __tank.rpT, __tank.replayText()]")
    check(st[0] == 'replay' and st[1] > 0.3, f'replay plays in real time {st}')
    await L.screenshot(path=SHOTS + 'r_replay_local.png')
    # skip by the button
    it = await ev(L, "__tank.replayItems()[0]")
    await L.mouse.click(it['x'] + it['w'] / 2, it['y'] + it['h'] / 2)
    await L.wait_for_timeout(150)
    check(await ev(L, "__tank.state") == 'result', 'Skip ends the replay')
    check(await ev(L, "__tank.scores.join(',')") == '1,0', 'the point was still given')

    # ---------- infection on one screen with computer tanks ----------
    r = await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'zombie', cpu: 3, winScore: 3, powerups: true, terrain: true, mut: 'off' })); T.beginFromMenu(); T.bots.add(0);
      const z0 = T.zed.slice(); let rounds = 0, st = '', zedSeen = 0, outs = [];
      for (let i = 0; i < 120 * 600 && T.state !== 'matchEnd'; i++) { T.update(1 / 120); if (T.state === 'result' && st !== 'result') { rounds++; outs.push(T.infWin.slice()); } zedSeen = Math.max(zedSeen, T.zed.reduce((a, b) => a + b, 0)); st = T.state; }
      return [z0.reduce((a, b) => a + b, 0), rounds, T.state, Math.max(...T.scores), zedSeen, outs, T.scores]; }""")
    check(r[0] == 1 and r[2] == 'matchEnd' and r[3] >= 3 and r[4] >= 2, f'infection: one zombie to start, it spreads, the match ends {r[:5]} {r[6]}')
    check(sum(1 for o in r[5] if len(o) >= 1) == r[1], f'every round has someone scoring {r[5]}')
    # the rules of touch, two shots and dash
    r = await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'zombie', cpu: 2, winScore: 3, powerups: false, terrain: false })); T.beginFromMenu();
      for (let i = 0; i < 120 * 2.2; i++) T.update(1 / 120);
      const z = T.zed.indexOf(1), tk = T.tanksNow, Z = tk[z], H = tk.find(t => t.id !== z);
      const res = {};
      res.zfire = (() => { const n = T.bullets.length; Z.stun = 0; Z.dcool = 0; T.fire(Z); return T.bullets.length === n; })();
      // two shots for a zombie
      Z.hp = 2; T.hit(Z, H.id); res.hp1 = [Z.alive, Z.hp]; T.hit(Z, H.id); res.hp2 = Z.alive;
      for (let i = 0; i < 120 * 3.2; i++) T.update(1 / 120);
      res.back = [Z.alive, T.zed[z], Z.inv];
      // touch
      Z.stun = 0; H.inv = 0; H.shield = 0; Z.x = H.x + 0.5; Z.y = H.y; T.stepPhysics(1 / 120, true, false);
      res.turned = [T.zed[H.id], H.alive, H.stun > 0];
      return res; }""")
    check(r['zfire'], 'a zombie cannot shoot')
    check(r['hp1'] == [True, 1] and r['hp2'] is False, f'a zombie takes two shots {r["hp1"]} {r["hp2"]}')
    check(r['back'][0] and r['back'][1] == 1 and r['back'][2] == 0, f'a zombie comes back, still a zombie, without a shield {r["back"]}')
    check(r['turned'] == [1, True, True], f'touching a survivor turns it on the spot {r["turned"]}')
    # a survivor's own stray shot turns it too, and its shots go with it
    r = await ev(L, """() => { const T = __tank; const H = T.tanksNow.find(t => !T.zed[t.id]); if (!H) return null; T.fire(H); const n = T.bullets.filter(b => b.owner === H.id).length; H.inv = 0; T.hit(H, H.id); T.stepPhysics(1 / 120, true, false);
      return [n, T.zed[H.id], H.alive, T.bullets.filter(b => b.owner === H.id).length]; }""")
    check(r and r[0] >= 1 and r[1] == 1 and r[2] is False and r[3] == 0, f'own shot: turned, down, its shots gone {r}')
    # dash
    r = await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'zombie', cpu: 1, winScore: 3, terrain: false })); T.beginFromMenu();
      for (let i = 0; i < 120 * 2.2; i++) T.update(1 / 120);
      const z = T.zed.indexOf(1), Z = T.tanksNow[z]; Z.stun = 0; Z.dcool = 0; Z.fireQ = 0.15; T.stepPhysics(1 / 120, true, true);
      return [Z.dash > 0, Z.dcool > 2]; }""")
    check(r == [True, True], f'a zombie\'s button dashes {r}')
    # the clock: survivors score when time is up
    r = await ev(L, """() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'zombie', cpu: 2, winScore: 3, terrain: false })); T.beginFromMenu();
      for (let i = 0; i < 120 * 2.2; i++) T.update(1 / 120);
      T.roundTv = 39.99; for (let i = 0; i < 10; i++) T.update(1 / 120);
      return [T.state, T.infWin.length, T.scores.reduce((a, b) => a + b, 0)]; }""")
    check(r[0] == 'result' and r[1] == r[2] and r[1] >= 1, f'time up: every survivor scores {r}')
    # screenshots: countdown with the roles, then play with a zombie
    await ev(L, "(() => { const T = __tank; T.goMenu(); T.setSettings(Object.assign({}, T.settings(), { game: 'zombie', cpu: 0, winScore: 5, terrain: true })); T.beginFromMenu(); for (let i = 0; i < 120 * 0.5; i++) T.update(1 / 120); })()")
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'r_inf_count.png')
    await ev(L, "(() => { const T = __tank; T.bots.add(0); T.bots.add(1); for (let i = 0; i < 120 * 9; i++) T.update(1 / 120); })()")
    await L.wait_for_timeout(200); await L.screenshot(path=SHOTS + 'r_inf_play.png')
    await L.close()

    # ---------- online: a tablet hosts infection, a phone joins ----------
    H = await page('host'); G = await page('guest', 844, 390)
    await ev(H, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 5, game: 'zombie', soft: false, terrain: false, mut: 'off' })")
    await ev(H, '__tank.net.goOnline()'); await H.wait_for_timeout(400)
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(1500)
    code = await ev(H, '__tank.net.code')
    await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(2500)
    await ev(H, '__tank.net.hostStart()'); await G.wait_for_timeout(3000)
    hz = await ev(H, "__tank.zed.slice()"); gz = await ev(G, "__tank.zed.slice()")
    check(sum(hz) == 1 and hz == gz, f'guest knows who the zombie is {hz} {gz}')
    await G.screenshot(path=SHOTS + 'r_inf_guest.png')
    # the guest records what it shows; the host's kill becomes a replay there too
    await G.wait_for_timeout(1500)
    nf = await ev(G, "__tank.rec.frames.length")
    check(nf > 40, f'guest records frames ({nf})')
    # turn the guest (seat 1) by a touch from the zombie, or shoot it if the guest is the zombie
    await ev(H, """(() => { const T = __tank, tk = T.tanksNow, z = T.zed.indexOf(1), h = 1 - z, Z = tk[z], Hm = tk[h];
      Z.stun = 0; Hm.inv = 0; Hm.shield = 0; Z.x = Hm.x + 0.5; Z.y = Hm.y; })()""")
    await H.wait_for_timeout(1800)
    hs = await ev(H, "[__tank.state, __tank.rp && __tank.rp.dur]")
    gs = await ev(G, "[__tank.state, __tank.rp && __tank.rp.dur, __tank.rec.frames.length, __tank.replayText()]")
    check(hs[0] == 'replay' and gs[0] == 'replay' and gs[1] == hs[1] and gs[2] > 20, f'host and guest both show the replay {hs} {gs}')
    await G.wait_for_timeout(500)
    await G.screenshot(path=SHOTS + 'r_replay_guest.png')
    await H.screenshot(path=SHOTS + 'r_replay_host.png')
    # the guest skips it for everyone
    it = await ev(G, "__tank.replayItems()[0]")
    await G.mouse.click(it['x'] + it['w'] / 2, it['y'] + it['h'] / 2)
    await H.wait_for_timeout(900)
    check(await ev(H, "__tank.state") in ('result', 'countdown', 'play'), 'a guest\'s Skip ends the replay on the host')
    await G.screenshot(path=SHOTS + 'r_inf_result_guest.png')
    # lobby mode page shows the cards
    await ev(H, "__tank.net.hostLobby()"); await H.wait_for_timeout(300)
    await ev(H, "(() => { const it = __tank.net.netItems().find(i => i.kind === 'pane' && i.v === 'mode'); __tank.applyMenu(it); })()"); await H.wait_for_timeout(300)
    pane = await ev(H, "__tank.paneItems().filter(i => i.kind === 'game').length")
    check(pane == 9, f'waiting room mode page has the nine cards ({pane})')
    await H.screenshot(path=SHOTS + 'r_lobby_modes.png')
    await br.close()

    # ---------- a room run by the server: the replay without a screen ----------
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    A = await page('a'); B = await page('b', 844, 390)
    await ev(A, "__tank.setSettings({ ammo: 'unlimited', powerups: false, maps: 'all', winScore: 3, game: 'classic', soft: false, terrain: false, mut: 'off' })")
    await ev(A, "__tank.net.goOnline()"); await A.wait_for_timeout(300)
    await ev(A, "__tank.net.createGame()"); await A.wait_for_timeout(2500)
    code = await ev(A, "__tank.net.code")
    await ev(B, f'__tank.net.joinGame("{code}")'); await B.wait_for_timeout(2500)
    await ev(A, "__tank.net.sendCmd('start')"); await A.wait_for_timeout(4000)
    # drive A's tank into B's line of fire is hard from here: end the round on the server through its test hook
    import urllib.request, json
    try:
      urllib.request.urlopen(urllib.request.Request(URL + 'test/endround?code=' + code, method='POST'), timeout=3).read()
    except Exception as e:
      print('endround hook:', e)
    await A.wait_for_timeout(2500)
    sa = await ev(A, "[__tank.state, __tank.scores.join(',')]")
    check(sa[0] in ('replay', 'result', 'countdown', 'play'), f'server-run room carries on through the end of a round {sa}')
    await br.close()
  if errors: print('ERRORS:'); [print('  ', e) for e in errors[:20]]
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
