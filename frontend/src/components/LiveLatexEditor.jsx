import React, { useState, useEffect, useRef, useCallback } from 'react';

/**
 * LiveLatexEditor
 * Real-time split-screen or full-width LaTeX editor with:
 * - Editable textarea with synchronized line numbers
 * - Debounced automatic compilation (750ms) to /compile_latex
 * - Inline PDF preview viewer via blob URL
 * - Error reporting HUD with line context
 * - Action buttons: Recompile now, Download .tex, Open in Overleaf, Set as Master
 */
export default function LiveLatexEditor({
  initialCode = '',
  onChange,
  onSaveMaster,
  onOpenOverleaf,
  apiBase = 'http://localhost:8000',
  authToken = '',
  candidateName = 'Resume',
  jobTitle = '',
  company = ''
}) {
  const [code, setCode] = useState(initialCode);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState(null);
  const [pageCount, setPageCount] = useState(1);
  const [viewMode, setViewMode] = useState('split'); // 'split' | 'code' | 'preview'
  const [copied, setCopied] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);
  const [activeLine, setActiveLine] = useState(1);

  const textareaRef = useRef(null);
  const gutterRef = useRef(null);
  const debounceTimerRef = useRef(null);
  const currentBlobUrlRef = useRef(null);

  // Sync initialCode if changed externally
  useEffect(() => {
    if (initialCode && initialCode !== code) {
      setCode(initialCode);
    }
  }, [initialCode]);

  // Clean up object URLs on unmount
  useEffect(() => {
    return () => {
      if (currentBlobUrlRef.current) {
        URL.revokeObjectURL(currentBlobUrlRef.current);
      }
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  // Synchronized scroll between textarea and line gutter
  const handleScroll = () => {
    if (textareaRef.current && gutterRef.current) {
      gutterRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  };

  // Track cursor line
  const handleKeyUp = () => {
    if (textareaRef.current) {
      const pos = textareaRef.current.selectionStart;
      const linesBefore = textareaRef.current.value.substring(0, pos).split('\n');
      setActiveLine(linesBefore.length);
    }
  };

  // Compile LaTeX code via backend tectonic endpoint
  const compileLatex = useCallback(async (latexText) => {
    if (!latexText || !latexText.trim()) return;

    setCompiling(true);
    setCompileError(null);

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const res = await fetch(`${apiBase}/compile_latex`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ latex_code: latexText })
      });

      if (!res.ok) {
        let errMsg = 'LaTeX compilation failed';
        try {
          const errData = await res.json();
          errMsg = errData.detail || errMsg;
        } catch (_) {
          errMsg = await res.text();
        }
        setCompileError(errMsg);
        setCompiling(false);
        return;
      }

      const blob = await res.blob();
      const newBlobUrl = URL.createObjectURL(blob);

      if (currentBlobUrlRef.current) {
        URL.revokeObjectURL(currentBlobUrlRef.current);
      }
      currentBlobUrlRef.current = newBlobUrl;
      setPdfUrl(newBlobUrl);
      setCompileError(null);

      // Check authoritative X-Page-Count header sent by backend pypdf inspector
      const headerPages = parseInt(res.headers.get('X-Page-Count') || res.headers.get('x-page-count'), 10);
      if (!isNaN(headerPages) && headerPages > 0) {
        setPageCount(headerPages);
      } else {
        // Fallback: Scan PDF text buffer for /Type /Page occurrences
        try {
          const textChunk = await blob.text();
          const matches = textChunk.match(/\/Type\s*\/Page\b/g);
          if (matches && matches.length > 0) {
            setPageCount(matches.length);
          } else {
            setPageCount(1);
          }
        } catch (_) {
          setPageCount(1);
        }
      }
    } catch (err) {
      setCompileError(err.message || 'Connection error while compiling LaTeX');
    } finally {
      setCompiling(false);
    }
  }, [apiBase, authToken]);

  // Debounced auto-compilation on code changes
  const handleCodeChange = (e) => {
    const newCode = e.target.value;
    setCode(newCode);
    if (onChange) onChange(newCode);

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = setTimeout(() => {
      compileLatex(newCode);
    }, 750);
  };

  // Compile on first load if we don't have a preview yet
  useEffect(() => {
    if (code && !pdfUrl && !compiling) {
      compileLatex(code);
    }
  }, [code, pdfUrl, compiling, compileLatex]);

  // Tab key support in textarea
  const handleKeyDown = (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = e.target.selectionStart;
      const end = e.target.selectionEnd;
      const val = e.target.value;
      const updated = val.substring(0, start) + '  ' + val.substring(end);
      setCode(updated);
      if (onChange) onChange(updated);
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.selectionStart = textareaRef.current.selectionEnd = start + 2;
        }
      }, 0);
    }
  };

  const lines = (code || '').split('\n');

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadTex = () => {
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${candidateName.replace(/\s+/g, '_')}_resume.tex`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSaveToMaster = async () => {
    if (onSaveMaster) {
      setSaveStatus('Saving...');
      try {
        await onSaveMaster(code);
        setSaveStatus('Saved!');
        setTimeout(() => setSaveStatus(null), 2500);
      } catch (err) {
        setSaveStatus(`Failed: ${err.message}`);
        setTimeout(() => setSaveStatus(null), 3500);
      }
    }
  };

  return (
    <div
      className="live-latex-workspace"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: '620px',
        background: '#090D16',
        borderRadius: '12px',
        border: '1px solid #1E293B',
        overflow: 'hidden',
        boxShadow: '0 8px 30px rgba(0,0,0,0.5)'
      }}
    >
      {/* Top Controls Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 16px',
          background: '#0D1424',
          borderBottom: '1px solid #1E293B',
          gap: '12px',
          flexWrap: 'wrap'
        }}
      >
        {/* Left: Document Info & Live Status Badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{
            width: '9px',
            height: '9px',
            borderRadius: '50%',
            background: compiling ? '#F59E0B' : compileError ? '#EF4444' : pageCount > 1 ? '#F97316' : '#10B981',
            boxShadow: compiling ? '0 0 8px #F59E0B' : compileError ? '0 0 8px #EF4444' : pageCount > 1 ? '0 0 8px #F97316' : '0 0 8px #10B981',
            transition: 'all 0.3s ease'
          }} />
          <span style={{ fontWeight: 600, color: '#F1F5F9', fontSize: '0.82rem', fontFamily: 'var(--font-mono)' }}>
            resume.tex
          </span>
          <span style={{
            fontSize: '0.72rem',
            padding: '2px 8px',
            borderRadius: '6px',
            background: compiling ? 'rgba(245, 158, 11, 0.15)' : compileError ? 'rgba(239, 68, 68, 0.15)' : pageCount > 1 ? 'rgba(249, 115, 22, 0.18)' : 'rgba(16, 185, 129, 0.15)',
            color: compiling ? '#FBBF24' : compileError ? '#F87171' : pageCount > 1 ? '#FB923C' : '#34D399',
            border: `1px solid ${compiling ? 'rgba(245, 158, 11, 0.3)' : compileError ? 'rgba(239, 68, 68, 0.3)' : pageCount > 1 ? 'rgba(249, 115, 22, 0.4)' : 'rgba(16, 185, 129, 0.3)'}`,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px'
          }}>
            {compiling ? (
              <>
                <svg className="animate-spin" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <circle cx="12" cy="12" r="10" strokeOpacity="0.25"></circle>
                  <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round"></path>
                </svg>
                Compiling...
              </>
            ) : compileError ? (
              'Compilation Error'
            ) : pageCount > 1 ? (
              `⚠️ ${pageCount} Pages (Exceeds 1-Page Budget)`
            ) : (
              'Ready • 1 Page (Strict Budget ✅)'
            )}
          </span>
        </div>

        {/* Center: View Switcher (Split / Code Only / Preview Only) */}
        <div style={{
          display: 'flex',
          background: 'rgba(255,255,255,0.04)',
          padding: '2px',
          borderRadius: '8px',
          border: '1px solid rgba(255,255,255,0.08)'
        }}>
          {[
            { id: 'split', label: 'Split View' },
            { id: 'code', label: 'Code Only' },
            { id: 'preview', label: 'PDF Preview' }
          ].map((mode) => (
            <button
              key={mode.id}
              onClick={() => setViewMode(mode.id)}
              style={{
                background: viewMode === mode.id ? '#2563EB' : 'transparent',
                color: viewMode === mode.id ? '#FFFFFF' : '#94A3B8',
                border: 'none',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '0.74rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              {mode.label}
            </button>
          ))}
        </div>

        {/* Right: Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'nowrap' }}>
          <button
            className="btn btn-secondary"
            style={{ padding: '4px 10px', fontSize: '0.74rem', height: '28px', gap: '5px' }}
            onClick={() => compileLatex(code)}
            disabled={compiling}
            title="Force re-compile now"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
            Recompile
          </button>

          <button
            className="btn btn-secondary"
            style={{ padding: '4px 10px', fontSize: '0.74rem', height: '28px', gap: '5px' }}
            onClick={handleCopy}
            title="Copy LaTeX source code"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            {copied ? 'Copied!' : 'Copy'}
          </button>

          <button
            className="btn btn-secondary"
            style={{ padding: '4px 10px', fontSize: '0.74rem', height: '28px', gap: '5px' }}
            onClick={handleDownloadTex}
            title="Download .tex source file"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            .tex
          </button>

          {onOpenOverleaf && (
            <button
              className="btn btn-secondary"
              style={{ padding: '4px 10px', fontSize: '0.74rem', height: '28px', gap: '5px', color: '#10B981' }}
              onClick={() => onOpenOverleaf(code)}
              title="Open project directly in Overleaf"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                <polyline points="15 3 21 3 21 9"></polyline>
                <line x1="10" y1="14" x2="21" y2="3"></line>
              </svg>
              Overleaf
            </button>
          )}

          {onSaveMaster && (
            <button
              className="btn btn-secondary"
              style={{
                padding: '4px 12px',
                fontSize: '0.74rem',
                height: '28px',
                gap: '5px',
                background: 'rgba(16, 185, 129, 0.15)',
                color: '#34D399',
                borderColor: 'rgba(16, 185, 129, 0.35)',
                fontWeight: 600
              }}
              onClick={handleSaveToMaster}
              title="Save current LaTeX code as Master Resume profile"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                <polyline points="17 21 17 13 7 13 7 21"></polyline>
                <polyline points="7 3 7 8 15 8"></polyline>
              </svg>
              {saveStatus || 'Save to Master'}
            </button>
          )}
        </div>
      </div>

      {/* Compile Error Drawer / Banner */}
      {compileError && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            borderBottom: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#FCA5A5',
            padding: '8px 16px',
            fontSize: '0.75rem',
            fontFamily: 'var(--font-mono)',
            maxHeight: '120px',
            overflowY: 'auto',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '10px'
          }}
        >
          <span style={{ color: '#EF4444', fontWeight: 'bold' }}>⚠️ Compile Error:</span>
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', flex: 1 }}>{compileError}</pre>
          <button
            onClick={() => setCompileError(null)}
            style={{ background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer', padding: 0 }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Split Body */}
      <div
        style={{
          display: 'flex',
          flex: 1,
          minHeight: 0,
          position: 'relative'
        }}
      >
        {/* Left Pane: Code Editor */}
        {(viewMode === 'split' || viewMode === 'code') && (
          <div
            style={{
              flex: viewMode === 'split' ? '1 1 50%' : '1 1 100%',
              display: 'flex',
              position: 'relative',
              background: '#090D16',
              borderRight: viewMode === 'split' ? '1px solid #1E293B' : 'none',
              overflow: 'hidden'
            }}
          >
            {/* Line Number Gutter */}
            <div
              ref={gutterRef}
              style={{
                width: '48px',
                userSelect: 'none',
                padding: '14px 8px 14px 0',
                textAlign: 'right',
                color: '#475569',
                background: '#070A12',
                borderRight: '1px solid #1E293B',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.78rem',
                lineHeight: '1.6',
                overflow: 'hidden',
                flexShrink: 0
              }}
            >
              {lines.map((_, i) => (
                <div
                  key={i}
                  style={{
                    color: activeLine === i + 1 ? '#38BDF8' : '#475569',
                    fontWeight: activeLine === i + 1 ? 700 : 400
                  }}
                >
                  {i + 1}
                </div>
              ))}
            </div>

            {/* Code Input Textarea */}
            <textarea
              ref={textareaRef}
              value={code}
              onChange={handleCodeChange}
              onScroll={handleScroll}
              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
              onClick={handleKeyUp}
              spellCheck="false"
              style={{
                flex: 1,
                width: '100%',
                height: '100%',
                padding: '14px 16px',
                background: 'transparent',
                color: '#E2E8F0',
                border: 'none',
                outline: 'none',
                resize: 'none',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.78rem',
                lineHeight: '1.6',
                whiteSpace: 'pre',
                overflowWrap: 'normal',
                overflowX: 'auto',
                overflowY: 'auto',
                tabSize: 2
              }}
              placeholder="Enter or edit LaTeX code here..."
            />
          </div>
        )}

        {/* Right Pane: Live PDF Preview */}
        {(viewMode === 'split' || viewMode === 'preview') && (
          <div
            style={{
              flex: viewMode === 'split' ? '1 1 50%' : '1 1 100%',
              display: 'flex',
              flexDirection: 'column',
              background: '#0F172A',
              position: 'relative',
              overflow: 'hidden'
            }}
          >
            {pdfUrl ? (
              <iframe
                src={`${pdfUrl}#toolbar=0&navpanes=0&scrollbar=1&view=FitH`}
                title="Live LaTeX Resume Preview"
                style={{
                  width: '100%',
                  height: '100%',
                  border: 'none',
                  background: '#1E293B'
                }}
              />
            ) : (
              <div
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#64748B',
                  gap: '12px'
                }}
              >
                {compiling ? (
                  <>
                    <svg className="animate-spin" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#38BDF8" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" strokeOpacity="0.25"></circle>
                      <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round"></path>
                    </svg>
                    <span style={{ fontSize: '0.85rem' }}>Compiling PDF preview with Tectonic...</span>
                  </>
                ) : (
                  <>
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    <span style={{ fontSize: '0.85rem' }}>No PDF compiled yet. Edit code or click Recompile.</span>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer Info Bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 16px',
          background: '#070A12',
          borderTop: '1px solid #1E293B',
          fontSize: '0.7rem',
          color: '#64748B',
          fontFamily: 'var(--font-mono)'
        }}
      >
        <div>
          <span>Line: {activeLine}</span>
          <span style={{ margin: '0 8px' }}>•</span>
          <span>Total: {lines.length} lines</span>
          <span style={{ margin: '0 8px' }}>•</span>
          <span>{code.length} characters</span>
        </div>
        <div>
          <span>Tectonic XeLaTeX Engine (Live Preview)</span>
        </div>
      </div>
    </div>
  );
}
