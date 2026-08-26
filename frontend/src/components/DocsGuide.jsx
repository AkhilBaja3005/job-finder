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
    { id: 'quickstart', label: '🚀 Quickstart', icon: '⚡' },
    { id: 'extension', label: '🧩 Chrome Extension v2.2', icon: '💻' },
    { id: 'sync-key', label: '🔑 Sync Key & Pairing', icon: '🔗' },
    { id: 'master-resume', label: '👥 Multi-Archetypes & Master Resume', icon: '📝' },
    { id: 'ats-scoring', label: '🎯 ATS Scoring & Strategies', icon: '📊' },
    { id: 'autofill', label: '✨ In-Page AI Autofill & PDF Drop', icon: '🤖' },
    { id: 'discovery', label: '🔍 Job Discovery Search', icon: '🌐' },
    { id: 'api-setup', label: '⚙️ API & Deployment', icon: '🛠️' },
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
            <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>v2.1.0 (Production)</span>
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
              <span>📥</span> Download Extension (.zip)
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
              Open Dashboard 🚀
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
                    <span>{item.icon}</span>
                    <span>{item.label.replace(/^[^\s]+\s/, '')}</span>
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
              <span style={{ fontSize: '1.5rem' }}>🚀</span>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Quickstart Workflow</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '20px' }}>
              Follow these 4 simple steps to connect your master resume with live job postings and generate tailored single-page resumes with 1 click.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
              {[
                { step: '1', title: 'Upload Master Resume', desc: 'Upload your .pdf, .docx, or native .tex file in the Master tab to extract and lock your categorized experience.' },
                { step: '2', title: 'Install Chrome Extension', desc: 'Download the pre-baked zip package and unpack it in chrome://extensions with zero manual configuration needed.' },
                { step: '3', title: 'Browse Any Job Board', desc: 'Open LinkedIn, Ashby, Greenhouse, Lever, Workday, or Indeed. The Side Panel auto-extracts the job description.' },
                { step: '4', title: '1-Click Tailor & Apply', desc: 'Generate a verified 1-page LaTeX PDF resume, cover letter, and personalized recruiter outreach in seconds.' }
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

          {/* SECTION: Chrome Extension v2.2.0 */}
          <section id="extension" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <span style={{ fontSize: '1.5rem' }}>🧩</span>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Chrome Extension v2.2.0 (Side Panel & Automation)</h2>
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
                📦 Zero-Config Installation Guide
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

            {/* In-Page Capabilities */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.2rem', marginBottom: '8px' }}>🏷️ Live Toolbar ATS Badge</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Shows your live match percentage (🟢 <code>94%</code>, 🟡 <code>76%</code>) on the browser toolbar icon in real time as you navigate job tabs without opening the panel.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.2rem', marginBottom: '8px' }}>📎 1-Click File Auto-Attach</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Click <code>📎 Attach PDF</code> in the side panel to compile and programmatically inject your tailored PDF into ATS dropzones on Ashby, Greenhouse, Lever, and Workday via DataTransfer.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.2rem', marginBottom: '8px' }}>🔄 Live Tab Sync & Rescan</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Switching tabs automatically scans the newly active job posting. If you edit custom job details, clicking <code>🔄 Rescan Tab</code> clears stale cache and re-extracts the live page DOM.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.2rem', marginBottom: '8px' }}>✉️ 1-Click Email Package</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Sends a formatted delivery email with the compiled PDF attached, ATS score breakdown, role title, company name, and direct Overleaf editing links straight to your inbox.
                </p>
              </div>
            </div>
          </section>

          {/* SECTION: Sync Key & Pairing */}
          <section id="sync-key" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <span style={{ fontSize: '1.5rem' }}>🔑</span>
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
                  {copiedKey ? '✓ Copied to Clipboard' : '📋 Copy Sync Key'}
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
              <span style={{ fontSize: '1.5rem' }}>👥</span>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>Multi-Archetype Profiles & Category Lockdown</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Store multiple distinct master resumes (e.g., <strong>GenAI Systems Engineer</strong>, <strong>Data Scientist</strong>, <strong>Backend SWE</strong>) and toggle the active baseline for target jobs.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '14px' }}>
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
              <span style={{ fontSize: '1.5rem' }}>🎯</span>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>ATS Scoring & Tailoring Strategies</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Choose your tailoring strategy and let our multi-pass compensation engine produce a strictly 1-page PDF.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#38bdf8', marginBottom: '6px' }}>🛡️ Strict Conservative</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Preserves original bullet structure verbatim and only replaces technical keywords where direct equivalents exist.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#34d399', marginBottom: '6px' }}>⚖️ Balanced (Recommended)</div>
                <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                  Aligns terminology, weaves missing target skills, and highlights relevant systems while strictly preserving candidate facts.
                </p>
              </div>
              <div style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '12px', padding: '18px' }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#f59e0b', marginBottom: '6px' }}>🚀 Impact-Driven</div>
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
                  <h4 style={{ color: '#10b981', margin: '0 0 8px', fontSize: '1rem' }}>✓ Deterministic Keyword Matching</h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                    Identifies hard technical requirements, preferred qualifications, seniority levels, and calculates timeline flattening to prevent duplicate date inflation.
                  </p>
                </div>
                <div>
                  <h4 style={{ color: '#38bdf8', margin: '0 0 8px', fontSize: '1rem' }}>✓ Multi-Pass Page Budgeting</h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                    If a tailored resume spills onto 2 pages, the backend dynamically calculates linespread scaling (0.95 down to 0.78) and section spacing to guarantee a strictly 1-page PDF.
                  </p>
                </div>
                <div>
                  <h4 style={{ color: '#818cf8', margin: '0 0 8px', fontSize: '1rem' }}>✓ Missing Skills Selector</h4>
                  <p style={{ color: '#94a3b8', fontSize: '0.86rem', lineHeight: 1.6, margin: 0 }}>
                    Click any missing keyword chip in the ATS breakdown to explicitly authorize and incorporate it into the tailored bullet points and skill section.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* SECTION: In-Page AI Autofill */}
          <section id="autofill" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <span style={{ fontSize: '1.5rem' }}>✨</span>
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
                  <span style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '4px 8px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 700 }}>✨ AI Answer</span>
                  <div style={{ color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.6 }}>
                    Inline buttons appear beside screening question textareas (e.g. <em>"Why are you interested in this role?"</em>, <em>"Describe your experience with distributed systems"</em>). Clicking generates contextual answers tailored to the company and role.
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                  <span style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', padding: '4px 8px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 700 }}>⚡ Auto-Fill</span>
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
              <span style={{ fontSize: '1.5rem' }}>🔍</span>
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

          {/* SECTION: API & Deployment */}
          <section id="api-setup" style={{ scrollMarginTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <span style={{ fontSize: '1.5rem' }}>⚙️</span>
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>API Configuration & Deployment</h2>
            </div>
            <p style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: '0.98rem', marginBottom: '18px' }}>
              Configure your backend endpoints, Gemini API keys (BYOK support), and environment variables.
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
              <div>
                <h4 style={{ color: '#38bdf8', margin: '0 0 8px', fontSize: '0.95rem' }}>Production Endpoint</h4>
                <div style={{
                  background: 'rgba(2, 6, 23, 0.6)',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  fontFamily: 'monospace',
                  fontSize: '0.88rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <span>{serverUrl}</span>
                  <button
                    onClick={() => handleCopy(serverUrl, 'url')}
                    style={{
                      background: 'rgba(56, 189, 248, 0.2)',
                      border: 'none',
                      color: '#38bdf8',
                      padding: '4px 10px',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      cursor: 'pointer'
                    }}
                  >
                    {copiedUrl ? '✓ Copied' : 'Copy'}
                  </button>
                </div>
              </div>

              <div>
                <h4 style={{ color: '#38bdf8', margin: '0 0 8px', fontSize: '0.95rem' }}>Hugging Face / Docker Environment Variables</h4>
                <pre style={{
                  background: 'rgba(2, 6, 23, 0.8)',
                  padding: '14px',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: '#94a3b8',
                  overflowX: 'auto',
                  margin: 0,
                  fontFamily: 'monospace'
                }}>
{`GEMINI_API_KEY="your-gemini-api-key"
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_KEY="your-anon-or-service-key"
SMTP_SERVER="smtp.gmail.com"
SMTP_PORT=587
SMTP_USER="your-email@gmail.com"
SMTP_PASSWORD="your-app-password"`}
                </pre>
              </div>
            </div>
          </section>

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
