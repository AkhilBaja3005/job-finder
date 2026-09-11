import asyncio, os
from playwright.async_api import async_playwright

async def main():
    profile_dir = os.path.abspath("backend/user_data/top_applicant_scanner_profile")
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    print(f"Launching Chrome window for Profile: {profile_dir}")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            executable_path=chrome_path,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--no-first-run", "--no-default-browser-check"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.linkedin.com/login")
        print("Opened LinkedIn login page.")
        # Wait until user logs in or closes window
        try:
            await page.wait_for_url("**/feed/**", timeout=60000)
            print("🎉 Detected LinkedIn login success!")
            await asyncio.sleep(3)
        except Exception:
            print("Session closed or timed out.")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
