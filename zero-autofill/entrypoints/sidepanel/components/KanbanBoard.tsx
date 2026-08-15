import React, { useState, useEffect } from 'react';
import { db, JobApplication } from '../../../modules/storage/db';

export function KanbanBoard() {
  const [applications, setApplications] = useState<JobApplication[]>([]);

  const loadApplications = async () => {
    const apps = await db.applications.reverse().toArray();
    setApplications(apps);
  };

  useEffect(() => {
    loadApplications();
  }, []);

  const updateStatus = async (id: number, status: JobApplication['status']) => {
    await db.applications.update(id, { status });
    loadApplications();
  };

  const columns: Array<JobApplication['status']> = ['Saved', 'Applied', 'Interviewing', 'Offer', 'Rejected'];

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2">
        <h2 className="text-sm font-bold text-sky-400">📊 Application Kanban Board</h2>
        <span className="text-[10px] text-slate-500">{applications.length} Total</span>
      </div>

      <div className="space-y-3">
        {columns.map((col) => {
          const colApps = applications.filter(a => a.status === col);
          return (
            <div key={col} className="bg-slate-900 p-3 rounded border border-slate-800 space-y-2">
              <div className="flex justify-between items-center border-b border-slate-800/60 pb-1">
                <span className="font-semibold text-slate-300 text-[11px] uppercase tracking-wider">{col}</span>
                <span className="bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded text-[10px]">{colApps.length}</span>
              </div>

              {colApps.length === 0 ? (
                <p className="text-[10px] text-slate-600 italic">No applications in {col}</p>
              ) : (
                <div className="space-y-2">
                  {colApps.map((app) => (
                    <div key={app.id} className="bg-slate-950 p-2.5 rounded border border-slate-800 space-y-1">
                      <div className="flex justify-between items-start">
                        <span className="font-bold text-slate-200 truncate max-w-[140px]">{app.company}</span>
                        <span className="text-[9px] text-slate-500">{app.appliedDate}</span>
                      </div>
                      <p className="text-[10px] text-slate-400 truncate">{app.position}</p>

                      <div className="flex gap-1 pt-1">
                        {columns.map((st) => (
                          <button
                            key={st}
                            onClick={() => app.id && updateStatus(app.id, st)}
                            className={`text-[9px] px-1.5 py-0.5 rounded transition ${
                              app.status === st
                                ? 'bg-sky-600 text-white font-bold'
                                : 'bg-slate-900 text-slate-500 hover:text-slate-300'
                            }`}
                          >
                            {st[0]}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
