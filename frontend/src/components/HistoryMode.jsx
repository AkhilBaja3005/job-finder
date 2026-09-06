import React from 'react';

const HistoryMode = ({
  historyLoading,
  handleFetchHistory,
}) => {
  return (
    <>
      <div className="section-label">Pipeline History</div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
        A persistent ledger of targeted applications, tailored LaTeX bundles, and pipeline stages.
      </div>
      <button
        className="btn btn-secondary"
        style={{ width: '100%', marginTop: '6px', gap: '6px' }}
        onClick={handleFetchHistory}
        disabled={historyLoading}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: historyLoading ? 'spin 1s linear infinite' : 'none' }}>
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
        </svg>
        <span>{historyLoading ? 'Refreshing Pipeline…' : 'Refresh Pipeline'}</span>
      </button>

      {/* Quick History Tips & Actions Box */}
      <div style={{
        marginTop: '16px',
        padding: '12px',
        background: 'var(--panel-bg-subtle)',
        border: '1px solid var(--border-color)',
        borderRadius: '8px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px'
      }}>
        <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>
          Pipeline Operations
        </div>
        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
          Toggle status between <span style={{ color: '#38BDF8', fontWeight: 600 }}>Tailored</span> and <span style={{ color: '#10B981', fontWeight: 600 }}>Applied</span> to calibrate pipeline metrics in real-time.
        </div>
        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
          Launch on-demand modals (Interview Prep, Cover Letter, Outreach InMail) directly from any application record.
        </div>
      </div>
    </>
  );
};

export default HistoryMode;
