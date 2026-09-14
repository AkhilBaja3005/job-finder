import asyncio, os
from playwright.async_api import async_playwright

async def main():
    profile_dir = os.path.abspath("backend/user_data/top_applicant_scanner_profile")
    try:
        from backend.services.browser_use_agent import find_browser_executable
        chrome_path = find_browser_executable()
    except Exception:
        import sys, shutil
        chrome_path = None
        if sys.platform == "win32":
            prog_files = os.getenv("ProgramFiles", r"C:\Program Files")
            prog_files_x86 = os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
            local_appdata = os.getenv("LOCALAPPDATA", "")
            candidates = [
                os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe") if local_appdata else "",
                os.path.join(prog_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
            for c in candidates:
                if c and os.path.exists(c):
                    chrome_path = c
                    break
        elif sys.platform == "darwin":
            mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.exists(mac_path):
                chrome_path = mac_path
        if not chrome_path:
            chrome_path = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium") or "chrome"

    print(f"🚀 Launching clean persistent Chrome window ({chrome_path})...")
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
