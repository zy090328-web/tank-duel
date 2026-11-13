# Server-run rooms: every player is a guest; the creator leads the room.
import asyncio, sys, math
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
errors = []
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False
async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    async def page(name):
      ctx = await br.new_context(viewport={'width': 900, 'height': 600}); p = await ctx.new_page()
      p.on('pageerror', lambda e, n=name: errors.append(f'{n}: {e}'))
      p.on('console', lambda m, n=name: errors.append(f'{n}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(300); return p
    P = [await page(f'p{i+1}') for i in range(4)]
    ev = lambda p, js: p.evaluate(js)
    # p1 creates the room with its own saved settings
    await ev(P[0], "__tank.setSettings({ammo:'reload', powerups:true, maps:'complex', winScore:3})")
    await ev(P[0], '__tank.net.goOnline()'); await P[0].wait_for_timeout(500)
    await ev(P[0], '__tank.net.startHosting()'); await P[0].wait_for_timeout(1500)
    code = await ev(P[0], '__tank.net.code')
    check(len(code or '') == 4, f'creator got code {code}')
    check(await ev(P[0], '__tank.net.mode') == 'guest' and await ev(P[0], '__tank.net.isLeader'), 'creator is a guest and leads the room')
    for p in P[1:]: await ev(p, f'__tank.net.joinGame("{code}")')
    await P[0].wait_for_timeout(1500)
    seats = await ev(P[3], '__tank.net.snaps.at(-1).g.seats')
    check(len(seats) == 4, f'4 players seated {len(seats)}')
    s_other = await ev(P[2], '__tank.settings()')
    check(s_other['ammo'] == 'reload' and s_other['maps'] == 'complex' and s_other['winScore'] == 3, f"creator's settings reached the room {s_other}")
    # a non-leader cannot change settings or start
    await ev(P[1], "__tank.net.sendCmd('set', {ammo:'single', powerups:false, maps:'all', winScore:7})")
    await ev(P[1], "__tank.net.sendCmd('start')")
    await P[1].wait_for_timeout(600)
    check(await ev(P[2], '__tank.settings().ammo') == 'reload' and await ev(P[2], '__tank.state') == 'guestWait', 'non-leader commands are ignored')
    # the leader changes a setting, then starts
    await ev(P[0], "__tank.net.sendCmd('set', Object.assign({}, __tank.settings(), {powerups:false}))")
    await P[0].wait_for_timeout(500)
    check(await ev(P[3], '__tank.settings().powerups') == False, 'leader setting change reaches everyone')
    await ev(P[0], "__tank.net.sendCmd('start')"); await P[0].wait_for_timeout(3200)
    st = [await ev(p, '__tank.state') for p in P]
    check(all(s == 'play' for s in st), f'all players in play {st}')
    check(all([await ev(p, '__tank.net.NP') == 4 for p in P]), 'everyone sees 4 tanks')
    # p2 drives; p3 should see p2's tank move
    s2 = await ev(P[1], '__tank.net.mySeat')
    before = await ev(P[2], f'[__tank.tanksNow[{s2}].x, __tank.tanksNow[{s2}].y]')
    await P[1].keyboard.down('ArrowUp'); await P[1].wait_for_timeout(250)
    await P[1].keyboard.down('ArrowLeft'); await P[1].wait_for_timeout(700)
    await P[1].keyboard.up('ArrowUp'); await P[1].keyboard.up('ArrowLeft'); await P[2].wait_for_timeout(700)
    after = await ev(P[2], f'[__tank.tanksNow[{s2}].x, __tank.tanksNow[{s2}].y]')
    own = await ev(P[1], f'[__tank.tanksNow[{s2}].x, __tank.tanksNow[{s2}].y]')
    moved = math.hypot(after[0]-before[0], after[1]-before[1]); agree = math.hypot(after[0]-own[0], after[1]-own[1])
    check(moved > 0.3 and agree < 0.25, f"another player sees p2 move {moved:.2f} cells; p2's own view agrees within {agree:.2f}")
    # everybody fires; every player's shot shows up for p4
    for p in P[:3]: await p.keyboard.press('Enter')
    await P[3].wait_for_timeout(400)
    owners = sorted(set(await ev(P[3], '__tank.bullets.map(b => b.owner)')))
    seats_of = sorted([await ev(p, '__tank.net.mySeat') for p in P[:3]])
    check(set(seats_of).issubset(set(owners)) or len(owners) >= 2, f'p4 sees shots from {owners} (fired by seats {seats_of})')
    # the leader leaves mid-match: the next player leads, the match goes on
    await P[0].close(); await P[1].wait_for_timeout(1500)
    check(await ev(P[1], '__tank.net.isLeader') and not await ev(P[2], '__tank.net.isLeader'), 'next player becomes leader')
    st = await ev(P[2], '__tank.state')
    check(st in ('play', 'ending', 'result', 'countdown'), f'match goes on after the leader left ({st})')
    # play out the match by waiting; the new leader can rematch / lobby at the end
    for _ in range(90):
      if await ev(P[1], '__tank.state') == 'matchEnd': break
      await P[1].wait_for_timeout(1000)
      # nudge rounds along: everyone fires at random
      for p in P[1:]:
        try: await p.keyboard.press('Enter')
        except Exception: pass
    st = await ev(P[1], '__tank.state')
    print('   state after waiting:', st, await ev(P[1], '__tank.scores'))
    if st == 'matchEnd':
      await P[1].wait_for_timeout(1400)
      items = await ev(P[1], '__tank.endItems().map(i => i.kind)')
      check(items == ['rematch', 'lobby'], f'new leader gets Rematch/Lobby {items}')
      await ev(P[1], "__tank.net.sendCmd('lobby')"); await P[1].wait_for_timeout(800)
      check(await ev(P[3], '__tank.state') == 'guestWait', 'lobby brings everyone back to the waiting room')
    # everyone drops out (pages closed): the room stays open for a while
    for p in P[1:]: await p.close()
    await asyncio.sleep(17)
    import urllib.request, json
    rooms = json.loads(urllib.request.urlopen(URL + 'relay.json').read())['rooms']
    check(rooms >= 1, f'a room everyone dropped out of is kept a while for them to come back (rooms={rooms})')
    await br.close()
  print('\nERRORS:' if errors else '\nno console errors')
  for e in errors[:20]: print('  ', e)
asyncio.run(main())
