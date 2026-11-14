# Sound: every effect plays without an error and makes a signal, and what comes out of the limiter stays below full scale.
# (A check of levels, not of how it sounds.) Needs the server on port 8790.
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8790/'
def check(cond, msg):
  print(('PASS ' if cond else 'FAIL ') + msg)
  if not cond: check.failed = True
check.failed = False

async def main():
  async with async_playwright() as pw:
    br = await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
    p = await br.new_page(); errors = []
    p.on('pageerror', lambda e: errors.append(str(e)))
    await p.goto(URL); await p.wait_for_timeout(400)
    r = await p.evaluate("""async () => { const T = __tank; T.audioInit(); await new Promise(r => setTimeout(r, 200));
      const { actx, out: master } = T.audio; if (!actx || !master) return { state: 'none' };
      const an = actx.createAnalyser(); an.fftSize = 2048; master.connect(an);
      const buf = new Float32Array(an.fftSize), out = { state: actx.state, peaks: {}, threw: [] };
      for (const name of Object.keys(T.sfx)) {
        if (typeof T.sfx[name] !== 'function') continue;
        try { T.sfx[name](1); } catch (e) { out.threw.push(name + ': ' + e.message); }
        let peak = 0; const t0 = performance.now();
        while (performance.now() - t0 < 700) { an.getFloatTimeDomainData(buf); for (const v of buf) peak = Math.max(peak, Math.abs(v)); await new Promise(r => setTimeout(r, 12)); }
        out.peaks[name] = +peak.toFixed(3);
      }
      // a pile-up: a volley of shots, bounces and two blasts at once
      for (let i = 0; i < 6; i++) { T.sfx.shoot(i % 5); T.sfx.bounce(); } T.sfx.boom(); T.sfx.boom();
      let peak = 0; const t0 = performance.now();
      while (performance.now() - t0 < 700) { an.getFloatTimeDomainData(buf); for (const v of buf) peak = Math.max(peak, Math.abs(v)); await new Promise(r => setTimeout(r, 12)); }
      out.pile = +peak.toFixed(3); return out; }""")
    print(r)
    check(r.get('state') == 'running', f"audio is running ({r.get('state')})")
    if r.get('state') == 'running':
      pk = r['peaks']
      check(not r['threw'], f"no effect throws {r['threw']}")
      check(all(v > 0.004 for v in pk.values()), 'every effect makes a signal ' + str([k for k, v in pk.items() if v <= 0.004]))
      check(all(v < 0.9 for v in pk.values()), 'no single effect is near full scale ' + str([k for k, v in pk.items() if v >= 0.95]))
      check(r['pile'] < 1, f"a pile of effects at once stays below full scale ({r['pile']})")
    await br.close()
  if errors: print('ERRORS:', errors[:10])
  print('ALL PASS' if not check.failed and not errors else 'SOME FAILED')
asyncio.run(main())
