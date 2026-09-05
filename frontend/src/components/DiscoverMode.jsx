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
      <div className="section-label">Job Discoverer · Direct ATS Grounding & Job Feeds</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {/* Role input */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '0.74rem', color: '#94A3B8', fontWeight: 600, letterSpacing: '0.02em' }}>TARGET ROLE</span>
            {primaryRole && !searchKeywords && (
              <button
                type="button"
                onClick={() => setSearchKeywords(primaryRole)}
                style={{ background: 'none', border: 'none', color: '#38BDF8', fontSize: '0.7rem', cursor: 'pointer', padding: 0, fontWeight: 600 }}
              >
                Use Primary: {primaryRole}
              </button>
            )}
          </div>
          <input
            type="text"
            placeholder="Auto-inferred from resume if blank"
            value={searchKeywords}
            onChange={(e) => setSearchKeywords(e.target.value)}
            style={{ marginBottom: '6px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)' }}
          />
          {/* Presets */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '4px' }}>
            {rolePresets.map((preset) => {
              const isSelected = searchKeywords.toLowerCase() === preset.toLowerCase();
              return (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setSearchKeywords(isSelected ? '' : preset)}
                  style={{
                    padding: '3px 9px',
                    borderRadius: '8px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    background: isSelected ? 'rgba(56, 189, 248, 0.2)' : 'rgba(255, 255, 255, 0.03)',
                    border: `1px solid ${isSelected ? '#38BDF8' : 'rgba(255, 255, 255, 0.08)'}`,
                    color: isSelected ? '#38BDF8' : '#94A3B8',
                    transition: 'all 0.15s ease'
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
          <span style={{ fontSize: '0.74rem', color: '#94A3B8', fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.02em' }}>LOCATION</span>
          <input
            type="text"
            placeholder="Location (e.g. Remote, London, San Francisco)"
            value={searchLocation}
            onChange={(e) => setSearchLocation(e.target.value)}
            style={{ marginBottom: '2px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)' }}
          />
        </div>

        {/* Timeline Dropdown */}
        <div>
          <span style={{ fontSize: '0.74rem', color: '#94A3B8', fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.02em' }}>POSTING FRESHNESS</span>
          <select
            value={searchTimeframe}
            onChange={(e) => setSearchTimeframe(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '8px',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: '#fff',
              fontSize: '0.84rem'
            }}
          >
            <option value="24h">Past 24 Hours (Today)</option>
            <option value="48h">Past 48 Hours (Default)</option>
            <option value="7d">Past 7 Days (This Week)</option>
            <option value="1m">Past 30 Days</option>
          </select>
        </div>

        {/* Platform Filter Pills */}
        <div>
          <span style={{ fontSize: '0.74rem', color: '#94A3B8', fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.02em' }}>FILTER BY ATS PLATFORM</span>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {platformPills.map((pill) => {
              const active = (targetPlatform || 'all').toLowerCase() === pill.id.toLowerCase();
              return (
                <button
                  key={pill.id}
                  type="button"
                  onClick={() => setTargetPlatform && setTargetPlatform(pill.id)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '8px',
                    fontSize: '0.72rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    background: active
                      ? 'rgba(56, 189, 248, 0.2)'
                      : 'rgba(255, 255, 255, 0.03)',
                    border: `1px solid ${active ? '#38BDF8' : 'rgba(255, 255, 255, 0.08)'}`,
                    color: active ? '#FFFFFF' : '#94A3B8',
                    transition: 'all 0.15s ease'
                  }}
                >
                  {pill.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <button
        className="btn btn-secondary"
        style={{
          width: '100%',
          marginTop: '16px',
          background: 'linear-gradient(135deg, rgba(56,189,248,0.18) 0%, rgba(37,99,235,0.12) 100%)',
          border: '1px solid rgba(56,189,248,0.35)',
          color: '#7dd3fc',
          fontWeight: 700,
          padding: '13px',
          borderRadius: '10px',
          letterSpacing: '0.01em',
          boxShadow: '0 4px 14px rgba(56,189,248,0.1)'
        }}
        onClick={handleSearchJobs}
        disabled={discovering || loading}
      >
        {discovering
          ? '⏳ Scanning Direct ATS Grounding & Feeds...'
          : `🔍 Discover Jobs · ATS & Feeds (${searchTimeframe === '24h' ? 'Past 24h' : searchTimeframe === '48h' ? 'Past 48h' : searchTimeframe === '7d' ? 'Past 7d' : 'Past 30d'})`}
      </button>
    </>
  );
};

export default DiscoverMode;
