import asyncio
from playwright.async_api import async_playwright
URL='http://127.0.0.1:8790/'
errs=[]
async def main():
  async with async_playwright() as pw:
    br=await pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--disable-renderer-backgrounding','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows'])
    async def page(w,h,name):
      ctx=await br.new_context(viewport={'width':w,'height':h}, has_touch=True, is_mobile=True, device_scale_factor=2)
      p=await ctx.new_page()
      p.on('pageerror', lambda e: errs.append(f'{name}: {e}'))
      p.on('console', lambda m: errs.append(f'{name}: {m.text}') if m.type=='error' and 'Failed to load resource' not in m.text else None)
      await p.goto(URL); await p.wait_for_timeout(400); return p
    H=await page(1180,820,'tablet-host')
    G=await page(844,390,'phone-guest')
    print('host title rotated:', await H.evaluate('__tank.layout.rotated'))
    await H.evaluate('__tank.net.hostGame()'); await H.wait_for_timeout(600)
    code=await H.evaluate('__tank.net.code')
    print('host online rotated / land:', await H.evaluate('[__tank.layout.rotated, __tank.layout.LW, __tank.layout.LH]'))
    await G.evaluate(f'__tank.net.joinGame("{code}")'); await G.wait_for_timeout(1200)
    await H.screenshot(path='l_hostwait.png')
    await H.evaluate('__tank.net.hostStart()'); await H.wait_for_timeout(3000)
    print('guest state', await G.evaluate('__tank.state'), await G.evaluate('__tank.layout'))
    # touch drive on the phone: put a thumb on the left panel and drag up
    lay=await G.evaluate('__tank.layout')
    x,y=lay['JX0'],lay['CY0']
    before=await H.evaluate('[__tank.tanksNow[1].x,__tank.tanksNow[1].y]')
    await G.dispatch_event('canvas','pointerdown',{'pointerId':5,'clientX':x,'clientY':y,'isPrimary':True,'pointerType':'touch'})
    await G.dispatch_event('canvas','pointermove',{'pointerId':5,'clientX':x+50,'clientY':y,'isPrimary':True,'pointerType':'touch'})
    await G.wait_for_timeout(500)
    held=await H.evaluate('(([id,g])=>g.inp)([...__tank.net.guests][0])')
    print('host sees guest stick', held)
    await G.dispatch_event('canvas','pointerup',{'pointerId':5,'clientX':x+50,'clientY':y,'pointerType':'touch'})
    # fire with the right thumb
    shots0=await H.evaluate("__tank.net.buildSnap().E.filter(e=>e[1]==='shot'&&e[2]===1).length")
    await G.dispatch_event('canvas','pointerdown',{'pointerId':6,'clientX':lay['FX0'],'clientY':lay['CY0'],'pointerType':'touch'})
    await G.dispatch_event('canvas','pointerup',{'pointerId':6,'clientX':lay['FX0'],'clientY':lay['CY0'],'pointerType':'touch'})
    await G.wait_for_timeout(300)
    shots1=await H.evaluate("__tank.net.buildSnap().E.filter(e=>e[1]==='shot'&&e[2]===1).length")
    print('guest fire reached host', shots1>shots0)
    await G.wait_for_timeout(400)
    await G.screenshot(path='l_guest.png')
    # back to the menu on the phone: one-screen title should rotate again
    await G.evaluate('__tank.goMenu()'); await G.wait_for_timeout(300)
    print('phone title rotated again:', await G.evaluate('__tank.layout.rotated'))
    await br.close()
  print('errors:', errs[:10])
asyncio.run(main())
