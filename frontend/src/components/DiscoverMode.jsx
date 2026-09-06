import React from 'react';

const DiscoverMode = ({
  searchKeywords,
  setSearchKeywords,
  searchLocation,
  setSearchLocation,
  searchTimeframe,
  setSearchTimeframe,
  targetPlatform = 'all',
  setTargetPlatform,
  discovering,
  loading,
  handleSearchJobs,
  primaryRole = '',
}) => {
  const rolePresets = ['AI Engineer', 'ML Systems', 'Product Engineer', 'Full Stack'];
  const platformPills = [
    { id: 'all', label: 'All' },
    { id: 'ashby', label: 'Ashby' },
    { id: 'greenhouse', label: 'Greenhouse' },
    { id: 'lever', label: 'Lever' },
    { id: 'linkedin', label: 'LinkedIn' },
    { id: 'workday', label: 'Workday' },
  ];

  return (
    <>
      <div className="section-label">Direct ATS Discovery &amp; Feeds</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {/* Role input */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 700, letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>TARGET ROLE</span>
            {primaryRole && !searchKeywords && (
              <button
                type="button"
                onClick={() => setSearchKeywords(primaryRole)}
                style={{ background: 'none', border: 'none', color: '#38BDF8', fontSize: '0.7rem', cursor: 'pointer', padding: 0, fontWeight: 600, fontFamily: 'var(--font-mono)' }}
              >
                Use Primary: {primaryRole}
              </button>
            )}
          </div>
          <input
            type="text"
            placeholder="Auto-inferred from calibrated profile if blank"
            value={searchKeywords}
            onChange={(e) => setSearchKeywords(e.target.value)}
            style={{ marginBottom: '6px' }}
          />
          {/* Presets */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '2px' }}>
            {rolePresets.map((preset) => {
              const isSelected = searchKeywords.toLowerCase() === preset.toLowerCase();
              return (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setSearchKeywords(isSelected ? '' : preset)}
                  style={{
                    padding: '3px 8px',
                    borderRadius: '4px',
                    fontSize: '0.72rem',
                    fontWeight: 500,
                    cursor: 'pointer',
                    background: isSelected ? 'rgba(37, 99, 235, 0.25)' : 'rgba(255, 255, 255, 0.03)',
                    border: `1px solid ${isSelected ? '#2563EB' : 'var(--border-color)'}`,
                    color: isSelected ? '#FFFFFF' : '#94A3B8',
                    transition: 'all 0.15s ease',
                    fontFamily: 'var(--font-mono)'
                  }}
                >
                  {preset}
                </button>
              );
            })}
          </div>
        </div>

        {/* Location input */}
        <div>
          <span style={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 700, display: 'block', marginBottom: '6px', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>LOCATION / WORKSPACE</span>
          <input
            type="text"
            placeholder="e.g. Remote, San Francisco, London, Bengaluru"
            value={searchLocation}
            onChange={(e) => setSearchLocation(e.target.value)}
            style={{ marginBottom: '2px' }}
          />
        </div>

        {/* Timeline Dropdown */}
        <div>
          <span style={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 700, display: 'block', marginBottom: '6px', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>POSTING FRESHNESS</span>
          <select
            value={searchTimeframe}
            onChange={(e) => setSearchTimeframe(e.target.value)}
            style={{
              width: '100%',
              padding: '9px 12px',
              borderRadius: '6px',
              background: 'var(--input-bg)',
              border: '1px solid var(--border-color)',
              color: '#fff',
              fontSize: '0.84rem'
            }}
          >
            <option value="24h">Past 24 Hours (Today)</option>
            <option value="48h">Past 48 Hours (Recommended)</option>
            <option value="7d">Past 7 Days</option>
            <option value="1m">Past 30 Days</option>
          </select>
        </div>

        {/* Platform Filter Pills */}
        <div>
          <span style={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 700, display: 'block', marginBottom: '8px', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>ATS PLATFORMS</span>
          <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
            {platformPills.map((pill) => {
              const active = (targetPlatform || 'all').toLowerCase() === pill.id.toLowerCase();
              return (
                <button
                  key={pill.id}
                  type="button"
                  onClick={() => setTargetPlatform && setTargetPlatform(pill.id)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '4px',
                    fontSize: '0.72rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    background: active ? 'rgba(37, 99, 235, 0.25)' : 'rgba(255, 255, 255, 0.02)',
                    border: `1px solid ${active ? '#2563EB' : 'var(--border-color)'}`,
                    color: active ? '#FFFFFF' : '#94A3B8',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    transition: 'all 0.15s ease',
                    fontFamily: 'var(--font-mono)'
                  }}
                >
                  <span style={{
                    width: '5px',
                    height: '5px',
                    borderRadius: '50%',
                    background: active ? '#38BDF8' : '#64748b'
                  }} />
                  {pill.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <button
        className="btn"
        style={{
          width: '100%',
          marginTop: '16px',
          padding: '11px',
          gap: '8px'
        }}
        onClick={handleSearchJobs}
        disabled={discovering || loading}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: discovering ? 'spin 1s linear infinite' : 'none' }}>
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <span>
          {discovering
            ? 'Scanning Direct ATS Feeds…'
            : `Search Active Postings (${searchTimeframe === '24h' ? '24h' : searchTimeframe === '48h' ? '48h' : searchTimeframe === '7d' ? '7d' : '30d'})`}
        </span>
      </button>
    </>
  );
};

export default DiscoverMode;
