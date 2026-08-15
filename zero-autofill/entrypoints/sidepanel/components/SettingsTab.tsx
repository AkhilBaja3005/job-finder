import React, { useState, useEffect } from 'react';
import { getSettings, saveSettings, AISettings } from '../../../modules/storage/db';

export function SettingsTab() {
  const [settings, setSettingsState] = useState<AISettings>({
    provider: 'backend',
    apiKey: '',
    localEndpoint: 'http://localhost:11434',
    localModel: 'llama3.2',
    backendBaseUrl: 'http://localhost:8000',
    backendAuthToken: 'GABY48',
  });

  const [savedStatus, setSavedStatus] = useState('');

  useEffect(() => {
    getSettings().then(setSettingsState);
  }, []);

  const handleSave = async () => {
    await saveSettings(settings);
    setSavedStatus('Settings saved!');
    setTimeout(() => setSavedStatus(''), 3000);
  };

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2">
        <h2 className="text-sm font-bold text-sky-400">⚙️ AI Provider & Sync Settings</h2>
        <button
          onClick={handleSave}
          className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-3 py-1 rounded shadow transition"
        >
          Save Settings
        </button>
      </div>

      {savedStatus && (
        <div className="p-2 bg-emerald-950 border border-emerald-800 text-emerald-300 rounded text-center">
          {savedStatus}
        </div>
      )}

      {/* Provider Selector */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
        <label className="block text-[10px] text-slate-400 font-semibold uppercase">AI Engine Provider</label>
        <select
          value={settings.provider}
          onChange={(e) => setSettingsState({ ...settings, provider: e.target.value as any })}
          className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
        >
          <option value="backend">App Backend Service (FastAPI)</option>
          <option value="window.ai">Chrome Built-in Prompt API (window.ai / Gemini Nano)</option>
          <option value="ollama">Local Ollama / LM Studio (100% Offline)</option>
          <option value="gemini">Google Gemini Flash (Cloud BYOK)</option>
        </select>
      </div>

      {/* App Backend Integration */}
      {settings.provider === 'backend' && (
        <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
          <h3 className="font-semibold text-slate-300">App Backend Connection</h3>
          <div>
            <label className="block text-[10px] text-slate-400">Backend Base URL (Local or HuggingFace)</label>
            <input
              type="url"
              value={settings.backendBaseUrl || ''}
              onChange={(e) => setSettingsState({ ...settings, backendBaseUrl: e.target.value })}
              placeholder="https://your-hf-space.hf.space or http://localhost:8000"
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-400">6-Digit Sync Code or Auth Token</label>
            <input
              type="text"
              value={settings.backendAuthToken || ''}
              onChange={(e) => setSettingsState({ ...settings, backendAuthToken: e.target.value })}
              placeholder="e.g. A7X9K2"
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200 uppercase tracking-widest font-mono"
            />
            <p className="text-[10px] text-slate-500 mt-1">
              Copy your 6-character Sync Code from your Web Application profile header to sync directly with Supabase/HuggingFace.
            </p>
          </div>
        </div>
      )}

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
