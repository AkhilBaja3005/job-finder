import { defineConfig } from 'wxt';

// See https://wxt.dev/api/config.html
export default defineConfig({
  extensionApi: 'chrome',
  modules: ['@wxt-dev/module-react'],
  manifest: {
    name: 'Job Finder ATS Tailor & AutoFill Copilot',
    description: 'AI ATS AutoFill (Greenhouse, Lever, Ashby, Workday, LinkedIn) + Batch Auto-Apply & Job Fit Analyzer',
    version: '2.0.0',
    permissions: [
      'storage',
      'activeTab',
      'tabs',
      'scripting',
      'sidePanel'
    ],
    host_permissions: ['<all_urls>'],
    action: {
      default_title: 'Open Job Finder ATS Sidepanel'
    },
    side_panel: {
      default_path: 'sidepanel.html'
    }
  },
  hooks: {
    'build:done': (_wxt, output) => {
      import('fs').then(fs => {
        const contentScriptPath = '.output/chrome-mv3/content-scripts/content.js';
        if (fs.existsSync(contentScriptPath)) {
          const buf = fs.readFileSync(contentScriptPath);
          const cleaned = buf.toString('utf-8').replace(/\uFFFF/g, '\\uFFFF');
          fs.writeFileSync(contentScriptPath, cleaned);
          console.log('[WXT Hook] Cleaned non-character U+FFFF bytes in content.js for Chrome V8 compliance.');
        }
      });
    }
  }
});
