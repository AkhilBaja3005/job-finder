import React from 'react';

const DiscoverMode = ({
  searchKeywords,
  setSearchKeywords,
  searchLocation,
  setSearchLocation,
  searchTimeframe,
  setSearchTimeframe,
  discovering,
  loading,
  handleSearchJobs,
}) => {
  return (
    <>
      <div className="section-label">Job Discoverer</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <input
          type="text"
          placeholder="Preferred Role (e.g. Data Scientist, AI Engineer)"
          value={searchKeywords}
          onChange={(e) => setSearchKeywords(e.target.value)}
          style={{ marginBottom: '2px' }}
        />
        <input
          type="text"
          placeholder="Location (e.g. San Francisco, Remote)"
          value={searchLocation}
          onChange={(e) => setSearchLocation(e.target.value)}
          style={{ marginBottom: '2px' }}
        />
        <select
          value={searchTimeframe}
          onChange={(e) => setSearchTimeframe(e.target.value)}
          style={{
            padding: '10px 12px',
            borderRadius: '8px',
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.12)',
            color: '#fff'
          }}
        >
          <option value="24h">Last 24 Hours</option>
          <option value="48h">Last 48 Hours</option>
          <option value="1w">Last 1 Week</option>
          <option value="1m">Last 1 Month</option>
        </select>
      </div>
      <button
        className="btn btn-secondary"
        style={{
          width: '100%',
          background: 'linear-gradient(135deg, rgba(56,189,248,0.12) 0%, rgba(37,99,235,0.06) 100%)',
          border: '1px solid rgba(56,189,248,0.25)',
          color: '#7dd3fc',
          fontWeight: 600,
          padding: '12px'
        }}
        onClick={handleSearchJobs}
        disabled={discovering || loading}
      >
        {discovering ? '⏳ Scanning Feeds...' : `🔍 Scan Matches (${searchTimeframe === '24h' ? 'Last 24h' : searchTimeframe === '48h' ? 'Last 48h' : searchTimeframe === '1w' ? 'Last 1w' : 'Last 1m'})`}
      </button>
    </>
  );
};

export default DiscoverMode;
