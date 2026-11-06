import React, { useState } from 'react';

const API_BASE = import.meta.env?.VITE_API_BASE
  || import.meta.env?.VITE_BACKEND_URL
  || ((window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:8000'
    : window.location.origin);

export default function ContactPage({ onNavigate }) {
  const [contactName, setContactName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactMessage, setContactMessage] = useState('');
  const [contactLoading, setContactLoading] = useState(false);
  const [contactStatus, setContactStatus] = useState({ type: '', text: '' });

  const handleContactSubmit = async (e) => {
    e.preventDefault();
    if (!contactEmail.trim() || !contactMessage.trim()) return;
    setContactLoading(true);
    setContactStatus({ type: '', text: '' });

    try {
      const res = await fetch(`${API_BASE}/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: contactName.trim() || 'Anonymous User',
          email: contactEmail.trim(),
          message: contactMessage.trim(),
        }),
      });

      const data = await res.json();
      if (res.ok && (data.success || data.status === 'success')) {
        setContactStatus({
          type: 'success',
          text: 'Inquiry dispatched successfully. Our team will review your query and respond shortly.',
        });
        setContactName('');
        setContactEmail('');
        setContactMessage('');
      } else {
        setContactStatus({
          type: 'error',
          text: data.detail || data.message || 'Failed to submit inquiry. Please email akhilbaja.work@gmail.com directly.',
        });
      }
    } catch (err) {
      setContactStatus({
        type: 'error',
        text: 'Network error submitting inquiry. Please email akhilbaja.work@gmail.com directly.',
      });
    } finally {
      setContactLoading(false);
    }
  };

  return (
    <div style={{
      maxWidth: '880px',
      margin: '0 auto',
      padding: '40px 24px 80px',
      color: 'var(--text-main)',
      fontFamily: 'var(--font-sans)',
      boxSizing: 'border-box'
    }}>
      {/* Page Header */}
      <div style={{ marginBottom: '32px' }}>
        <div style={{
          display: 'inline-block',
          fontSize: '0.74rem',
          fontWeight: 700,
          color: '#38BDF8',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginBottom: '8px'
        }}>
          Support & Inquiries
        </div>
        <h1 style={{
          fontSize: '2rem',
          fontWeight: 800,
          color: '#FFFFFF',
          margin: '0 0 10px',
          letterSpacing: '-0.02em'
        }}>
          Contact & Platform Inquiries
        </h1>
        <p style={{
          color: 'var(--text-muted)',
          fontSize: '0.96rem',
          lineHeight: 1.6,
          margin: 0,
          maxWidth: '680px'
        }}>
          Have questions about official UK sponsor database updates, ATS compatibility scoring, or custom integrations? Get in touch directly with our engineering and support team.
        </p>
      </div>

      {/* Direct Contact Channels */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap: '16px',
        marginBottom: '32px'
      }}>
        {/* Direct Email */}
        <div style={{
          background: 'var(--panel-bg)',
          border: '1px solid var(--border-color)',
          borderRadius: '10px',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px'
        }}>
          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Direct Support Email
          </div>
          <a
            href="mailto:akhilbaja.work@gmail.com"
            style={{ fontSize: '1rem', fontWeight: 700, color: '#38BDF8', textDecoration: 'none' }}
          >
            akhilbaja.work@gmail.com
          </a>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Typical response within 24 business hours
          </div>
        </div>

        {/* LinkedIn */}
        <div style={{
          background: 'var(--panel-bg)',
          border: '1px solid var(--border-color)',
          borderRadius: '10px',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px'
        }}>
          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Professional Network
          </div>
          <a
            href="https://linkedin.com/in/akhilbaja"
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: '1rem', fontWeight: 700, color: '#38BDF8', textDecoration: 'none' }}
          >
            linkedin.com/in/akhilbaja →
          </a>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Connect for enterprise or engineering collaborations
          </div>
        </div>

        {/* GitHub Issues */}
        <div style={{
          background: 'var(--panel-bg)',
          border: '1px solid var(--border-color)',
          borderRadius: '10px',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px'
        }}>
          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Open Source & Issues
          </div>
          <a
            href="https://github.com/AkhilBaja3005/job-finder/issues"
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: '1rem', fontWeight: 700, color: '#38BDF8', textDecoration: 'none' }}
          >
            GitHub Issue Tracker →
          </a>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Bug reports and portal integration requests
          </div>
        </div>
      </div>

      {/* Interactive In-Page Inquiry Form */}
      <form onSubmit={handleContactSubmit} style={{
        background: 'var(--panel-bg)',
        border: '1px solid var(--border-color)',
        borderRadius: '12px',
        padding: '28px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#FFFFFF', marginBottom: '4px' }}>
            Send an Inquiry or Feedback Directly
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            Fill out the form below to transmit your request straight to our mailbox.
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase' }}>
              Your Name
            </label>
            <input
              type="text"
              placeholder="Jane Doe"
              value={contactName}
              onChange={(e) => setContactName(e.target.value)}
              style={{ width: '100%', boxSizing: 'border-box' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase' }}>
              Your Email Address *
            </label>
            <input
              type="email"
              required
              placeholder="jane@company.com"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              style={{ width: '100%', boxSizing: 'border-box' }}
            />
          </div>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase' }}>
            Message / Query *
          </label>
          <textarea
            required
            rows={5}
            placeholder="Ask a question about ATS matrices, request a new job board, or report an issue..."
            value={contactMessage}
            onChange={(e) => setContactMessage(e.target.value)}
            style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
          />
        </div>

        {contactStatus.text && (
          <div style={{
            padding: '12px 16px',
            borderRadius: '6px',
            fontSize: '0.84rem',
            background: contactStatus.type === 'success' ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
            border: `1px solid ${contactStatus.type === 'success' ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            color: contactStatus.type === 'success' ? '#34D399' : '#F87171'
          }}>
            {contactStatus.text}
          </div>
        )}

        <div>
          <button
            type="submit"
            disabled={contactLoading}
            className="btn"
            style={{ padding: '10px 24px', fontSize: '0.9rem', fontWeight: 700 }}
          >
            {contactLoading ? 'Sending Inquiry...' : 'Submit Inquiry →'}
          </button>
        </div>
      </form>

      {/* Footer Navigation */}
      <div style={{
        marginTop: '40px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingTop: '20px',
        borderTop: '1px solid var(--border-color)',
        fontSize: '0.82rem',
        color: 'var(--text-muted)'
      }}>
        <button
          onClick={() => onNavigate && onNavigate('intro')}
          style={{ background: 'none', border: 'none', padding: 0, color: '#38BDF8', cursor: 'pointer', fontSize: '0.82rem' }}
        >
          ← Return to Overview
        </button>
        <button
          onClick={() => onNavigate && onNavigate('platform')}
          style={{ background: 'none', border: 'none', padding: 0, color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.82rem' }}
        >
          Open Platform Workspace →
        </button>
      </div>
    </div>
  );
}
