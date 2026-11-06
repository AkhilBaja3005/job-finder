import React, { useState, useEffect } from 'react';
import { APP_VERSION, EXTENSION_VERSION } from '../config/constants';

function AnimatedCounter({ target, suffix = '', duration = 1800 }) {
  const [count, setCount] = useState(1);

  useEffect(() => {
    let startTimestamp = null;
    let animationFrame;

    const step = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / duration, 1);
      // Easing out cubic: 1 - Math.pow(1 - progress, 3)
      const easeProgress = 1 - Math.pow(1 - progress, 3);
      const current = Math.floor(1 + easeProgress * (target - 1));
      setCount(current);

      if (progress < 1) {
        animationFrame = window.requestAnimationFrame(step);
      } else {
        setCount(target);
      }
    };

    animationFrame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [target, duration]);

  return (
    <span>
      {count >= 1000 ? count.toLocaleString() : count}
      {suffix}
    </span>
  );
}

/**
 * LandingPage — Institutional, self-explanatory introductory view for JobFinder.
 * Structured with:
 *  1. Hero Overview & Core Value Prop
 *  2. Step-by-Step Interactive Workflow (How It Works)
 *  3. System Capabilities (Discovery, Scoring, Tailoring, Autofill, UK Sponsors)
 *  4. Quick Navigation Actions (Launch App, Setup Guide, Full Docs)
 */
