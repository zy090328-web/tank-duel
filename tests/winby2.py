# Round-by-round modes are won by two clear: first to 5, but at 4-4 play goes on until someone leads by two.
# Kill and time goals end as before.  python3 tests/winby2.py http://127.0.0.1:8790/
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
    ctx = await br.new_context(viewport={'width': 1180, 'height': 820}); p = await ctx.new_page()
    p.on('pageerror', lambda e: errors.append(str(e)))
    await p.goto(URL); await p.wait_for_timeout(400)
    ev = lambda js, a=None: p.evaluate(js, a)
    async def game(g, win=5, cpu=1):
      await ev(f"(() => {{ const T = __tank; T.setSettings(Object.assign({{}}, T.settings(), {{ game: '{g}', cpu: {cpu}, winScore: {win} }})); T.goMenu(); T.beginFromMenu(); }})()")
    async def done(sc):
      return await ev(f"(() => {{ const T = __tank; T.scores.fill(0); {sc}.forEach((v, i) => T.scores[i] = v); return [T.matchDone(), T.deuce(), T.hudOf()]; }})()")

    await game('classic')
    d = await done([5, 3]); check(d[0] is True, f'5-3 wins a first-to-5 match {d}')
    d = await done([4, 4]); check(d[0] is False and d[1] is True and 'win by 2' in d[2], f'4-4 is deuce, shown as "win by 2" {d}')
    d = await done([5, 4]); check(d[0] is False, f'5-4 does not end it {d}')
    d = await done([5, 5]); check(d[0] is False, f'nor 5-5 {d}')
    d = await done([7, 5]); check(d[0] is True, f'7-5 does {d}')
    d = await done([3, 2]); check(d[1] is False and d[2] == 'of 5', f'before deuce the score line is as before {d}')
    await game('classic', 3)
    d = await done([3, 2]); check(d[0] is False, f'first to 3: 3-2 plays on {d}')
    d = await done([4, 2]); check(d[0] is True, f'...4-2 wins {d}')
    # a whole round through the real flow: at 5-4 the result screen leads to another round, not the end
    await game('classic', 5)
    st = await ev("""(async () => { const T = __tank; for (let i = 0; i < 60 && T.state !== 'play'; i++) await new Promise(r => setTimeout(r, 200));
      T.scores.fill(0); T.scores[0] = 4; T.scores[1] = 4;
      const [a, b] = T.tanksNow; T.kill(b, a.id); await new Promise(r => setTimeout(r, 6500)); return [T.state, [...T.scores]]; })()""")
    check(st[1][:2] == [5, 4] and st[0] not in ('matchEnd',), f'winning a round at 4-4 makes it 5-4 and play goes on {st}')
    st = await ev("""(async () => { const T = __tank; for (let i = 0; i < 60 && T.state !== 'play'; i++) await new Promise(r => setTimeout(r, 200));
      const [a, b] = T.tanksNow; T.kill(b, a.id); await new Promise(r => setTimeout(r, 6500)); return [T.state, [...T.scores]]; })()""")
    check(st[1][:2] == [6, 4] and st[0] == 'matchEnd', f'winning the next makes it 6-4 and the match is over {st}')
    # teams and soccer count by side
    await game('soccer', 5, 3)
    d = await done([5, 4]); check(d[0] is False, f'soccer 5-4 plays on {d}')
    d = await done([6, 4]); check(d[0] is True, f'soccer 6-4 ends {d}')
    # running totals end at the goal as before
    await game('dm', 5)
    tgt = await ev('(() => __tank.target())()')
    d = await done([tgt, tgt - 1]); check(d[1] is False, f'deathmatch has no "win by 2" ({d})')
    for e in errors: print('ERROR', e)
    await br.close()
  if errors or check.failed: print('SOME FAILED'); sys.exit(1)
  print('ALL PASS')
asyncio.run(main())
