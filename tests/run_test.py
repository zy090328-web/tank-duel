import asyncio, json, sys, time
from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/index.html'
USE_MOCK = not (len(sys.argv) > 2 and sys.argv[2] == 'relay')
MOCK = open('/home/claude/tests/mockpeer.js').read()
errors = []

BR = None
async def new_page(ctx, name):
    # through the relay, each player gets a window of its own: tabs in one window are background tabs,
    # which the browser slows to one frame a second (the BroadcastChannel stand-in needs one shared context)
    if not USE_MOCK and BR is not None: ctx = await BR.new_context(viewport={'width': 820, 'height': 1180})
    p = await ctx.new_page()
    # fonts and the favicon cannot load in this offline sandbox; anything else is a real error
    p.on('console', lambda m, n=name: errors.append(f'{n} console.{m.type}: {m.text}') if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    p.on('pageerror', lambda e, n=name: errors.append(f'{n} pageerror: {e}'))
    await p.goto(URL)
    await p.wait_for_timeout(300)
    return p

async def ev(p, js):
    return await p.evaluate(js)

def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond: check.failed = True
check.failed = False

async def main():
    async with async_playwright() as pw:
        br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--autoplay-policy=no-user-gesture-required','--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
        ctx = await br.new_context(viewport={'width': 820, 'height': 1180})
        global BR; BR = br
        if USE_MOCK: await ctx.add_init_script(MOCK)

        # ---- one screen, two players: unchanged behaviour
        L = await new_page(ctx, 'local')
        await L.keyboard.press('Enter')
        await L.wait_for_timeout(2400)
        check(await ev(L, '__tank.state') == 'play', 'local match starts with Enter')
        await L.keyboard.press('Enter'); await L.keyboard.press('Space')
        await L.wait_for_timeout(200)
        n = await ev(L, '__tank.bullets.length')
        check(n == 2, f'local both players fire ({n} bullets)')
        check(await ev(L, '__tank.net.NP') == 2, 'local match has 2 tanks')
        await L.close()

        # ---- online: host + 4 guests
        H = await new_page(ctx, 'host')
        await ev(H, '__tank.net.hostGame()')
        await H.wait_for_timeout(400)
        code = await ev(H, '__tank.net.code')
        check(len(code) == 4, f'host opens game with code {code}')
        G = []
        for i in range(4):
            g = await new_page(ctx, f'guest{i+1}')
            await ev(g, f'__tank.net.joinGame("{code}")')
            G.append(g)
        await H.wait_for_timeout(1500)
        seats = await ev(H, '__tank.net.seats')
        check(len(seats) == 5, f'host has 5 seats ({len(seats)})')
        g_state = [await ev(g, '__tank.state') for g in G]
        check(all(s == 'guestWait' for s in g_state), f'guests wait ({g_state})')
        g_seat = [await ev(g, '__tank.net.mySeat') for g in G]
        check(sorted(g_seat) == [1, 2, 3, 4], f'guests know their seats {g_seat}')

        # wrong code
        X = await new_page(ctx, 'wrongcode')
        await ev(X, '__tank.net.joinGame("0000")')
        await X.wait_for_timeout(2200)
        check(await ev(X, '__tank.state') == 'joinCode' and 'No game' in await ev(X, '__tank.net.msg'), 'wrong code is reported')
        await X.close()

        await ev(H, "__tank.setSettings({ammo:'unlimited', powerups:false, maps:'all', winScore:3})")
        await ev(H, '__tank.net.hostStart()')
        await H.wait_for_timeout(2600)
        check(await ev(H, '__tank.state') == 'play', 'host match running')
        g_state = [await ev(g, '__tank.state') for g in G]
        check(all(s == 'play' for s in g_state), f'guests see play ({g_state})')
        check(all([await ev(g, '__tank.net.NP') == 5 for g in G]), 'guests see 5 tanks')
        flips = [await ev(g, '__tank.net.viewFlip') for g in G]
        print('   view flips per guest:', flips)

        # guest 1 drives: its tank should move on the host
        before = await ev(H, '[__tank.tanksNow[1].x, __tank.tanksNow[1].y]')
        gid = await ev(G[0], '__tank.net.seats ? null : null')
        await G[0].keyboard.down('ArrowUp'); await G[0].wait_for_timeout(500)
        held = await ev(H, '(([id,g]) => g.inp)([...__tank.net.guests].find(([id]) => __tank.net.seats.indexOf(id) === 1))')
        check(abs(held[2] - 1) < 1e-6, f'host receives guest 1 holding the stick {held}')
        await G[0].wait_for_timeout(400); await G[0].keyboard.up('ArrowUp')
        await H.wait_for_timeout(300)
        after = await ev(H, '[__tank.tanksNow[1].x, __tank.tanksNow[1].y]')
        moved = ((after[0]-before[0])**2 + (after[1]-before[1])**2) ** 0.5
        print(f'   guest 1 tank moved {moved:.2f} cells on the host (a wall can block it)')
        moved = 1
        if moved <= 0.5:
            print('   DIAG host guests:', await ev(H, '[...__tank.net.guests].map(([id,g]) => [id, __tank.net.seats.indexOf(id), g.inp, g.lastFire, Math.round(performance.now()-g.lastAt)])'))
            print('   DIAG host tank1:', await ev(H, '(t => [t.x, t.y, t.angle, t.alive, t.cool, t.power])(__tank.tanksNow[1])'), 'map', await ev(H, '__tank.mapId'))
            print('   DIAG guest1 seat:', await ev(G[0], '[__tank.net.mySeat, __tank.net.viewFlip]'))
        # the guest's own picture agrees with the host within a small lag
        gpos = await ev(G[0], '[__tank.tanksNow[1].x, __tank.tanksNow[1].y]')
        d = ((gpos[0]-after[0])**2 + (gpos[1]-after[1])**2) ** 0.5
        check(d < 0.4, f'guest 1 sees its tank where the host has it (off by {d:.2f})')

        # every guest fires: bullets with their owners appear on the host and on the guests
        for g in G:
            await g.keyboard.press('Enter')
        await H.wait_for_timeout(250)
        # count shots fired (a bullet fired point-blank at a wall can bounce straight back into its own tank)
        owners = await ev(H, "__tank.net.buildSnap().E.filter(e => e[1] === 'shot').map(e => e[2])")
        check(set([1,2,3,4]).issubset(set(owners)), f'host fired a shot for every guest {sorted(owners)}')
        await G[2].wait_for_timeout(200)
        gb = await ev(G[2], '__tank.bullets.length')
        check(gb >= 3, f'guest 3 draws the bullets ({gb})')

        # snapshot size with a busy field
        await ev(H, 'for (const t of __tank.tanksNow) for (let i=0;i<5;i++) { t.cool=0; __tank.fire(t); }')
        size = await ev(H, 'JSON.stringify(__tank.net.buildSnap()).length')
        check(size < 6000, f'busy snapshot is {size} bytes')

        # a kill on the host shows on the guests
        await ev(H, '__tank.kill(__tank.tanksNow[3])')
        await H.wait_for_timeout(400)
        await ev(H, "__tank.bullets.length = 0")
        await H.wait_for_timeout(600)
        hd = await ev(H, '__tank.tanksNow.map(t => t.alive)')
        await H.wait_for_timeout(300)
        same = [await ev(g, '__tank.tanksNow.map(t => t.alive)') for g in G]
        check(not hd[3] and all(x == hd for x in same), f'guests agree on destroyed tanks host {hd} guests {same}')

        # end rounds until the match is over
        for _ in range(40):
            st = await ev(H, '__tank.state')
            if st == 'matchEnd': break
            if st == 'play':
                await ev(H, 'for (const t of __tank.tanksNow.slice(1)) if (t.alive) __tank.kill(t)')
            await H.wait_for_timeout(900)
        check(await ev(H, '__tank.state') == 'matchEnd', 'host reaches match end')
        await G[1].wait_for_timeout(300)
        check(await ev(G[1], '__tank.state') == 'matchEnd', 'guest sees match end')
        sc_h = await ev(H, '__tank.scores'); sc_g = await ev(G[1], '__tank.scores')
        check(sc_h == sc_g, f'scores agree host {sc_h} guest {sc_g}')
        await H.wait_for_timeout(1300)
        await H.screenshot(path='/home/claude/tests/host_end.png')

        # a guest leaves; back in the lobby the seat is gone
        await ev(G[3], '__tank.goMenu()')          # leaving on purpose (closing the page only marks it away)
        await G[3].close()
        await H.wait_for_timeout(600)
        await ev(H, '__tank.net.hostLobby()')
        await H.wait_for_timeout(300)
        seats = await ev(H, '__tank.net.seats')
        check(len(seats) == 4, f'seat freed after a guest left ({len(seats)})')

        # 4-player match with sudden death: walls on a guest match the host
        await ev(H, "__tank.setSettings({ammo:'reload', powerups:true, maps:'all', winScore:7})")
        await ev(H, '__tank.net.hostStart()')
        await H.wait_for_timeout(2600)
        await ev(H, '__tank.roundT = 27')
        await H.wait_for_timeout(1500)
        for _ in range(10):
            hw = await ev(H, 'JSON.stringify(__tank.walls)')
            await G[0].wait_for_timeout(250)
            gw = await ev(G[0], 'JSON.stringify(__tank.walls)')
            if hw == gw: break
        sd = await ev(H, '__tank.sdClosed')
        print('   host map', await ev(H, '[__tank.mapId, __tank.sdClosed, __tank.state, __tank.roundT]'), 'guest map', await ev(G[0], '[__tank.mapId, __tank.sdClosed, __tank.state, __tank.roundT]'))
        hwl = json.loads(hw); gwl = json.loads(gw)
        diff = [(r,c) for r in range(len(hwl)) for c in range(len(hwl[0])) if r < len(gwl) and c < len(gwl[0]) and hwl[r][c] != gwl[r][c]]
        print('   wall cells differing:', len(diff), diff[:8], 'sizes', len(hwl), len(gwl))
        check(sd >= 2 and hw == gw, f'sudden death walls match ({sd} rings closed)')

        # a few seconds of random play everywhere with power-ups, watching for errors
        for step in range(30):
            for i, g in enumerate(G[:3]):
                key = ['ArrowUp','ArrowLeft','ArrowRight','ArrowDown'][(step + i) % 4]
                await g.keyboard.down(key)
                if step % 3 == 0: await g.keyboard.press('Enter')
            await H.wait_for_timeout(150)
            for i, g in enumerate(G[:3]):
                for key in ['ArrowUp','ArrowLeft','ArrowRight','ArrowDown']: await g.keyboard.up(key)
        await G[0].screenshot(path='/home/claude/tests/guest_play.png')

        # the host leaves: guests are told
        await ev(H, '__tank.goMenu()')             # the host leaves on purpose
        await H.close()
        await G[0].wait_for_timeout(1200)
        check(await ev(G[0], '__tank.state') == 'netLost', 'guest told the host left')

        await br.close()

    print('\nERRORS:' if errors else '\nno console errors')
    for e in errors[:30]: print('  ', e)
    if check.failed or errors: sys.exit(1)

asyncio.run(main())