export default function LandingPage({ onLaunchApp, onOpenDocs, onLaunchDemo }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedDemoTab, setSelectedDemoTab] = useState('matching');
  const [contactName, setContactName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactMessage, setContactMessage] = useState('');
  const [contactLoading, setContactLoading] = useState(false);
  const [contactStatus, setContactStatus] = useState({ type: '', text: '' });

  const handleContactSubmit = async (e) => {
    e.preventDefault();
    if (!contactEmail || !contactMessage) return;
    setContactLoading(true);
    setContactStatus({ type: '', text: '' });

    try {
      const res = await fetch('/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: contactName,
          email: contactEmail,
          message: contactMessage
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to submit inquiry.');
      }

      setContactStatus({ type: 'success', text: 'Thank you! Your query has been delivered to akhilbaja.work@gmail.com. We will respond shortly.' });
      setContactName('');
      setContactEmail('');
      setContactMessage('');
    } catch (err) {
      setContactStatus({ type: 'error', text: err.message || 'Error sending message. Please try emailing directly.' });
    } finally {
      setContactLoading(false);
    }
  };

  const pillars = [
    {
      id: 'discovery',
      tag: 'Multi-Board Aggregation',
      title: 'Automated Job Discovery',
      desc: 'Real-time aggregation across Ashby, Greenhouse, Lever, Workday, LinkedIn, Indeed, Reed, and JobServe with continuous deduplication.',
      badge: '9 Portals'
    },
    {
      id: 'sponsorship',
      tag: 'Compliance Engine',
      title: 'UK Visa Sponsor Database',
      desc: 'Automatic cross-referencing of every employer against the official 140,000+ GOV.UK licensed sponsor register with daily updates.',
      badge: 'GOV.UK Verified'
    },
    {
      id: 'scoring',
      tag: 'Deterministic Matrix',
      title: 'ATS Keyword Scoring',
      desc: 'Rigorous keyword gap analysis and matching taxonomy that measures real keyword relevance before you submit an application.',
      badge: 'Zero-Hallucination'
    },
    {
      id: 'tailoring',
      tag: 'XeLaTeX Precision',
      title: 'Publication-Grade Resumes',
      desc: 'Micro-tailor LaTeX bullet points for specific job descriptions while preserving facts and enforcing a strict 1-page PDF budget.',
      badge: '1-Page Budget'
    },
    {
      id: 'autofill',
      tag: 'Browser Extension',
      title: '1-Click In-Page Autofill',
      desc: 'Chrome Side Panel that detects live job postings, analyzes recruiter requirements, and auto-populates lengthy application forms.',
      badge: 'Chrome Extension'
    },
    {
      id: 'privacy',
      tag: 'Zero Data Retention',
      title: 'Security & Access',
      desc: 'Passwordless single-use OTP authentication, secure API credentials, and client-side encryption for candidate profiles.',
      badge: 'Single-Use OTP'
    }
  ];

  const steps = [
    {
      num: '01',
      title: 'Build Master Profile',
      subtitle: 'Ingest or upload your LaTeX baseline once',
      description: 'Upload your existing LaTeX or standard resume. The system structures your career history, skills taxonomy, and archetypes into a reusable baseline without hallucinations.'
    },
    {
      num: '02',
      title: 'Discover & Verify Jobs',
      subtitle: 'Aggregate postings with licensed visa checks',
      description: 'Search across 9 top hiring portals simultaneously with filters for salary, seniority, and official UK sponsor licensing status.'
    },
    {
      num: '03',
      title: 'Tailor LaTeX in 1-Click',
      subtitle: 'Align keyword matrix to target specification',
      description: 'Choose your tailoring strategy (Balanced, Strict Conservative, or Impact-Driven). Our XeLaTeX compiler generates a verified 1-page PDF ready for submission.'
    },
    {
      num: '04',
      title: 'Autofill & Track Application',
      subtitle: 'Complete applications in seconds via Chrome Extension',
      description: 'Use the paired Chrome Extension to auto-populate Workday, Lever, and Greenhouse forms with customized screening responses and track your pipeline.'
    }
  ];

  return (
    <div style={{
      maxWidth: '1240px',
      margin: '0 auto',
      padding: '40px 20px 100px',
      color: 'var(--text-main)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }}>
      {/* Hero Section */}
      <section style={{
        textAlign: 'center',
        padding: '50px 20px 40px',
        maxWidth: '880px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '20px'
      }}>
        {/* Pill Badge */}
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 14px',
          borderRadius: '20px',
          background: 'rgba(37, 99, 235, 0.1)',
          border: '1px solid rgba(37, 99, 235, 0.3)',
          color: '#38BDF8',
          fontSize: '0.78rem',
          fontWeight: 700,
          letterSpacing: '0.04em',
          textTransform: 'uppercase'
        }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#38BDF8' }} />
          Career Operations & ATS Infrastructure
        </div>

        {/* Main Heading */}
        <h1 style={{
          fontSize: 'clamp(2.1rem, 4.2vw, 3.4rem)',
          fontWeight: 800,
          lineHeight: 1.15,
          letterSpacing: '-0.03em',
          margin: 0,
          color: '#FFFFFF'
        }}>
          Institutional Career Operations & Precision ATS Engine
        </h1>

        {/* Description */}
        <p style={{
          fontSize: 'clamp(1rem, 1.3vw, 1.18rem)',
          lineHeight: 1.6,
          color: 'var(--text-muted)',
          margin: 0,
          maxWidth: '720px'
        }}>
          A unified, self-explanatory platform for tech job aggregation, official UK visa sponsorship verification, deterministic ATS scoring, and publication-grade LaTeX tailoring.
        </p>

        {/* CTA Buttons */}
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '12px',
          justifyContent: 'center',
          marginTop: '10px'
        }}>
          <button
            className="btn"
            style={{
              padding: '12px 28px',
              fontSize: '0.94rem',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              borderRadius: '8px'
            }}
            onClick={onLaunchApp}
          >
            <span>Launch Platform</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12"></line>
              <polyline points="12 5 19 12 12 19"></polyline>
            </svg>
          </button>

          {onLaunchDemo && (
            <button
              className="btn btn-secondary"
              style={{
                padding: '12px 24px',
                fontSize: '0.94rem',
                fontWeight: 600,
                borderRadius: '8px',
                borderColor: 'rgba(56, 189, 248, 0.4)',
                color: '#38BDF8',
                background: 'rgba(56, 189, 248, 0.08)'
              }}
              onClick={onLaunchDemo}
            >
              Try Demo Workspace
            </button>
          )}

          <button
            className="btn btn-secondary"
            style={{
              padding: '12px 24px',
              fontSize: '0.94rem',
              fontWeight: 600,
              borderRadius: '8px'
            }}
            onClick={onOpenDocs}
          >
            Docs & Setup Guide
          </button>
        </div>
      </section>

      {/* Quick Stats Banner with Fluid Animated Counters */}
      <section style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '16px',
        margin: '20px 0 40px'
      }}>
        {[
          {
            metricNode: <><AnimatedCounter target={9} duration={1200} /> Portals</>,
            label: 'Simultaneous ATS aggregation (Ashby, Lever, Greenhouse, etc.)'
          },
          {
            metricNode: <><AnimatedCounter target={140000} suffix="+" duration={1800} /></>,
            label: 'Verified UK GOV sponsor companies checked in real-time'
          },
          {
            metricNode: '100% Deterministic',
            label: 'ATS keyword matrix with zero hallucinations'
          },
          {
            metricNode: '1-Page Strict',
            label: 'XeLaTeX budget enforcement with publication typography'
          }
        ].map((item, idx) => (
          <div key={idx} style={{
            background: 'var(--panel-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '20px 22px'
          }}>
            <div style={{ fontSize: '1.45rem', fontWeight: 800, color: '#38BDF8', letterSpacing: '-0.02em', marginBottom: '6px' }}>
              {item.metricNode}
            </div>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {item.label}
            </div>
          </div>
        ))}
      </section>

      {/* Live Interactive Product Preview */}
      <section style={{
        background: 'var(--panel-bg)',
        border: '1px solid var(--border-color)',
        borderRadius: '14px',
        padding: '30px',
        marginBottom: '50px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '22px' }}>
          <div>
            <div style={{ fontSize: '0.74rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>
              Live Architecture Preview
            </div>
            <h2 style={{ fontSize: '1.45rem', fontWeight: 800, color: '#FFFFFF', margin: 0, letterSpacing: '-0.02em' }}>
              From Raw Job Listing to Publication-Grade XeLaTeX
            </h2>
          </div>
          <div style={{ display: 'flex', gap: '6px', background: '#07090E', padding: '4px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
            {[
              { id: 'matching', label: 'ATS Keyword Matrix' },
              { id: 'sponsors', label: 'UK Visa Verification' },
              { id: 'latex', label: '1-Page XeLaTeX' }
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => setSelectedDemoTab(t.id)}
                style={{
                  border: 'none',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  background: selectedDemoTab === t.id ? '#2563EB' : 'transparent',
                  color: selectedDemoTab === t.id ? '#FFFFFF' : 'var(--text-muted)',
                  transition: 'all 0.15s ease'
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {selectedDemoTab === 'matching' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '18px' }}>
            <div style={{ background: '#0B101C', border: '1px solid var(--border-color)', borderRadius: '10px', padding: '20px' }}>
              <div style={{ fontSize: '0.76rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', marginBottom: '8px' }}>Extracted Job Requirements</div>
              <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#FFFFFF', marginBottom: '6px' }}>Staff Distributed Systems Engineer</div>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: '0 0 14px' }}>Monzo Bank • London / Hybrid • £110k - £135k</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                <span style={{ fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.15)', color: '#38BDF8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>Go / Distributed Systems</span>
                <span style={{ fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.15)', color: '#38BDF8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>Apache Kafka</span>
                <span style={{ fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.15)', color: '#38BDF8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>gRPC & Raft Consensus</span>
                <span style={{ fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.15)', color: '#38BDF8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>PostgreSQL Partitioning</span>
              </div>
            </div>

            <div style={{ background: '#0B101C', border: '1px solid rgba(37, 99, 235, 0.3)', borderRadius: '10px', padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <span style={{ fontSize: '0.76rem', fontWeight: 700, color: '#10B981', textTransform: 'uppercase' }}>ATS Match Taxonomy</span>
                  <span style={{ fontSize: '1.25rem', fontWeight: 800, color: '#10B981', fontFamily: 'var(--font-mono)' }}>94%</span>
                </div>
                <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden', marginBottom: '14px' }}>
                  <div style={{ width: '94%', height: '100%', background: '#10B981' }} />
                </div>
                <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.5, margin: 0 }}>
                  Zero hallucination policy. 18 of 19 required competencies confirmed in Master Profile. Bullet points tailored to emphasize low-latency consensus and stream processing.
                </p>
              </div>
              <div style={{ marginTop: '16px', fontSize: '0.75rem', color: '#94A3B8', fontFamily: 'var(--font-mono)' }}>
                ✓ Strategy: Balanced (Recommended)
              </div>
            </div>
          </div>
        )}

        {selectedDemoTab === 'sponsors' && (
          <div style={{ background: '#0B101C', border: '1px solid var(--border-color)', borderRadius: '10px', padding: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
              <span style={{ padding: '4px 10px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.15)', color: '#10B981', border: '1px solid rgba(16, 185, 129, 0.3)', fontSize: '0.76rem', fontWeight: 700 }}>
                ✓ GOV.UK Licensed Visa Sponsor
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>Tier 2 / Skilled Worker Route Verified</span>
            </div>
            <p style={{ fontSize: '0.86rem', color: 'var(--text-main)', margin: '0 0 10px', lineHeight: 1.6 }}>
              JobFinder continuously synchronizes against the official 140,000+ UK Home Office Sponsor register stored in persistent SQLite storage. Revoked employers are flagged immediately to protect international candidate time.
            </p>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Database: /data/uk_sponsors.db • Daily automated sync enabled
            </div>
          </div>
        )}

        {selectedDemoTab === 'latex' && (
          <div style={{ background: '#0B101C', border: '1px solid var(--border-color)', borderRadius: '10px', padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <div style={{ fontSize: '0.76rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase' }}>XeLaTeX Compilation Budget</div>
              <span style={{ padding: '2px 8px', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.15)', color: '#38BDF8', fontSize: '0.74rem', fontFamily: 'var(--font-mono)' }}>
                Exact 1.0 Page (Budget: 100%)
              </span>
            </div>
            <pre style={{
              margin: 0,
              padding: '14px',
              background: '#07090E',
              borderRadius: '6px',
              border: '1px solid rgba(255,255,255,0.06)',
              fontSize: '0.78rem',
              color: '#CBD5E1',
              fontFamily: 'var(--font-mono)',
              lineHeight: 1.5,
              overflowX: 'auto'
            }}>
              {String.raw`\resumeItem{Architected real-time streaming ledger using Apache Kafka and Go, reducing reconciliation latency by 68% across 4.2M daily transactions.}
\resumeItem{Engineered distributed consensus protocol with gRPC sidecars, enforcing fault tolerance under simulated partition failure.}`}
            </pre>
          </div>
        )}
      </section>

      {/* Interactive Workflow Guide */}
      <section style={{
        background: 'var(--panel-bg)',
        border: '1px solid var(--border-color)',
        borderRadius: '14px',
        padding: '36px 30px',
        marginBottom: '60px'
      }}>
        <div style={{ maxWidth: '640px', marginBottom: '28px' }}>
          <div style={{ fontSize: '0.74rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>
            System Architecture
          </div>
          <h2 style={{ fontSize: '1.65rem', fontWeight: 800, color: '#FFFFFF', margin: '0 0 8px', letterSpacing: '-0.02em' }}>
            How JobFinder Works (4 Step Flow)
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
            An integrated workflow connecting candidate profile management, live job search, deterministic ATS matching, and in-browser form filling.
          </p>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: '20px'
        }}>
          {steps.map((st) => (
            <div key={st.num} style={{
              background: '#0B101C',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '10px',
              padding: '24px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px'
            }}>
              <div style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.85rem',
                fontWeight: 800,
                color: '#2563EB',
                background: 'rgba(37, 99, 235, 0.1)',
                padding: '4px 8px',
                borderRadius: '4px',
                alignSelf: 'flex-start'
              }}>
                STEP {st.num}
              </div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                {st.title}
              </h3>
              <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#94A3B8' }}>
                {st.subtitle}
              </div>
              <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', lineHeight: 1.55, margin: 0 }}>
                {st.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Feature Capabilities Grid */}
      <section style={{ marginBottom: '60px' }}>
        <div style={{ textAlign: 'center', maxWidth: '600px', margin: '0 auto 36px' }}>
          <div style={{ fontSize: '0.74rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>
            Core Platform Engines
          </div>
          <h2 style={{ fontSize: '1.65rem', fontWeight: 800, color: '#FFFFFF', margin: '0 0 8px', letterSpacing: '-0.02em' }}>
            Built for Serious Technical Applicants
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
            Every component is engineered with deterministic rules, transparent scoring algorithms, and strict security standards.
          </p>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '18px'
        }}>
          {pillars.map((p) => (
            <div key={p.id} style={{
              background: 'var(--panel-bg)',
              border: '1px solid var(--border-color)',
              borderRadius: '12px',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  {p.tag}
                </span>
                <span style={{
                  fontSize: '0.68rem',
                  fontWeight: 600,
                  fontFamily: 'var(--font-mono)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  background: 'rgba(255, 255, 255, 0.05)',
                  color: '#94A3B8'
                }}>
                  {p.badge}
                </span>
              </div>
              <h3 style={{ fontSize: '1.08rem', fontWeight: 700, color: '#FFFFFF', margin: 0 }}>
                {p.title}
              </h3>
              <p style={{ fontSize: '0.86rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
                {p.desc}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Contact & Developer Feedback Section */}
      <section style={{
        background: 'var(--panel-bg)',
        border: '1px solid var(--border-color)',
        borderRadius: '14px',
        padding: '32px 28px',
        marginBottom: '40px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '20px'
      }}>
        <div style={{ maxWidth: '620px' }}>
          <div style={{ fontSize: '0.74rem', fontWeight: 700, color: '#38BDF8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>
            Support & Inquiries
          </div>
          <h2 style={{ fontSize: '1.45rem', fontWeight: 800, color: '#FFFFFF', margin: '0 0 6px', letterSpacing: '-0.02em' }}>
            Contact & Developer Feedback
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', lineHeight: 1.6, margin: 0 }}>
            Have questions about official UK sponsor database updates, ATS compatibility scoring, or custom integrations? Connect directly with our engineering and support team.
          </p>
        </div>

        <button
          onClick={() => {
            window.history.pushState(null, '', '/contact');
            window.dispatchEvent(new PopStateEvent('popstate'));
          }}
          className="btn"
          style={{ padding: '12px 24px', fontSize: '0.9rem', fontWeight: 700, whiteSpace: 'nowrap' }}
        >
          Open Contact Page →
        </button>
      </section>

      {/* Institutional Enterprise Footer */}
      <footer style={{
        marginTop: '60px',
        paddingTop: '24px',
        borderTop: '1px solid var(--border-color)',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        fontSize: '0.78rem',
        color: 'var(--text-muted)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10B981' }} />
          <span>JobFinder Infrastructure</span>
          <span>•</span>
          <span>UK Home Office Register Synced: 143,053 Official Sponsors</span>
          <span>•</span>
          <span style={{ color: '#38BDF8' }}>AES-256-GCM Zero-Knowledge Storage</span>
        </div>
        <div style={{ display: 'flex', gap: '16px' }}>
          <a
            href="https://github.com/AkhilBaja3005/job-finder"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--text-muted)', textDecoration: 'none' }}
          >
            GitHub
          </a>
          <button
            onClick={onOpenDocs}
            style={{ background: 'none', border: 'none', padding: 0, color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.78rem' }}
          >
            Documentation
          </button>
          <button
            onClick={() => {
              window.history.pushState(null, '', '/contact');
              window.dispatchEvent(new PopStateEvent('popstate'));
            }}
            style={{ background: 'none', border: 'none', padding: 0, color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.78rem' }}
          >
            Contact & Support
          </button>
          <button
            onClick={onLaunchApp}
            style={{ background: 'none', border: 'none', padding: 0, color: '#38BDF8', cursor: 'pointer', fontSize: '0.78rem' }}
          >
            Platform Access
          </button>
        </div>
      </footer>
    </div>
  );
}
