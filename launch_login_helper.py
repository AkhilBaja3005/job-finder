import asyncio, os
from playwright.async_api import async_playwright

async def main():
    profile_dir = os.path.abspath("backend/user_data/top_applicant_scanner_profile")
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    print(f"🚀 Launching clean persistent Chrome window...")
    print(f"👉 Target Profile: {profile_dir}")
    print(f"👉 TIP: You can sign in using your LinkedIn email/password or 'Sign in with Google'.")
    print(f"👉 Once signed in and you reach your feed, this window will automatically detect it and save.\n")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            executable_path=chrome_path,
            headless=False,
            viewport={"width": 1280, "height": 850},
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--no-first-run",
                "--no-default-browser-check"
            ]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        # Strip navigator.webdriver flag so Google OAuth does not block with 'This browser or app may not be secure'
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        
        try:
            # Wait up to 3 minutes for you to complete sign-in
            await page.wait_for_url("**/feed/**", timeout=180000)
            print("\n🎉 Detected LinkedIn login success! Saving session state...")
            await asyncio.sleep(4)
            print("✅ Session saved permanently for both scanner and auto-fill!")
        except Exception:
            print("\nℹ️ Helper closed or session timed out.")
        finally:
            await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
