import React, { useState, useEffect } from 'react';

const SkillsHeatmapWidget = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/applications/skills_heatmap')
      .then(res => res.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '12px' }}>Loading ATS skills heatmap…</div>;
  if (!data || (!data.top_matched_skills?.length && !data.top_missing_skills?.length)) return null;

  return (
    <div style={{
      marginTop: '16px',
      padding: '12px',
      background: 'var(--panel-bg-subtle)',
      border: '1px solid var(--border-color)',
      borderRadius: '8px'
    }}>
      <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)', marginBottom: '8px' }}>
        📊 ATS Keyword Gap & Skill Heatmap
      </div>
      {data.top_matched_skills?.length > 0 && (
        <div style={{ marginBottom: '8px' }}>
          <div style={{ fontSize: '0.7rem', color: '#34D399', fontWeight: 700, marginBottom: '4px' }}>Top Matched Skills:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            {data.top_matched_skills.map((s, i) => (
              <span key={i} style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.35)', color: '#34D399', padding: '2px 7px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600 }}>
                {s.skill} ({s.count})
              </span>
            ))}
          </div>
        </div>
      )}
      {data.top_missing_skills?.length > 0 && (
        <div>
          <div style={{ fontSize: '0.7rem', color: '#F87171', fontWeight: 700, marginBottom: '4px' }}>Top Missing Keyword Gaps:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            {data.top_missing_skills.map((s, i) => (
              <span key={i} style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.35)', color: '#F87171', padding: '2px 7px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600 }}>
                {s.skill} ({s.count})
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

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

      {/* Interactive ATS Skills Heatmap Widget */}
      <SkillsHeatmapWidget />
    </>
  );
};

export default HistoryMode;
