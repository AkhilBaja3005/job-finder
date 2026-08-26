import React, { useState, useEffect } from 'react';
import { getSettings, saveSettings, AISettings } from '../../../modules/storage/db';

export function SettingsTab() {
  const [settings, setSettingsState] = useState<AISettings>({
    provider: 'backend',
    apiKey: '',
    localEndpoint: 'http://localhost:11434',
    localModel: 'llama3.2',
    backendBaseUrl: 'http://127.0.0.1:8000',
    backendAuthToken: '',
    maxYears: 5,
    blacklistKeywords: 'Senior, Lead, Manager, Director'
  });

  const [savedStatus, setSavedStatus] = useState('');
  const [statusType, setStatusType] = useState<'success' | 'error' | 'info'>('info');
  const [testResult, setTestResult] = useState<{ connected: boolean; email?: string; error?: string } | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  useEffect(() => {
    getSettings().then((s) => {
      setSettingsState(s);
      if (s.backendAuthToken) {
        verifyBackend(s.backendBaseUrl || 'http://127.0.0.1:8000', s.backendAuthToken);
      }
    });
  }, []);

  const verifyBackend = async (url: string, token: string) => {
    setIsTesting(true);
    try {
      const cleanUrl = (url || 'http://127.0.0.1:8000').replace(/\/+$/, '');
      const cleanToken = token.trim();
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (cleanToken) {
        headers['Authorization'] = cleanToken.startsWith('Bearer ') ? cleanToken : `Bearer ${cleanToken}`;
      }

      const res = await fetch(`${cleanUrl}/user/me`, { headers });
      const contentType = res.headers.get('content-type') || '';

      if (!contentType.includes('application/json')) {
        setTestResult({
          connected: false,
          error: 'Backend returned HTML page instead of JSON API. Check port/URL.'
        });
        return;
      }

      if (res.ok) {
        const data = await res.json();
        setTestResult({
          connected: true,
          email: data.email || 'Connected User'
        });
      } else {
        setTestResult({
          connected: false,
          error: `HTTP ${res.status}: Invalid Sync Code or Unauthorized`
        });
      }
    } catch (e: any) {
      setTestResult({
        connected: false,
        error: `Could not reach ${url}: ${e.message || e}`
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = async () => {
    await saveSettings(settings);
    try {
      chrome.storage.local.set({
        userToken: settings.backendAuthToken || '',
        maxYears: settings.maxYears,
        blacklistKeywords: settings.blacklistKeywords
      });
    } catch (e) {}
    setStatusType('success');
    setSavedStatus('Settings saved successfully!');
    if (settings.backendAuthToken) {
      verifyBackend(settings.backendBaseUrl || 'http://127.0.0.1:8000', settings.backendAuthToken);
    }
    setTimeout(() => setSavedStatus(''), 3000);
  };

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2">
        <h2 className="text-sm font-bold text-sky-400">⚙️ AI Provider & Sync Settings</h2>
        <button
          onClick={handleSave}
          className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-3 py-1 rounded shadow transition text-[11px]"
        >
          Save Settings
        </button>
      </div>

      {savedStatus && (
        <div
          className={`p-2 rounded text-center text-xs ${
            statusType === 'success'
              ? 'bg-emerald-950 border border-emerald-800 text-emerald-300'
              : 'bg-rose-950 border border-rose-800 text-rose-300'
          }`}
        >
          {savedStatus}
        </div>
      )}

      {/* Provider Selector */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
        <label className="block text-[10px] text-slate-400 font-semibold uppercase">AI Engine Provider</label>
        <select
          value={settings.provider}
          onChange={(e) => setSettingsState({ ...settings, provider: e.target.value as any })}
          className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1.5 focus:border-sky-500 outline-none text-slate-200"
        >
          <option value="backend">Job Finder Backend API (FastAPI + LLM Agent)</option>
          <option value="window.ai">Chrome Built-in Prompt API (window.ai / Gemini Nano)</option>
          <option value="gemini">Google Gemini Flash (Cloud BYOK)</option>
          <option value="ollama">Local Ollama / LM Studio (100% Offline)</option>
        </select>
      </div>

      {/* App Backend Integration */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
        <h3 className="font-semibold text-slate-300">App Backend Connection & Sync Key</h3>
        <div>
          <label className="block text-[10px] text-slate-400">Backend Base URL</label>
          <input
            type="url"
            value={settings.backendBaseUrl || ''}
            onChange={(e) => setSettingsState({ ...settings, backendBaseUrl: e.target.value })}
            placeholder="http://127.0.0.1:8000 or https://your-domain.com"
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
          />
        </div>
        <div>
          <label className="block text-[10px] text-slate-400">6-Digit Sync Code or Bearer Token</label>
          <input
            type="text"
            value={settings.backendAuthToken || ''}
            onChange={(e) => setSettingsState({ ...settings, backendAuthToken: e.target.value.toUpperCase() })}
            placeholder="e.g. A7X9K2"
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200 uppercase tracking-widest font-mono font-bold"
          />
          <p className="text-[10px] text-slate-500 mt-1">
            Copy your 6-character Sync Code from your web app dashboard header to pair automatically.
          </p>
        </div>

        {/* Backend Connection Badge */}
        <div className="pt-1">
          {isTesting ? (
            <div className="text-[10px] text-slate-400">Testing connection...</div>
          ) : testResult ? (
            testResult.connected ? (
              <div className="p-2 bg-emerald-950/80 border border-emerald-800 rounded text-emerald-300 text-[10px] flex items-center gap-1.5">
                <span>🟢</span>
                <span>Connected: <b>{testResult.email}</b></span>
              </div>
            ) : (
              <div className="p-2 bg-rose-950/80 border border-rose-800 rounded text-rose-300 text-[10px] flex items-center gap-1.5">
                <span>🔴</span>
                <span>Offline: {testResult.error}</span>
              </div>
            )
          ) : null}
        </div>
      </div>

      {/* Cloud BYOK Gemini Key */}
      {settings.provider === 'gemini' && (
        <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
          <h3 className="font-semibold text-slate-300">Google Gemini API Key</h3>
          <input
            type="password"
            value={settings.apiKey || ''}
            onChange={(e) => setSettingsState({ ...settings, apiKey: e.target.value })}
            placeholder="AIzaSy..."
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
          />
        </div>
      )}

      {/* Local Ollama Endpoint */}
      {settings.provider === 'ollama' && (
        <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
          <h3 className="font-semibold text-slate-300">Ollama Local Endpoint</h3>
          <div>
            <label className="block text-[10px] text-slate-500">Endpoint URL</label>
            <input
              type="url"
              value={settings.localEndpoint || ''}
              onChange={(e) => setSettingsState({ ...settings, localEndpoint: e.target.value })}
              placeholder="http://localhost:11434"
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Model Name</label>
            <input
              type="text"
              value={settings.localModel || ''}
              onChange={(e) => setSettingsState({ ...settings, localModel: e.target.value })}
              placeholder="llama3.2"
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
          </div>
        </div>
      )}
    </div>
  );
}
