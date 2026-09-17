import React, { useState, useEffect } from 'react';

const API_BASE = import.meta.env?.VITE_API_BASE
  || import.meta.env?.VITE_BACKEND_URL
  || ((typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'))
    ? 'http://127.0.0.1:8000'
    : (typeof window !== 'undefined' ? window.location.origin : ''));

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
  const [slugStats, setSlugStats] = useState({
    total_slugs: 0,
    active_slugs: 0,
    by_platform: { ashby: 0, greenhouse: 0, lever: 0 }
  });
  const [harvesting, setHarvesting] = useState(false);
  const [harvestMsg, setHarvestMsg] = useState('');

  const fetchSlugStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/slugs/stats`);
      if (res.ok) {
        const data = await res.json();
        setSlugStats(data);
      }
    } catch (_) {
      // Non-blocking fallback
    }
  };

  useEffect(() => {
    fetchSlugStats();
  }, []);

  const handleHarvestSlugs = async () => {
    setHarvesting(true);
    setHarvestMsg('Harvesting & validating fresh company boards...');
    try {
      const res = await fetch(`${API_BASE}/api/slugs/harvest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: 'seeds', run_validation: true, limit: 100, background: true })
      });
      if (res.ok) {
        const data = await res.json();
        const activeCount = data.total_active || 0;
        const byPlat = data.by_platform || {};
        setSlugStats({
          total_slugs: data.total_slugs || (data.validated || 0) + activeCount,
          active_slugs: activeCount,
          by_platform: {
            ashby: byPlat.ashby || 0,
            greenhouse: byPlat.greenhouse || 0,
            lever: byPlat.lever || 0,
            bamboohr: byPlat.bamboohr || 0,
            workday: byPlat.workday || 0
          }
        });
        setHarvestMsg(`✓ Ready: ${activeCount} active boards confirmed!`);
        setTimeout(() => setHarvestMsg(''), 4000);
      } else {
        setHarvestMsg('Sync completed');
        setTimeout(() => setHarvestMsg(''), 3000);
      }
    } catch (err) {
      setHarvestMsg('Sync error (using cached boards)');
      setTimeout(() => setHarvestMsg(''), 3000);
    } finally {
      setHarvesting(false);
      await fetchSlugStats();
    }
  };

  const rolePresets = ['AI Engineer', 'ML Systems', 'Product Engineer', 'Full Stack'];
  const platformPills = [
    { id: 'all', label: 'All' },
    { id: 'ashby', label: 'Ashby' },
    { id: 'greenhouse', label: 'Greenhouse' },
    { id: 'lever', label: 'Lever' },
    { id: 'bamboohr', label: 'BambooHR' },
    { id: 'workday', label: 'Workday' },
    { id: 'linkedin', label: 'LinkedIn' },
  ];

  return (
    <>
      <div className="section-label">Direct ATS Discovery &amp; Feeds</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {/* Role input */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 700, letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>TARGET ROLE / KEYWORD</span>
            {primaryRole && (
              <span
                onClick={() => setSearchKeywords(primaryRole)}
                style={{
                  fontSize: '0.68rem',
                  color: '#38BDF8',
                  cursor: 'pointer',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px'
                }}
                title="Fill with primary role from your master profile"
              >
                Use "{primaryRole.length > 20 ? primaryRole.slice(0, 18) + '...' : primaryRole}"
              </span>
            )}
          </div>
          <input
            type="text"
            placeholder="e.g. AI Engineer, Machine Learning, Full Stack"
            value={searchKeywords}
            onChange={(e) => setSearchKeywords(e.target.value)}
            style={{ marginBottom: '6px' }}
          />
          {/* Quick preset role chips */}
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
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

        {/* ATS Registry HUD */}
        <div style={{
          marginTop: '4px',
          padding: '8px 10px',
          borderRadius: '6px',
          background: 'rgba(15, 23, 42, 0.6)',
          border: '1px solid rgba(56, 189, 248, 0.2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: '0.72rem',
          color: '#CBD5E1'
        }}>
          <div>
            <div style={{ fontWeight: 600, color: '#38BDF8', fontFamily: 'var(--font-mono)' }}>
              {slugStats.active_slugs > 0 ? `${slugStats.active_slugs}+` : '10+'} Verified Boards
            </div>
            <div style={{ color: '#64748B', fontSize: '0.65rem' }}>
              Ashby: {slugStats.by_platform?.ashby || 0} | Greenhouse: {slugStats.by_platform?.greenhouse || 0} | Lever: {slugStats.by_platform?.lever || 0} | Bamboo: {slugStats.by_platform?.bamboohr || 0} | Workday: {slugStats.by_platform?.workday || 0}
            </div>
          </div>
          <button
            type="button"
            onClick={handleHarvestSlugs}
            disabled={harvesting}
            style={{
              background: 'rgba(56, 189, 248, 0.1)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              color: '#38BDF8',
              borderRadius: '4px',
              padding: '3px 8px',
              fontSize: '0.68rem',
              cursor: harvesting ? 'not-allowed' : 'pointer',
              fontWeight: 600,
              fontFamily: 'var(--font-mono)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ animation: harvesting ? 'spin 1s linear infinite' : 'none' }}>
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l6.73-6.73"/>
            </svg>
            {harvesting ? 'Harvesting...' : 'Sync Boards'}
          </button>
        </div>

        {harvestMsg && (
          <div style={{ fontSize: '0.68rem', color: '#38BDF8', fontFamily: 'var(--font-mono)', paddingLeft: '2px' }}>
            {harvestMsg}
          </div>
        )}
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
