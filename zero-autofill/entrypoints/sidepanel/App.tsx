import React, { useState } from 'react';
import { ProfileManager } from './components/ProfileManager';
import { JobInspector } from './components/JobInspector';
import { BatchApplyTab } from './components/BatchApplyTab';
import { KanbanBoard } from './components/KanbanBoard';
import { SettingsTab } from './components/SettingsTab';

export default function App() {
  const [activeTab, setActiveTab] = useState<'inspector' | 'batch' | 'profile' | 'kanban' | 'settings'>('inspector');

  return (
    <div className="w-full min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Header */}
      <header className="p-3 bg-slate-900 border-b border-slate-800 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <span className="text-base">⚡</span>
          <div>
            <h1 className="font-extrabold text-xs bg-gradient-to-r from-sky-400 to-indigo-400 bg-clip-text text-transparent leading-tight">
              Job Finder ATS Tailor
            </h1>
            <span className="text-[9px] text-slate-400 block -mt-0.5">AI AutoFill & Batch Apply Copilot</span>
          </div>
        </div>
        <span className="text-[10px] text-sky-400 font-mono bg-sky-950/70 border border-sky-800 px-1.5 py-0.5 rounded">v2.0</span>
      </header>

      {/* Navigation Tabs */}
      <nav className="flex bg-slate-900/80 border-b border-slate-800/80 p-1 gap-1 text-[10px] font-medium">
        <button
          onClick={() => setActiveTab('inspector')}
          className={`flex-1 py-1.5 rounded transition text-center ${
            activeTab === 'inspector' ? 'bg-sky-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          🔍 Inspect
        </button>
        <button
          onClick={() => setActiveTab('batch')}
          className={`flex-1 py-1.5 rounded transition text-center ${
            activeTab === 'batch' ? 'bg-sky-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          🤖 Batch
        </button>
        <button
          onClick={() => setActiveTab('profile')}
          className={`flex-1 py-1.5 rounded transition text-center ${
            activeTab === 'profile' ? 'bg-sky-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          👤 Profile
        </button>
        <button
          onClick={() => setActiveTab('kanban')}
          className={`flex-1 py-1.5 rounded transition text-center ${
            activeTab === 'kanban' ? 'bg-sky-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          📊 Kanban
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          className={`flex-1 py-1.5 rounded transition text-center ${
            activeTab === 'settings' ? 'bg-sky-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          ⚙️ Settings
        </button>
      </nav>

      {/* Main Tab Content */}
      <main className="flex-1 overflow-y-auto">
        {activeTab === 'inspector' && <JobInspector />}
        {activeTab === 'batch' && <BatchApplyTab />}
        {activeTab === 'profile' && <ProfileManager />}
        {activeTab === 'kanban' && <KanbanBoard />}
        {activeTab === 'settings' && <SettingsTab />}
      </main>
    </div>
  );
}
