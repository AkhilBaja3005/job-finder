import React, { useState } from 'react';
import { ProfileManager } from './components/ProfileManager';
import { JobInspector } from './components/JobInspector';
import { KanbanBoard } from './components/KanbanBoard';
import { SettingsTab } from './components/SettingsTab';

export default function App() {
  const [activeTab, setActiveTab] = useState<'inspector' | 'profile' | 'kanban' | 'settings'>('inspector');

  return (
    <div className="w-full min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Header */}
      <header className="p-3 bg-slate-900 border-b border-slate-800 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <span className="text-lg">✨</span>
          <h1 className="font-extrabold text-sm bg-gradient-to-r from-sky-400 to-indigo-400 bg-clip-text text-transparent">
            Zero-Autofill
          </h1>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">v1.0.0</span>
      </header>

      {/* Navigation Tabs */}
      <nav className="flex bg-slate-900/80 border-b border-slate-800/80 p-1 gap-1 text-[11px] font-medium">
        <button
          onClick={() => setActiveTab('inspector')}
          className={`flex-1 py-1.5 rounded transition ${activeTab === 'inspector' ? 'bg-sky-600 text-white font-bold' : 'text-slate-400 hover:text-slate-200'}`}
        >
          🔍 Inspect
        </button>
        <button
          onClick={() => setActiveTab('profile')}
          className={`flex-1 py-1.5 rounded transition ${activeTab === 'profile' ? 'bg-sky-600 text-white font-bold' : 'text-slate-400 hover:text-slate-200'}`}
        >
          👤 Profile
        </button>
        <button
          onClick={() => setActiveTab('kanban')}
          className={`flex-1 py-1.5 rounded transition ${activeTab === 'kanban' ? 'bg-sky-600 text-white font-bold' : 'text-slate-400 hover:text-slate-200'}`}
        >
          📊 Kanban
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          className={`flex-1 py-1.5 rounded transition ${activeTab === 'settings' ? 'bg-sky-600 text-white font-bold' : 'text-slate-400 hover:text-slate-200'}`}
        >
          ⚙️ Settings
        </button>
      </nav>

      {/* Main Tab Content */}
      <main className="flex-1 overflow-y-auto">
        {activeTab === 'inspector' && <JobInspector />}
        {activeTab === 'profile' && <ProfileManager />}
        {activeTab === 'kanban' && <KanbanBoard />}
        {activeTab === 'settings' && <SettingsTab />}
      </main>
    </div>
  );
}
