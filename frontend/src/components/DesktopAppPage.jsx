import React, { useState } from 'react';
import { APP_VERSION } from '../config/constants';

const DESKTOP_RELEASE = 'https://github.com/AkhilBaja3005/job-finder/releases/download/desktop-latest/';
const MAC_CURL_CMD = 'curl -fsSL https://raw.githubusercontent.com/AkhilBaja3005/job-finder/main/macapp/install_mac.sh | bash';

const DOWNLOADS = [
  { key: 'mac-arm', label: 'Mac (Apple Silicon)', sub: 'M1, M2, M3, M4 — arm64 .dmg', file: 'Job-Finder-arm64.dmg' },
  { key: 'mac-intel', label: 'Mac (Intel)', sub: 'Pre-2020 Macs — x86_64 .dmg', file: 'Job-Finder-x86_64.dmg' },
  { key: 'windows', label: 'Windows', sub: 'Windows 10 / 11 — .zip', file: 'Job-Finder-windows.zip' },
];

const STAGES = [
  {
    num: '1',
    title: 'Search',
    desc: 'Scan LinkedIn, Indeed, Reed, Jobserve, and 23,000+ Greenhouse, Lever, Ashby, Workday & BambooHR boards into a per-search Excel workbook. Dry-run first to inspect the funnel.',
  },
  {
    num: '2',
    title: 'Review',
    desc: 'Filter scanned roles by ATS score and keywords. Approve only the jobs you want before spending AI credits on tailoring.',
  },
  {
    num: '3',
    title: 'Documents',
    desc: 'Prepare tailored 1-page CVs, cover letters, and fit analyses with live progress logs. Inspect Evidence & Risk ("I have this"), Diff & Revert, or edit LaTeX live with offline bundled Tectonic PDF preview, then click Docs OK.',
  },
  {
    num: '4',
    title: 'Apply',
    desc: 'Only signed-off jobs enter the Apply queue. Run Preview apply first to watch your docked Chrome fill forms without submitting, then Submit applications when ready.',
  },
];

export default function DesktopAppPage({ onBack, onLaunchPlatform }) {
  const [copied, setCopied] = useState(false);

  const copyCmd = () => {
    try {
      navigator.clipboard.writeText(MAC_CURL_CMD);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) { /* clipboard blocked */ }
  };

  return (
    <div style={{ maxWidth: '1040px', margin: '0 auto', padding: '36px 24px 72px', color: 'var(--text-main)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '28px', gap: '12px', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={onBack}
          className="btn-secondary"
          style={{ padding: '8px 14px', fontSize: '0.84rem' }}
        >
          ← Back to home
        </button>
        <button
          type="button"
          onClick={onLaunchPlatform}
          className="btn"
          style={{ padding: '8px 16px', fontSize: '0.84rem' }}
        >
          Open Web Platform
        </button>
      </div>

      <section style={{
        background: 'var(--panel-bg)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '36px 32px',
        marginBottom: '32px',
      }}>
        <div style={{ fontSize: '0.76rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '8px' }}>
          Job Finder Desktop App · v{APP_VERSION}
        </div>
        <h1 style={{ fontSize: '2.1rem', fontWeight: 800, color: '#FFFFFF', margin: '0 0 12px', letterSpacing: '-0.025em' }}>
          Search, tailor, and apply from your own Mac or Windows PC
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.96rem', lineHeight: 1.65, maxWidth: '720px', margin: '0 0 24px' }}>
          A native desktop window wrapping the full staged workflow — <strong>Search → Review → Documents → Apply</strong> — with your own Chrome browser, local Excel workbooks, zero-hallucination CV guards, and an offline bundled <strong>Tectonic</strong> LaTeX compiler.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', marginBottom: '22px' }}>
          {DOWNLOADS.map((d) => (
            <a
              key={d.key}
              href={DESKTOP_RELEASE + d.file}
              rel="noopener noreferrer"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
                padding: '16px 18px',
                borderRadius: '12px',
                background: 'rgba(15, 23, 42, 0.72)',
                border: '1px solid var(--border-color)',
                textDecoration: 'none',
                color: '#FFFFFF',
              }}
            >
              <span style={{ fontWeight: 700, fontSize: '0.95rem', color: '#38BDF8' }}>Download for {d.label}</span>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{d.sub}</span>
            </a>
          ))}
        </div>

        <div style={{
          paddingTop: '16px',
          borderTop: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            macOS Terminal install (no Gatekeeper warning):
          </span>
          <div style={{
            width: '100%',
            boxSizing: 'border-box',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 12px',
            borderRadius: '8px',
            background: 'rgba(15, 23, 42, 0.7)',
            border: '1px solid var(--border-color)',
          }}>
            <code style={{ fontSize: '0.76rem', color: '#e2e8f0', wordBreak: 'break-all', flex: 1 }}>
              {MAC_CURL_CMD}
            </code>
            <button
              type="button"
              onClick={copyCmd}
              className="btn-secondary"
              style={{ padding: '4px 10px', fontSize: '0.74rem', flexShrink: 0 }}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      </section>

      <h2 style={{ fontSize: '1.35rem', fontWeight: 800, color: '#FFFFFF', margin: '0 0 14px' }}>
        Four-Stage Staged Workflow
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginBottom: '36px' }}>
        {STAGES.map((s) => (
          <div
            key={s.num}
            style={{
              background: 'var(--panel-bg)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '20px',
            }}
          >
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#38BDF8', marginBottom: '6px' }}>
              STAGE {s.num}
            </div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#FFFFFF', marginBottom: '8px' }}>
              {s.title}
            </div>
            <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', lineHeight: 1.55, margin: 0 }}>
              {s.desc}
            </p>
          </div>
        ))}
      </div>

      <section style={{
        background: 'var(--panel-bg)',
        border: '1px solid var(--border-color)',
        borderRadius: '14px',
        padding: '24px 28px',
      }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#FFFFFF', margin: '0 0 12px' }}>
          Built-in Safety &amp; LaTeX Controls
        </h2>
        <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--text-muted)', fontSize: '0.87rem', lineHeight: 1.75 }}>
          <li><strong>Zero invented facts:</strong> Tailoring only selects, reorders, and rephrases your real resume &amp; profile. Missing skills are never added unless you explicitly confirm them via <em>&ldquo;I have this&rdquo;</em>.</li>
          <li><strong>Offline bundled Tectonic:</strong> Compile and preview 1-page LaTeX CVs in-app with no internet or external TeX install required.</li>
          <li><strong>Custom <code>.tex</code> templates &amp; hand-edited sync:</strong> Import your own <code>.tex</code> template or hand-edit any pack&apos;s LaTeX, and switch back to the standard CV anytime.</li>
          <li><strong>Docked Chrome + Practice mode:</strong> Preview form filling step-by-step before ever clicking Submit.</li>
        </ul>
      </section>
    </div>
  );
}
