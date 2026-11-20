# Random hero: the highlight runs over the cards ticking, slows and stops on a different hero, which is then picked;
# for the slot being edited (P2 / a CPU), and online it reaches the host.  python3 tests/random.py http://127.0.0.1:8790/
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
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
    async def page():
      c = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await c.new_page()
      p.on('pageerror', lambda e: errors.append(str(e))); await p.goto(URL); await p.wait_for_timeout(400); return p
    L = await page()
    ev = lambda p, js: p.evaluate(js)
    await ev(L, "(() => { const T = __tank; T.setMySkin('classic'); T.goMenu(); T.openSkins(); })()")
    # the Random button is on the screen, and a click on it starts the wheel
    items = await ev(L, "__tank.net.netItems().filter(i => i.kind === 'sroll' || i.kind === 'sback').map(i => [i.kind, i.x, i.y, i.w, i.h])")
    check(len(items) == 2, f'Random sits beside Back ({[i[0] for i in items]})')
    r = [i for i in items if i[0] == 'sroll'][0]
    box = await ev(L, "(() => { const b = document.querySelector('canvas').getBoundingClientRect(); return [b.left, b.top, b.width / __tank.layout.LW]; })()")
    await L.mouse.click(box[0] + (r[1] + r[3] / 2) * box[2], box[1] + (r[2] + r[4] / 2) * box[2])
    seen = await ev(L, """(async () => { const T = __tank, seen = new Set(); const t0 = performance.now();
      while (T.skinRoll && !T.skinRoll.done && performance.now() - t0 < 5000) { seen.add(T.skinRoll.idx); await new Promise(r => setTimeout(r, 20)); }
      return [seen.size, performance.now() - t0, T.skinRoll && T.skinRoll.done, T.mySkin]; })()""")
    check(seen[0] >= 8, f'the highlight runs over the cards ({seen[0]} different ones)')
    check(1500 < seen[1] < 3500, f'it runs down in a couple of seconds ({seen[1] / 1000:.1f} s)')
    check(seen[2] is True and seen[3] != 'classic', f'it stops on a different hero, which is now picked ({seen[3]})')
    await L.wait_for_timeout(1300)
    check(await ev(L, '__tank.skinRoll') is None, 'the flash where it stopped dies away')
    # picking a card while it runs stops it there and takes that card
    await ev(L, "(() => { const T = __tank; T.startRoll(); })()"); await L.wait_for_timeout(300)
    it = await ev(L, "(() => { const it = __tank.net.netItems().find(i => i.kind === 'skinpick' && i.v === 'rewind'); return [it.x + it.w / 2, it.y + it.h / 2]; })()")
    await L.mouse.click(box[0] + it[0] * box[2], box[1] + it[1] * box[2]); await L.wait_for_timeout(2600)
    check(await ev(L, '[__tank.mySkin, __tank.skinRoll]') == ['rewind', None], 'a card picked mid-spin wins over the wheel')
    # the slot being edited: CPU 1
    await ev(L, "(() => { const T = __tank; T.closeSkins(); T.setSettings(Object.assign({}, T.settings(), { cpu: 1 })); T.setCpuSkin(0, 'heavy'); T.openSkins(); T.skinSlot = 1; T.startRoll(); })()")
    await L.wait_for_timeout(3200)
    r = await ev(L, '[__tank.mySkin, __tank.cpuSkins[0]]')
    check(r[0] == 'rewind' and r[1] != 'heavy', f'with CPU 1 chosen, the roll picks for CPU 1 only ({r})')
    # the R key; leaving mid-spin keeps the old pick
    await ev(L, "(() => { __tank.skinSlot = 0; })()")
    await L.keyboard.press('r'); await L.wait_for_timeout(300)
    check(await ev(L, '!!__tank.skinRoll'), 'R starts the wheel too')
    await L.keyboard.press('Escape'); await L.wait_for_timeout(2800)
    check(await ev(L, '[__tank.mySkin, __tank.skinRoll, __tank.state]') == ['rewind', None, 'title'], 'leaving mid-spin keeps the hero you had')
    # online: a guest's random pick reaches the host
    H = await page(); G = await page()
    await ev(H, '__tank.net.hostGame()'); await H.wait_for_timeout(900)
    code = await ev(H, '__tank.net.code'); await ev(G, f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1500)
    await ev(G, "(() => { const T = __tank; T.setMySkin('classic'); T.openSkins(); T.startRoll(); })()"); await G.wait_for_timeout(3500)
    gs = await ev(G, '__tank.mySkin'); hs = await ev(H, '__tank.lobby.skins[1]')
    check(gs != 'classic' and hs == gs, f"the guest's random hero reaches the host ({gs} / {hs})")
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
