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
        style={{ width: '100%', marginTop: '4px' }}
        onClick={handleFetchHistory}
        disabled={historyLoading}
      >
        {historyLoading ? '⏳ Refreshing...' : '🔄 Refresh History'}
      </button>
    </>
  );
};

export default HistoryMode;
