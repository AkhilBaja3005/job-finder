import React, { useState, useEffect } from 'react';

export default function DocsGuide({ user, userToken, onDownloadExtension, onNavigateMode }) {
  const [activeSection, setActiveSection] = useState('quickstart');
  const [copiedKey, setCopiedKey] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  const syncKey = user?.sync_code || (userToken && userToken !== 'guest' ? userToken.slice(0, 6).toUpperCase() : 'GABY48');
  const serverUrl = window.location.origin.includes('localhost') ? 'https://www.job-finder.space' : window.location.origin;

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '');
      if (hash) setActiveSection(hash);
    };
    if (window.location.hash) handleHashChange();
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleCopy = (text, type) => {
    navigator.clipboard.writeText(text);
    if (type === 'key') {
      setCopiedKey(true);
      setTimeout(() => setCopiedKey(false), 2000);
    } else if (type === 'url') {
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2000);
    }
  };

  const navItems = [
    { id: 'quickstart', label: 'Quickstart', icon: '' },
    { id: 'extension', label: 'Chrome Extension v3.0', icon: '' },
    { id: 'sync-key', label: 'Sync Key & Pairing', icon: '' },
    { id: 'master-resume', label: 'Multi-Archetypes & Master Resume', icon: '' },
    { id: 'ats-scoring', label: 'ATS Matrix & Keyword Badges', icon: '' },
    { id: 'latex-engine', label: 'XeLaTeX Engine & Code Viewer', icon: '' },
    { id: 'shortcuts', label: 'Keyboard Shortcuts', icon: '' },
    { id: 'autofill', label: 'In-Page AI Autofill & PDF Drop', icon: '' },
    { id: 'discovery', label: 'Job Discovery Search', icon: '' },
    { id: 'mcp-skills', label: 'MCP Server & Universal Skills', icon: '' },
    { id: 'api-setup', label: 'Backend & Environment Setup', icon: '' },
  ];

  return (
    <div className="docs-container" style={{
      maxWidth: '1280px',
      margin: '0 auto',
      padding: '24px 16px 80px',
      color: '#e2e8f0',
      fontFamily: 'Inter, system-ui, -apple-system, sans-serif'
    }}>
      {/* Top Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.12) 0%, rgba(129, 140, 248, 0.08) 100%)',
        border: '1px solid rgba(56, 189, 248, 0.25)',
        borderRadius: '16px',
        padding: '32px 28px',
        marginBottom: '32px',
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: '20px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)'
      }}>
        <div style={{ maxWidth: '680px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
            <span style={{
              background: 'linear-gradient(135deg, #38bdf8, #818cf8)',
              color: '#090d16',
              fontSize: '0.72rem',
              fontWeight: 800,
              padding: '3px 8px',
              borderRadius: '6px',
              textTransform: 'uppercase',
              letterSpacing: '0.06em'
            }}>Documentation & Setup Guide</span>
            <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>v3.1.0 (Production)</span>
          </div>
          <h1 style={{
            fontSize: '2rem',
            fontWeight: 800,
            margin: '0 0 8px',
            background: 'linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent'
          }}>
            AI Job Finder & ATS Tailor Setup
          </h1>
          <p style={{ color: '#94a3b8', fontSize: '0.95rem', lineHeight: 1.6, margin: 0 }}>
            Master documentation covering zero-config extension installation, deterministic ATS scoring, single-page LaTeX tailoring, persistent Chrome Side Panel, and automated job discovery.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          {onDownloadExtension && (
            <button
              onClick={onDownloadExtension}
              style={{
                background: 'linear-gradient(135deg, #38bdf8 0%, #0284c7 100%)',
                color: '#ffffff',
                border: 'none',
                padding: '12px 20px',
                borderRadius: '10px',
                fontWeight: 700,
                fontSize: '0.92rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: '0 4px 16px rgba(56, 189, 248, 0.35)',
                transition: 'all 0.2s ease'
              }}
            >
              Download Extension (.zip)
            </button>
          )}
          {onNavigateMode && (
            <button
              onClick={() => onNavigateMode('tailor')}
              style={{
                background: 'rgba(255, 255, 255, 0.06)',
                color: '#f8fafc',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                padding: '12px 18px',
                borderRadius: '10px',
                fontWeight: 600,
                fontSize: '0.92rem',
                cursor: 'pointer',
                transition: 'all 0.2s ease'
              }}
            >
              Open Dashboard →
            </button>
          )}
        </div>
      </div>

      {/* Main Grid: Sidebar TOC + Content Area */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: '32px' }} className="docs-grid">
        
        {/* Navigation Sidebar */}
        <div style={{ position: 'sticky', top: '24px', height: 'fit-content' }}>
          <div style={{
            background: 'rgba(15, 23, 42, 0.75)',
            backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '14px',
            padding: '16px 12px',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)'
          }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '0 12px 10px' }}>
              Topics
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {navItems.map((item) => {
                const isActive = activeSection === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setActiveSection(item.id);
                      window.location.hash = item.id;
                      const el = document.getElementById(item.id);
                      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      padding: '10px 14px',
                      borderRadius: '8px',
                      border: 'none',
                      background: isActive ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                      color: isActive ? '#38bdf8' : '#94a3b8',
                      fontWeight: isActive ? 700 : 500,
                      fontSize: '0.88rem',
                      textAlign: 'left',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Quick Credentials Box */}
            <div style={{
              marginTop: '20px',
              padding: '14px',
              background: 'rgba(2, 6, 23, 0.6)',
              borderRadius: '10px',
              border: '1px solid rgba(56, 189, 248, 0.2)'
            }}>
              <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#38bdf8', marginBottom: '6px', display: 'flex', justifyContent: 'space-between' }}>
                <span>YOUR SYNC KEY</span>
                <span style={{ color: '#10b981' }}>● Active</span>
              </div>
              <div style={{
                fontFamily: 'monospace',
                fontSize: '1.1rem',
                fontWeight: 800,
                letterSpacing: '0.15em',
                color: '#f8fafc',
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}>
                <span>{syncKey}</span>
                <button
                  onClick={() => handleCopy(syncKey, 'key')}
                  style={{
                    background: 'rgba(56, 189, 248, 0.2)',
                    border: 'none',
                    color: '#38bdf8',
                    padding: '3px 8px',
                    borderRadius: '4px',
                    fontSize: '0.72rem',
                    cursor: 'pointer'
                  }}
                >
                  {copiedKey ? '✓ Copied' : 'Copy'}
                </button>
              </div>
              <div style={{ fontSize: '0.72rem', color: '#64748b', wordBreak: 'break-all' }}>
                Backend: <span style={{ color: '#cbd5e1' }}>{serverUrl}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Content Stream */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '48px' }}>
          
          {/* SECTION: Quickstart */}
          <section id="quickstart" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Quickstart Workflow</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '20px' }}>
              Follow these 6 streamlined steps to connect your master resume with live job postings, tailor ATS-optimized LaTeX resumes, and auto-fill applications.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
              {[
                { step: '1', title: 'Upload & Lock Master Resume', desc: 'Upload your .pdf, .docx, or native .tex file in the Master tab to extract and preserve your exact skill categories, experiences, and metrics.' },
                { step: '2', title: 'Pair Chrome Extension', desc: 'Download the pre-baked zip package and unpack it in chrome://extensions. Your 6-digit Sync Key pairs the browser side panel automatically.' },
                { step: '3', title: 'Browse Any Career Portal', desc: 'Navigate to LinkedIn, Ashby, Greenhouse, Lever, Workday, or Indeed. The persistent Side Panel auto-extracts the job description in real time.' },
                { step: '4', title: 'Review Deterministic ATS Fit', desc: 'Inspect your calculated ATS score, required vs. preferred keywords, missing skills chips, and recruiter seniority alignment before tailoring.' },
                { step: '5', title: '1-Click LaTeX Tailor & Preview', desc: 'Generate a verified 1-page LaTeX PDF resume with XeLaTeX/Tectonic budgeting, live syntax editor, and optional Overleaf sync.' },
                { step: '6', title: 'In-Page Auto-Fill & Outreach', desc: 'Use inline "✨ AI Answer" and auto-fill buttons to complete form fields instantly, or copy tailored 3-sentence LinkedIn recruiter InMails.' }
              ].map((c) => (
                <div key={c.step} style={{
                  background: 'rgba(15, 23, 42, 0.6)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '12px',
                  padding: '20px',
                  position: 'relative'
                }}>
                  <div style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    background: 'linear-gradient(135deg, #38bdf8, #0284c7)',
                    color: '#ffffff',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 800,
                    fontSize: '0.9rem',
                    marginBottom: '14px'
                  }}>{c.step}</div>
                  <h3 style={{ fontSize: '1.05rem', fontWeight: 700, margin: '0 0 6px', color: '#f8fafc' }}>{c.title}</h3>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>{c.desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* SECTION: Chrome Extension v3.1.0 */}
          <section id="extension" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Chrome Extension v3.1.0 (Side Panel & Automation)</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '20px' }}>
              The extension uses Chrome's native <strong>Manifest V3 Persistent Side Panel API</strong>. It docks seamlessly to the right side of your browser and stays open as you switch tabs, click links, and fill out application forms.
            </p>

            {/* Installation Steps Card */}
            <div style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '14px',
              padding: '24px',
              marginBottom: '20px'
            }}>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 700, margin: '0 0 16px', color: '#38bdf8' }}>
                Zero-Config Installation Guide
              </h3>
              <ol style={{ margin: 0, paddingLeft: '20px', color: '#cbd5e1', lineHeight: 1.8, fontSize: '0.92rem' }}>
                <li>
                  Click the <strong>"Download Extension (.zip)"</strong> button in the dashboard header or on this page. Your personalized 6-digit Sync Key (<code>{syncKey}</code>) and server endpoint (<code>{serverUrl}</code>) are automatically pre-baked inside.
                </li>
                <li>Extract / Unzip the downloaded <code>job-finder-extension.zip</code> file to a folder on your computer.</li>
                <li>Open Google Chrome (or Brave, Edge, Arc) and navigate to <code>chrome://extensions/</code> in the URL bar.</li>
                <li>Turn on the <strong>"Developer mode"</strong> toggle in the top-right corner.</li>
                <li>Click <strong>"Load unpacked"</strong> in the top-left corner and select the extracted extension folder.</li>
                <li>Click the Extension puzzle icon in your browser toolbar and click <strong>Job Finder ATS Tailor</strong> to open the Persistent Side Panel!</li>
              </ol>
            </div>

            {/* In-Page Capabilities (6 Core Features) */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>Live Toolbar ATS Badge</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Displays your real-time ATS match percentage (e.g. <code>94%</code>, <code>76%</code>) right on the browser toolbar icon as you navigate job listings without needing to open the side panel.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>1-Click File Auto-Attach</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Click <code>Attach PDF</code> in the side panel to compile and programmatically inject your tailored PDF into ATS dropzones on Ashby, Greenhouse, Lever, and Workday via DataTransfer.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>Live Tab Sync & Rescan</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Switching tabs automatically scans the newly active job posting. If you edit custom job details, clicking <code>Rescan Tab</code> clears stale cache and re-extracts the live page DOM.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>1-Click Email Package</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Sends a formatted delivery email with the compiled PDF attached, ATS score breakdown, role title, company name, and direct Overleaf editing links straight to your inbox.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>Offline Resilience & Caching</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Automatically falls back to local storage and in-memory caches when offline or during transient server blips, preserving your tailoring history and ATS metrics without disruption.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '20px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>Multimodal Screening AI Answers</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Injects inline <code>✨ AI Answer</code> buttons beside open-ended essay questions on live job application forms, synthesizing grounded answers tailored to the company culture.
                </p>
              </div>
            </div>
          </section>

          {/* SECTION: Sync Key & Pairing */}
          <section id="sync-key" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Sync Key & Web-to-Extension Pairing</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Your 6-digit Sync Key provides a lightweight, secure handshake between the Web Dashboard and the Chrome Extension without requiring repetitive email/password logins.
            </p>

            <div style={{
              background: 'rgba(15, 23, 42, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '14px',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px'
            }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '20px', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    Permanent Sync Code
                  </div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 800, letterSpacing: '0.12em', color: '#ffffff', fontFamily: 'monospace' }}>
                    {syncKey}
                  </div>
                </div>
                <button
                  onClick={() => handleCopy(syncKey, 'key')}
                  style={{
                    background: 'rgba(56, 189, 248, 0.15)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    color: '#38bdf8',
                    padding: '8px 16px',
                    borderRadius: '8px',
                    fontWeight: 700,
                    fontSize: '0.85rem',
                    cursor: 'pointer'
                  }}
                >
                  {copiedKey ? '✓ Copied to Clipboard' : 'Copy Sync Key'}
                </button>
              </div>

              <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '16px', color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.6 }}>
                <strong>Automatic Broadcast:</strong> Whenever you upload a new resume or update your profile in the Web Dashboard, the dashboard broadcasts your profile updates to any active extension side panels automatically.
              </div>
            </div>
          </section>

          {/* SECTION: Multi-Archetypes & Master Resume */}
          <section id="master-resume" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Multi-Archetype Profiles & Category Lockdown</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Store multiple distinct master resumes (e.g., <strong>GenAI Systems Engineer</strong>, <strong>Data Scientist</strong>, <strong>Backend SWE</strong>) and toggle the active baseline for target jobs.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '14px' }}>
              {[
                { name: 'Languages', example: 'Python, SQL, C++, Java' },
                { name: 'AI/ML & GenAI', example: 'LLMs, RAG, Anomaly Detection, XGBoost, Computer Vision' },
                { name: 'Data & Platforms', example: 'PySpark, Azure OpenAI, Cloudera ML, PostgreSQL' },
                { name: 'Software & Infrastructure', example: 'Docker, Rancher, RabbitMQ, Jenkins, Git, AST Parsing' }
              ].map((cat) => (
                <div key={cat.name} style={{
                  background: 'rgba(15, 23, 42, 0.5)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '10px',
                  padding: '16px'
                }}>
                  <div style={{ fontSize: '0.92rem', fontWeight: 700, color: '#38bdf8', marginBottom: '4px' }}>{cat.name}</div>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8', lineHeight: 1.5 }}>{cat.example}</div>
                </div>
              ))}
            </div>
          </section>

          {/* SECTION: ATS Scoring & Tailoring Strategies */}
          <section id="ats-scoring" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>ATS Scoring, Keyword Matrix & Strategies</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Choose your tailoring strategy and interact directly with our deterministic keyword matrix to produce an ATS-optimized, strictly 1-page PDF.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#38bdf8', marginBottom: '6px' }}>Strict Conservative</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Preserves original bullet structure verbatim and only replaces technical keywords where direct equivalents exist.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#34d399', marginBottom: '6px' }}>Balanced (Recommended)</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Aligns terminology, weaves missing target skills, and highlights relevant systems while strictly preserving candidate facts.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f59e0b', marginBottom: '6px' }}>Impact-Driven</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Emphasizes business throughput, latency reductions, scalability, and measurable ROI metrics in every bullet point.
                </p>
              </div>
            </div>

            <div style={{
              background: 'rgba(15, 23, 42, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '14px',
              padding: '24px',
              marginTop: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px'
            }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '20px' }}>
                <div>
                  <h4 style={{ color: '#10b981', margin: '0 0 8px', fontSize: '1rem' }}>✓ Interactive Keyword Pill Matrix</h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                    Matched keywords render as soft emerald pills with checkmarks. Missing keywords render as dashed amber badges with a <code>+ Add to LaTeX</code> action that immediately recalculates the projected ATS score in real-time.
                  </p>
                </div>
                <div>
                  <h4 style={{ color: '#38bdf8', margin: '0 0 8px', fontSize: '1rem' }}>✓ Multi-Pass Page Budgeting</h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                    If a tailored resume spills onto 2 pages, the backend dynamically calculates linespread scaling (0.95 down to 0.78) and section spacing to guarantee a strictly 1-page PDF.
                  </p>
                </div>
                <div>
                  <h4 style={{ color: '#818cf8', margin: '0 0 8px', fontSize: '1rem' }}>✓ Deterministic Keyword Matching</h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                    Identifies hard technical requirements, preferred qualifications, seniority levels, and calculates timeline flattening to prevent duplicate date inflation.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* SECTION: XeLaTeX Engine & Code Viewer */}
          <section id="latex-engine" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>XeLaTeX Engine, Fonts & Syntax Viewer</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Every resume is rendered using the modern <strong>XeLaTeX</strong> typesetting engine with <code>TeX Gyre Termes</code> typography and dual-file compiler configuration for seamless local and Overleaf builds.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '20px' }}>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1rem', fontWeight: 700, color: '#38bdf8', marginBottom: '6px' }}>
                  XeLaTeX & TeX Gyre Termes
                </div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Resumes compile under <code>xelatex</code> with OpenType font support, providing crisp micro-typography and authentic font weights without missing-glyph errors.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1rem', fontWeight: 700, color: '#34d399', marginBottom: '6px' }}>
                  Dual Overleaf Compiler Directives
                </div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Exported ZIP packages include both <code>latexmkrc</code> (<code>$pdf_mode = 5; $xelatex = 'xelatex ...'</code>) and <code>.latexmkrc</code> so Overleaf automatically selects XeLaTeX by default.
                </p>
              </div>

              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1rem', fontWeight: 700, color: '#a78bfa', marginBottom: '6px' }}>
                  Code Viewer with Line Gutters
                </div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Toggle to <code>TeX Code</code> mode to inspect your LaTeX with line numbers, color-coded TeX macros (blue), comments (green), and braces (amber), plus 1-click clipboard copy.
                </p>
              </div>
            </div>
          </section>

          {/* SECTION: Keyboard Shortcuts */}
          <section id="shortcuts" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Global Keyboard Shortcuts</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Accelerate your workflow with first-class keyboard navigation designed for developers:
            </p>

            <div style={{
              background: 'rgba(15, 23, 42, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '14px',
              padding: '20px'
            }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '14px' }}>
                {[
                  { keys: '⌘ / Ctrl + Enter', desc: 'Trigger 1-click ATS Job Analysis & Tailoring' },
                  { keys: '⌘ / Ctrl + S', desc: 'Save current candidate profile snapshot / archetype' },
                  { keys: '⌘ / Ctrl + 1', desc: 'Switch to Master Profile & Setup Tab' },
                  { keys: '⌘ / Ctrl + 2', desc: 'Switch to Job Tailor Workspace Tab' },
                  { keys: '⌘ / Ctrl + 3', desc: 'Switch to Job Discovery Search Tab' },
                  { keys: 'Esc / ?', desc: 'Dismiss active overlay or view shortcut cheat-sheet' }
                ].map((sc) => (
                  <div key={sc.keys} style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    padding: '12px 16px',
                    background: 'rgba(2, 6, 23, 0.5)',
                    borderRadius: '8px',
                    border: '1px solid rgba(255, 255, 255, 0.05)'
                  }}>
                    <span style={{ color: '#cbd5e1', fontSize: '0.84rem' }}>{sc.desc}</span>
                    <kbd style={{
                      background: 'rgba(56, 189, 248, 0.12)',
                      border: '1px solid rgba(56, 189, 248, 0.3)',
                      color: '#38bdf8',
                      padding: '3px 8px',
                      borderRadius: '6px',
                      fontSize: '0.74rem',
                      fontFamily: 'var(--font-mono)',
                      whiteSpace: 'nowrap'
                    }}>
                      {sc.keys}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* SECTION: In-Page AI Autofill */}
          <section id="autofill" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>In-Page AI Autofill & Screening Questions</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              When navigating job applications on LinkedIn, Ashby, Greenhouse, Lever, and Workday, the extension injects smart autofill capabilities directly into the page.
            </p>

            <div style={{
              background: 'rgba(15, 23, 42, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '14px',
              padding: '24px'
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                  <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '4px 8px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 700 }}>AI Answer</span>
                  <div style={{ color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.6 }}>
                    Inline buttons appear beside screening question textareas (e.g. <em>"Why are you interested in this role?"</em>, <em>"Describe your experience with distributed systems"</em>). Clicking generates contextual answers tailored to the company and role.
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                  <span style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', padding: '4px 8px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 700 }}>Auto-Fill</span>
                  <div style={{ color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.6 }}>
                    Standard fields like Name, Email, Phone, LinkedIn, GitHub, Portfolio, Notice Period, and Sponsorship are filled deterministically from your synced Candidate Profile.
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* SECTION: Job Discovery */}
          <section id="discovery" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Automated Job Discovery & Search</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Discover active job postings across LinkedIn and Indeed filtered by keywords, location (e.g. London, Remote, New York), and timeframes (past 24h, past week).
            </p>

            <div style={{
              background: 'rgba(15, 23, 42, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '14px',
              padding: '24px',
              color: '#cbd5e1',
              fontSize: '0.9rem',
              lineHeight: 1.6
            }}>
              Each discovered job displays a calculated ATS match badge, company name, location, and a 1-click <strong>"Tailor Resume"</strong> button that loads the posting directly into the single-page compiler.
            </div>
          </section>

          {/* SECTION: MCP Server & Universal Agent Skills */}
          <section id="mcp-skills" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>
                Model Context Protocol (MCP) & Universal Agent Skills
              </h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '20px' }}>
              Job Finder features a built-in JSON-RPC 2.0 MCP server and 8 Universal Skills (YAML frontmatter compatible), enabling autonomous career search directly through <strong>Claude Desktop</strong>, <strong>Claude Code</strong>, <strong>Cursor IDE</strong>, <strong>Gemini CLI</strong>, and <strong>Antigravity</strong>.
            </p>

            {/* MCP Highlights */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '24px' }}>
              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid rgba(168, 85, 247, 0.25)',
                borderRadius: '12px',
                padding: '20px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <span style={{ background: 'rgba(168, 85, 247, 0.2)', color: '#c084fc', padding: '4px 8px', borderRadius: '6px', fontSize: '0.78rem', fontWeight: 700 }}>
                    18 Production MCP Tools
                  </span>
                </div>
                <div style={{ color: '#cbd5e1', fontSize: '0.88rem', lineHeight: 1.6 }}>
                  Includes <code>search_jobs</code>, <code>scrape_job_posting</code>, <code>calculate_ats_score</code>, <code>analyze_skill_gap</code>, <code>tailor_resume_latex</code>, <code>compile_latex_metrics</code>, <code>export_overleaf_bundle</code>, <code>extract_recruiter_profile</code>, <code>generate_outreach_inmail</code>, and <code>track_application</code>.
                </div>
              </div>

              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                borderRadius: '12px',
                padding: '20px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <span style={{ background: 'rgba(56, 189, 248, 0.2)', color: '#38bdf8', padding: '4px 8px', borderRadius: '6px', fontSize: '0.78rem', fontWeight: 700 }}>
                    8 Universal Agent Skills
                  </span>
                </div>
                <div style={{ color: '#cbd5e1', fontSize: '0.88rem', lineHeight: 1.6 }}>
                  Autonomous career workflows located in <code>.agents/skills/</code>: <code>career-discovery</code>, <code>ats-resume-tailor</code>, <code>recruiter-networking</code>, <code>candidate-profile-config</code>, <code>company-intelligence</code>, <code>cover-letter-crafting</code>, <code>interview-mastery</code>, and <code>application-tracker-crm</code>.
                </div>
              </div>

              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid rgba(16, 185, 129, 0.25)',
                borderRadius: '12px',
                padding: '20px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <span style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', padding: '4px 8px', borderRadius: '6px', fontSize: '0.78rem', fontWeight: 700 }}>
                    flash-lite & Sub-Second Execution
                  </span>
                </div>
                <div style={{ color: '#cbd5e1', fontSize: '0.88rem', lineHeight: 1.6 }}>
                  Prioritizes <code>gemini-3.5-flash-lite</code> with zero-latency profile auto-resolution (&lt;10ms) from <code>candidate_profile.json</code>, eliminating 429 quota exhaustion.
                </div>
              </div>
            </div>

            {/* Harness Integration Snippet */}
            <div style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '14px',
              padding: '20px'
            }}>
              <h4 style={{ color: '#f8fafc', margin: '0 0 12px', fontSize: '1rem', fontWeight: 700 }}>
                Harness Setup (Claude Desktop, Cursor, Antigravity)
              </h4>
              <p style={{ color: '#94a3b8', fontSize: '0.88rem', margin: '0 0 12px' }}>
                Add the MCP server configuration into your AI client settings file (see <code>harness_configs/</code> for pre-built JSON templates):
              </p>
              <pre style={{
                background: 'rgba(2, 6, 23, 0.85)',
                padding: '14px',
                borderRadius: '8px',
                fontSize: '0.82rem',
                color: '#38bdf8',
                overflowX: 'auto',
                margin: 0,
                fontFamily: 'monospace'
              }}>
{`{
  "mcpServers": {
    "job-finder": {
      "command": "python",
      "args": ["-m", "mcp.server"],
      "cwd": "/path/to/Job Finder/backend",
      "env": {
        "GEMINI_API_KEY": "your-gemini-api-key"
      }
    }
  }
}`}
              </pre>
            </div>
          </section>

          {/* SECTION: Backend & Environment Setup */}
          <section id="api-setup" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>
                Backend & Environment Setup
              </h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '20px' }}>
              Connect frontend clients to production endpoints, configure BYOK Gemini API keys, or run containerized instances via Docker or local uvicorn.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
              {/* Endpoint Card */}
              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '14px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '16px'
              }}>
                <div>
                  <h4 style={{ color: '#38bdf8', margin: '0 0 6px', fontSize: '0.98rem', fontWeight: 700 }}>
                    Active Backend Server URL
                  </h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: '0 0 10px', lineHeight: 1.5 }}>
                    Target host for the React web app and Chrome Side Panel synchronization:
                  </p>
                  <div style={{
                    background: 'rgba(2, 6, 23, 0.8)',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    border: '1px solid rgba(56, 189, 248, 0.2)',
                    fontFamily: 'monospace',
                    fontSize: '0.88rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}>
                    <span style={{ color: '#f8fafc' }}>{serverUrl}</span>
                    <button
                      onClick={() => handleCopy(serverUrl, 'url')}
                      style={{
                        background: 'rgba(56, 189, 248, 0.2)',
                        border: 'none',
                        color: '#38bdf8',
                        padding: '6px 12px',
                        borderRadius: '6px',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        cursor: 'pointer'
                      }}
                    >
                      {copiedUrl ? '✓ Copied' : 'Copy'}
                    </button>
                  </div>
                </div>

                <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '16px' }}>
                  <h4 style={{ color: '#38bdf8', margin: '0 0 6px', fontSize: '0.98rem', fontWeight: 700 }}>
                    Docker & Local Run Commands
                  </h4>
                  <pre style={{
                    background: 'rgba(2, 6, 23, 0.8)',
                    padding: '12px',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    color: '#94a3b8',
                    overflowX: 'auto',
                    margin: 0,
                    fontFamily: 'monospace'
                  }}>
{`# Docker build & run (port 8000)
docker build -t job-finder .
docker run -p 8000:8000 --env-file backend/.env job-finder

# Or run backend locally
cd backend && uvicorn main:app --reload --port 8000`}
                  </pre>
                </div>
              </div>

              {/* Environment Variables Card */}
              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '14px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h4 style={{ color: '#38bdf8', margin: 0, fontSize: '0.98rem', fontWeight: 700 }}>
                    Environment Variables (.env)
                  </h4>
                  <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Hugging Face / Docker</span>
                </div>
                <pre style={{
                  background: 'rgba(2, 6, 23, 0.8)',
                  padding: '14px',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: '#94a3b8',
                  overflowX: 'auto',
                  margin: 0,
                  fontFamily: 'monospace',
                  lineHeight: 1.6
                }}>
{`GEMINI_API_KEY="your-gemini-api-key"
# Optional Supabase Cloud Sync
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_KEY="your-anon-or-service-key"
# Optional Email Delivery (SMTP)
SMTP_SERVER="smtp.gmail.com"
SMTP_PORT=587
SMTP_USER="your-email@gmail.com"
SMTP_PASSWORD="your-app-password"`}
                </pre>
              </div>
            </div>

            {/* Reachout & Contact Card */}
            <div style={{
              marginTop: '20px',
              background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(30, 41, 59, 0.6) 100%)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '14px',
              padding: '24px',
              display: 'flex',
              flexWrap: 'wrap',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '20px'
            }}>
              <div>
                <div style={{ fontSize: '0.75rem', fontWeight: 800, color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '6px' }}>
                  Creator & Inquiries
                </div>
                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#f8fafc', marginBottom: '4px' }}>
                  Have questions, ideas, or feedback?
                </div>
                <div style={{ color: '#94a3b8', fontSize: '0.88rem' }}>
                  Reach out directly to Akhil Baja — AI/ML Systems Engineer & Builder.
                </div>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                <a
                  href="mailto:akhilbaja.work@gmail.com"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    background: 'rgba(56, 189, 248, 0.15)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    color: '#38bdf8',
                    textDecoration: 'none',
                    fontSize: '0.84rem',
                    fontWeight: 600
                  }}
                >
                  ✉️ akhilbaja.work@gmail.com
                </a>
                <a
                  href="https://linkedin.com/in/akhilbaja"
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    background: 'rgba(255, 255, 255, 0.06)',
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                    color: '#f8fafc',
                    textDecoration: 'none',
                    fontSize: '0.84rem',
                    fontWeight: 600
                  }}
                >
                  LinkedIn
                </a>
                <a
                  href="https://github.com/AkhilBaja3005"
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    background: 'rgba(255, 255, 255, 0.06)',
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                    color: '#f8fafc',
                    textDecoration: 'none',
                    fontSize: '0.84rem',
                    fontWeight: 600
                  }}
                >
                  GitHub
                </a>
              </div>
            </div>
          </section>

          {/* Footer note */}
          <div style={{
            textAlign: 'center',
            paddingTop: '20px',
            borderTop: '1px solid rgba(255, 255, 255, 0.06)',
            color: '#64748b',
            fontSize: '0.85rem'
          }}>
            Crafted with ❤️ from Hyderabad • AI Job Finder v3.1.0
          </div>
        </div>
      </div>
      <style>{`
        @media (max-width: 900px) {
          .docs-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
