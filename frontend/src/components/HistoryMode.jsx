import React from 'react';

const HistoryMode = ({
  historyLoading,
  handleFetchHistory,
}) => {
  return (
    <>
      <div className="section-label">Application History</div>
      <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>
        A record of jobs you've tailored a resume for or applied to. Kept per-account (or per-guest browser).
      </div>
      <button
        className="btn btn-secondary"
        style={{ width: '100%', marginTop: '4px', gap: '8px' }}
        onClick={handleFetchHistory}
        disabled={historyLoading}
      >
        {historyLoading ? '⏳ Refreshing...' : '🔄 Refresh History'}
      </button>

      {/* Quick History Tips & Actions Box */}
      <div style={{
        marginTop: '16px',
        padding: '14px',
        background: 'rgba(255, 255, 255, 0.02)',
        border: '1px solid var(--border-color)',
        borderRadius: '12px',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px'
      }}>
        <div style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--accent-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          💡 Pipeline Mastery
        </div>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          Toggle status between <strong style={{ color: 'var(--accent-cyan)' }}>Tailored</strong> and <strong style={{ color: 'var(--accent-green)' }}>Applied</strong> on any card to update your funnel metrics in real-time.
        </div>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          Use the <strong style={{ color: '#fff' }}>1-Click Modals</strong> (🎤 Prep, 📝 Cover Letter, ✉️ Outreach) on each application to instantly generate tailored material for that specific employer.
        </div>
      </div>
    </>
  );
};

export default HistoryMode;
