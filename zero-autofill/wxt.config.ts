import { defineConfig } from 'wxt';

// See https://wxt.dev/api/config.html
export default defineConfig({
  extensionApi: 'chrome',
  modules: ['@wxt-dev/module-react'],
  manifest: {
    name: 'Zero-Autofill: AI Job Application Copilot',
    description: '100% Client-Side, Zero-Backend Job Application Autofill & Tracker Chrome Extension',
    version: '1.0.0',
    permissions: [
      'storage',
      'activeTab',
      'tabs',
      'scripting',
      'sidePanel'
    ],
    host_permissions: ['<all_urls>'],
    action: {
      default_title: 'Open Zero-Autofill Sidepanel'
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
