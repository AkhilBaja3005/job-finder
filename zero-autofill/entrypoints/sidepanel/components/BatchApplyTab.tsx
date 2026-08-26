import React, { useState, useEffect } from 'react';
import { getSettings, saveSettings } from '../../../modules/storage/db';

export function BatchApplyTab() {
  const [isRunning, setIsRunning] = useState(false);
  const [appliedCount, setAppliedCount] = useState(0);
  const [skippedCount, setSkippedCount] = useState(0);
  const [maxYears, setMaxYears] = useState(5);
  const [blacklist, setBlacklist] = useState('Senior, Lead, Manager, Director');
  const [logs, setLogs] = useState<string[]>(['Ready to start LinkedIn Batch Auto-Apply...']);

  useEffect(() => {
    // Load initial values from chrome.storage & Dexie
    getSettings().then((s) => {
      if (s.maxYears !== undefined) setMaxYears(s.maxYears);
      if (s.blacklistKeywords !== undefined) setBlacklist(s.blacklistKeywords);
    });

    try {
      chrome.storage.local.get(
        ['isAutoRunning', 'appliedCount', 'skippedCount', 'appLogs', 'maxYears', 'blacklistKeywords'],
        (items) => {
          if (items.isAutoRunning !== undefined) setIsRunning(!!items.isAutoRunning);
          if (items.appliedCount !== undefined) setAppliedCount(items.appliedCount);
          if (items.skippedCount !== undefined) setSkippedCount(items.skippedCount);
          if (items.appLogs) setLogs(items.appLogs);
          if (items.maxYears) setMaxYears(items.maxYears);
          if (items.blacklistKeywords) setBlacklist(items.blacklistKeywords);
        }
      );

      const listener = (changes: Record<string, chrome.storage.StorageChange>) => {
        if (changes.isAutoRunning) setIsRunning(!!changes.isAutoRunning.newValue);
        if (changes.appliedCount) setAppliedCount(changes.appliedCount.newValue || 0);
        if (changes.skippedCount) setSkippedCount(changes.skippedCount.newValue || 0);
        if (changes.appLogs) setLogs(changes.appLogs.newValue || []);
      };

      chrome.storage.onChanged.addListener(listener);
      return () => chrome.storage.onChanged.removeListener(listener);
    } catch (e) {}
  }, []);

  const handleToggle = () => {
    const nextState = !isRunning;
    setIsRunning(nextState);

    try {
      chrome.storage.local.set({
        isAutoRunning: nextState,
        maxYears,
        blacklistKeywords: blacklist
      });

      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0]?.id) {
          chrome.tabs.sendMessage(tabs[0].id, {
            action: 'TOGGLE_BATCH_AUTO',
            state: nextState
          });
        }
      });
    } catch (e) {}
  };

  const handleSaveFilters = async () => {
    const s = await getSettings();
    await saveSettings({ ...s, maxYears, blacklistKeywords: blacklist });
    try {
      chrome.storage.local.set({ maxYears, blacklistKeywords: blacklist });
    } catch (e) {}
  };

  const handleResetStats = () => {
    setAppliedCount(0);
    setSkippedCount(0);
    setLogs(['Stats reset. Ready.']);
    try {
      chrome.storage.local.set({ appliedCount: 0, skippedCount: 0, appLogs: ['Stats reset. Ready.'] });
    } catch (e) {}
  };

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2">
        <h2 className="text-sm font-bold text-sky-400">🤖 LinkedIn Batch Auto-Apply</h2>
        <span
          className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
            isRunning
              ? 'bg-emerald-950/80 border-emerald-500 text-emerald-300 animate-pulse'
              : 'bg-slate-800 border-slate-700 text-slate-400'
          }`}
        >
          {isRunning ? 'Running 🟢' : 'Idle ⚪'}
        </span>
      </div>

      {/* Main Trigger Card */}
      <div className="bg-slate-900/90 border border-sky-500/20 p-3 rounded-lg space-y-3 shadow-md">
        <p className="text-[11px] text-slate-300">
          Navigate to LinkedIn Jobs search with <b className="text-sky-400">"Easy Apply"</b> filter enabled, then start the loop.
        </p>

        <button
          onClick={handleToggle}
          className={`w-full py-2.5 rounded-md font-bold text-xs tracking-wide shadow-md transition ${
            isRunning
              ? 'bg-rose-600 hover:bg-rose-500 text-white'
              : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}
        >
          {isRunning ? '⏸️ Stop Batch Auto-Apply' : '▶️ Start Batch Auto-Apply'}
        </button>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-2 pt-1">
          <div className="bg-slate-950 p-2.5 rounded border border-slate-800 text-center">
            <div className="text-xl font-extrabold text-emerald-400">{appliedCount}</div>
            <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Applied</div>
          </div>
          <div className="bg-slate-950 p-2.5 rounded border border-slate-800 text-center">
            <div className="text-xl font-extrabold text-amber-400">{skippedCount}</div>
            <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Skipped / Roadblock</div>
          </div>
        </div>

        <button
          onClick={handleResetStats}
          className="text-[10px] text-slate-500 hover:text-slate-300 underline w-full text-center block pt-1"
        >
          Reset Application Counts
        </button>
      </div>

      {/* Filtering Rules */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">🎯 Filtering & Safety Rules</h3>
        
        <div>
          <label className="block text-[10px] text-slate-500">Max Experience Required (Years)</label>
          <input
            type="number"
            value={maxYears}
            min={0}
            max={30}
            onChange={(e) => {
              const val = parseInt(e.target.value, 10) || 0;
              setMaxYears(val);
            }}
            onBlur={handleSaveFilters}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
          />
        </div>

        <div>
          <label className="block text-[10px] text-slate-500">Blacklist Keywords in Job Title (Comma separated)</label>
          <input
            type="text"
            value={blacklist}
            onChange={(e) => setBlacklist(e.target.value)}
            onBlur={handleSaveFilters}
            placeholder="Senior, Staff, Principal, Lead, Manager"
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
          />
        </div>
      </div>

      {/* Live Automation Logs */}
      <div className="space-y-1">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">📋 Live Automation Activity Log</h3>
        <div className="bg-slate-950 border border-slate-800 rounded p-2.5 font-mono text-[10px] text-slate-400 max-h-36 overflow-y-auto space-y-1">
          {logs.map((l, i) => (
            <div key={i} className="leading-tight break-words">{l}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
