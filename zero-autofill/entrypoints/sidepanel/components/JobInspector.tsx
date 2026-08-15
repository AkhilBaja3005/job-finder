import React, { useState, useEffect } from 'react';
import { getProfile } from '../../../modules/storage/db';
import { calculateKeywordMatchScore } from '../../../modules/ai/matcher';

export function JobInspector() {
  const [pageInfo, setPageInfo] = useState<{ title: string; url: string; text: string } | null>(null);
  const [matchResult, setMatchResult] = useState<{ score: number; matchedKeywords: string[]; missingKeywords: string[] } | null>(null);
  const [statusMsg, setStatusMsg] = useState('');

  const inspectCurrentPage = () => {
    setStatusMsg('Scanning page...');
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTabId = tabs[0]?.id;
      const tabUrl = tabs[0]?.url || '';

      if (tabUrl.startsWith('chrome://') || tabUrl.startsWith('chrome-extension://') || tabUrl.startsWith('about:')) {
        setStatusMsg('Open a standard job portal page (e.g. Greenhouse, Lever, LinkedIn) to inspect.');
        return;
      }

      if (activeTabId) {
        chrome.tabs.sendMessage(activeTabId, { action: 'GET_PAGE_DETAILS' }, async (res) => {
          if (chrome.runtime.lastError) {
            // Programmatically inject content script into tab if dynamic matching missed it
            try {
              await chrome.scripting.executeScript({
                target: { tabId: activeTabId },
                files: ['content-scripts/content.js']
              });
              // Retry message after injection
              chrome.tabs.sendMessage(activeTabId, { action: 'GET_PAGE_DETAILS' }, async (retryRes) => {
                if (retryRes) {
                  setPageInfo(retryRes);
                  const profile = await getProfile();
                  if (profile) {
                    setMatchResult(calculateKeywordMatchScore(retryRes.text, profile));
                  }
                  setStatusMsg('');
                }
              });
            } catch (e) {
              setStatusMsg('Open a standard web page (e.g. Greenhouse, Lever, LinkedIn) to inspect.');
            }
            return;
          }
          if (res) {
            setPageInfo(res);
            const profile = await getProfile();
            if (profile) {
              const result = calculateKeywordMatchScore(res.text, profile);
              setMatchResult(result);
            }
            setStatusMsg('');
          } else {
            setStatusMsg('Could not read page details. Make sure you are on a valid tab.');
          }
        });
      }
    });
  };

  const triggerAutofill = () => {
    setStatusMsg('Triggering autofill sequence...');
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTabId = tabs[0]?.id;
      if (activeTabId) {
        chrome.tabs.sendMessage(activeTabId, { action: 'RUN_AUTOFILL' }, (res) => {
          if (chrome.runtime.lastError) {
            console.warn('[Zero-Autofill] Content script error:', chrome.runtime.lastError.message);
            setStatusMsg('⚠️ Could not run autofill on restricted tab (e.g. chrome://). Open a job application page.');
            return;
          }
          if (res?.success) {
            setStatusMsg(`✅ Autofill complete! Filled ${res.count} fields.`);
          } else {
            setStatusMsg('⚠️ Autofill completed.');
          }
        });
      }
    });
  };

  const [aiSolvedDetails, setAiSolvedDetails] = useState<Array<{ fieldId: string; label: string; answer: string }> | null>(null);

  const triggerAISolve = () => {
    setStatusMsg('🤖 AI is analyzing page form questions & candidate profile...');
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTabId = tabs[0]?.id;
      if (activeTabId) {
        chrome.tabs.sendMessage(activeTabId, { action: 'SOLVE_WITH_AI' }, (res) => {
          if (chrome.runtime.lastError) {
            setStatusMsg('⚠️ Open a standard web page to run AI auto-solve.');
            return;
          }
          if (res?.success) {
            setStatusMsg(`✨ AI Page Solve complete! Generated & filled ${res.count} answers.`);
            if (res.details) {
              setAiSolvedDetails(res.details);
            }
          } else {
            setStatusMsg('⚠️ AI Solve finished.');
          }
        });
      }
    });
  };

  useEffect(() => {
    inspectCurrentPage();
  }, []);

  const triggerUnifiedAutofill = async () => {
    setStatusMsg('⚡ Running autofill & capturing page screenshot...');
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTabId = tabs[0]?.id;
      if (!activeTabId) return;

      chrome.tabs.sendMessage(activeTabId, { action: 'RUN_AUTOFILL' }, (res) => {
        const heuristicCount = res?.count || 0;
        setStatusMsg('📸 Analyzing visual page layout & questions with Gemini Multimodal Vision...');
        
        chrome.tabs.sendMessage(activeTabId, { action: 'SOLVE_WITH_AI' }, (aiRes) => {
          if (aiRes?.success) {
            const total = heuristicCount + (aiRes.count || 0);
            setStatusMsg(`✨ Autofill & Multimodal AI Solve Complete! Filled ${total} fields (${aiRes.count} via Vision AI).`);
            if (aiRes.details) {
              setAiSolvedDetails(aiRes.details);
            }
          } else {
            setStatusMsg(`✅ Autofill finished (${heuristicCount} fields filled).`);
          }
        });
      });
    });
  };

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2">
        <h2 className="text-sm font-bold text-sky-400">🔍 Live Job Inspector</h2>
        <button
          onClick={inspectCurrentPage}
          className="bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium px-2 py-1 rounded transition text-[10px]"
        >
          🔄 Re-Scan Page
        </button>
      </div>

      {statusMsg && (
        <div className="p-2 bg-slate-900 border border-slate-800 text-sky-400 rounded text-center font-medium">
          {statusMsg}
        </div>
      )}

      {pageInfo && (
        <div className="bg-slate-900 border border-slate-800 p-3 rounded space-y-2">
          <div className="flex flex-col gap-2">
            <button
              onClick={triggerUnifiedAutofill}
              className="w-full bg-gradient-to-r from-sky-500 via-indigo-600 to-emerald-500 hover:opacity-90 text-white font-extrabold py-2.5 rounded-lg shadow-lg shadow-sky-500/25 transition transform active:scale-95 flex items-center justify-center gap-2 text-xs"
            >
              ✨ One-Click Autofill & Multimodal AI Solve
            </button>
          </div>
          
          <div className="pt-2 border-t border-slate-800">
            <h3 className="font-semibold text-slate-300 text-sm truncate">{pageInfo.title}</h3>
            <p className="text-[10px] text-slate-500 truncate">{pageInfo.url}</p>
          </div>

          {/* AI Solved Q&A Breakdown */}
          {aiSolvedDetails && aiSolvedDetails.length > 0 && (
            <div className="bg-slate-950 p-3 rounded border border-emerald-500/30 space-y-2">
              <div className="flex justify-between items-center border-b border-slate-800 pb-1.5">
                <span className="font-bold text-emerald-400 text-xs">✨ AI Generated & Filled Answers</span>
                <span className="text-[10px] text-slate-400 font-mono">{aiSolvedDetails.length} questions</span>
              </div>
              <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {aiSolvedDetails.map((item, idx) => (
                  <div key={idx} className="bg-slate-900/90 p-2 rounded border border-slate-800 space-y-1">
                    <p className="font-semibold text-[11px] text-sky-300 flex items-start gap-1">
                      <span className="text-emerald-400 shrink-0">Q{idx + 1}:</span>
                      <span>{item.label}</span>
                    </p>
                    <div className="bg-slate-950 p-1.5 rounded text-[10px] text-slate-200 font-mono whitespace-pre-wrap border border-slate-800/60">
                      {item.answer}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Match Score Badge */}
          {matchResult && (
            <div className="bg-slate-950 p-3 rounded border border-slate-800 space-y-2">
              <div className="flex justify-between items-center">
                <span className="font-semibold text-slate-400 text-[10px] uppercase">Match Score</span>
                <span className={`text-base font-bold ${matchResult.score >= 75 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {matchResult.score}%
                </span>
              </div>
              <div className="w-full bg-slate-950 h-2 rounded-full overflow-hidden">
                <div
                  className={`h-full ${matchResult.score >= 75 ? 'bg-emerald-500' : 'bg-amber-500'}`}
                  style={{ width: `${matchResult.score}%` }}
                />
              </div>

              {/* Matched Keywords */}
              <div>
                <span className="text-[10px] text-emerald-400 font-semibold">Matched Skills: </span>
                <span className="text-[10px] text-slate-400">
                  {matchResult.matchedKeywords.join(', ') || 'None'}
                </span>
              </div>
            </div>
          )}

          {/* Quick Autofill Action Button */}
          <button
            onClick={triggerUnifiedAutofill}
            className="w-full py-2 bg-gradient-to-r from-sky-500 via-indigo-600 to-emerald-500 hover:opacity-90 text-white font-bold rounded-lg shadow-lg shadow-sky-500/20 transition transform active:scale-95 text-xs"
          >
            ✨ Run One-Click Autofill & Multimodal AI Solve
          </button>
        </div>
      )}
    </div>
  );
}
