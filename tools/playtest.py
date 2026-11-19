import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
        pg = await b.new_page(viewport={"width":390,"height":844}, device_scale_factor=2)
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto("http://localhost:8765/index.html"); await pg.wait_for_timeout(1500)
        shots=0; results=[]
        for game in range(3):
            for i in range(20):
                if await pg.locator("#modal.show").count(): break
                lie = await pg.inner_text("#hLie")
                if lie=="Green" and shots<2:
                    await pg.wait_for_timeout(2500); await pg.screenshot(path=f"gr{shots}.png"); shots+=1
                await pg.mouse.click(200,400); await pg.wait_for_timeout(600+i*37%400)
                await pg.mouse.click(200,400); await pg.wait_for_timeout(5500 if lie=="Green" else 4200)
            results.append(await pg.inner_text("#mTitle") + " / " + await pg.inner_text("#mText"))
            await pg.click("#again"); await pg.wait_for_timeout(1200)
        print("errors:", errs); print(results)
        await b.close()
asyncio.run(main())
