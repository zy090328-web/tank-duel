# every map, in every game mode and tank count: spawns are open, distinct and all connected; the hill is reachable
import sys, json, os
from playwright.sync_api import sync_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'file://' + os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'index.html')
JS = r"""
() => {
  const T = window.__tank, out = [], terr = [];
  const base = T.settings();
  for (const game of ['classic', 'teams', 'dm', 'hill']) for (const soft of [false, true]) for (const terrain of [false, true]) for (let np = 2; np <= 5; np++) {
    T.setSettings(Object.assign({}, base, { game, soft, terrain, cpu: Math.min(3, np - 1) }));
    T.setupLocal();
    if (T.NP !== np && np <= 4) { out.push(['np mismatch', game, np, T.NP]); continue; }
    if (np === 5) continue;
    const pool = T.mapPool();
    if (!pool.length) out.push(['empty pool', game, np]);
    for (const m of pool) {
      T.showMap(m);
      const W = T.walls, C = T.COLS, R = T.ROWS, sp = T.spawn;
      if (sp.length < np) { out.push(['few spawns', game, np, m, sp.length]); continue; }
      const cells = sp.slice(0, np).map(s => [Math.floor(s.y), Math.floor(s.x)]);
      const d = T.distField(cells[0][1], cells[0][0]);
      cells.forEach(([r, c], i) => {
        if (W[r][c]) out.push(['spawn in wall', game, np, m, i]);
        if (T.water[r * C + c]) out.push(['spawn in water', game, np, m, i]);
        if (d[r * C + c] < 0) out.push(['spawn cut off', game, np, m, i]);
      });
      const keys = new Set(cells.map(x => x.join(',')));
      if (keys.size !== np) out.push(['spawns overlap', game, np, m]);
      if (game === 'hill' && d[(R >> 1) * C + (C >> 1)] < 0) out.push(['hill cut off', m]);
      // every open cell reachable (no sealed pockets a respawn could pick is guaranteed by distField, but report big pockets)
      let open = 0, reach = 0;
      for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) if (!W[r][c] && !T.water[r * C + c]) { open++; if (d[r * C + c] >= 0) reach++; }
      if (terrain && np === 2 && game === 'classic' && !soft) terr.push([m, T.water.reduce((a, b) => a + b, 0), T.grass.reduce((a, b) => a + b, 0), open - reach]);
      if (reach < open * 0.9) out.push(['pockets', game, m, open, reach]);
    }
  }
  T.setSettings(base); T.goMenu();
  return { problems: out, maps: T.MAPS.length, rot4: [...T.ROT4], terrain: terr };
}
"""
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 800, 'height': 1100})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(600)
    r = pg.evaluate(JS)
    print(json.dumps(r))
    print('errors:', errs)
    b.close()
    sys.exit(1 if r['problems'] or errs else 0)
