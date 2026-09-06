import React, { Suspense, lazy } from 'react';

const TailorMode = ({
  jobUrl,
  setJobUrl,
  jobTitle,
  setJobTitle,
  company = '',
  setCompany,
  jobDescription,
  setJobDescription,
  analysisResult,
  loading,
  urlScraping,
  urlScrapeError,
  handleUrlBlur,
  handleAnalyzeJob,
  handleGenerateTailoredResume,
  onGenerateOutreach,
  tailoringIntensity = 'balanced',
  setTailoringIntensity,
}) => {
  const handleJdChange = (text) => {
    setJobDescription(text);
    if ((!company || company === '') && setCompany && text) {
      // Auto-extract company name from text if not already populated
      const m1 = text.match(/(?:^|\n|\.\s+)([A-Z][A-Za-z0-9\s&.,-]{1,30}?)\s+(?:is|are)\s+(?:a|an)\s+/);
      if (m1 && !["the", "this", "our", "a", "an", "there", "it", "here", "what", "who"].includes(m1[1].trim().toLowerCase())) {
        setCompany(m1[1].trim());
      } else {
        const m2 = text.match(/(?:about|at|join|welcome to)\s+([A-Z][A-Za-z0-9\s&.,-]{2,30}?)(?:\s+(?:is|are|we|team|to|for|where|who|\.|\n|,|!))/i);
        if (m2 && !["the", "this", "our", "a", "an", "us"].includes(m2[1].trim().toLowerCase())) {
          setCompany(m2[1].trim());
        }
      }
    }
  };
  return (
    <>
      <div className="section-label">Target Specification</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
        {/* Tailoring Intensity Segmented Control */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          background: 'var(--panel-bg-subtle)',
          border: '1px solid var(--border-color)',
          borderRadius: '6px',
          padding: '8px 10px',
          marginBottom: '12px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>
              Tailoring Strategy
            </span>
            <span style={{ fontSize: '0.7rem', color: '#38BDF8', fontFamily: 'var(--font-mono)' }}>
              {tailoringIntensity === 'conservative' ? 'Strict Keywords' : tailoringIntensity === 'impact' ? 'Metrics & ROI Focus' : 'Balanced'}
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px', marginTop: '2px' }}>
            {[
              { id: 'conservative', label: 'Strict' },
              { id: 'balanced', label: 'Balanced' },
              { id: 'impact', label: 'Impact' }
            ].map((mode) => (
              <button
                key={mode.id}
                type="button"
                style={{
                  padding: '5px 4px',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  borderRadius: '4px',
                  border: `1px solid ${tailoringIntensity === mode.id ? '#2563EB' : 'transparent'}`,
                  background: tailoringIntensity === mode.id ? 'rgba(37, 99, 235, 0.25)' : 'rgba(255,255,255,0.02)',
                  color: tailoringIntensity === mode.id ? '#FFFFFF' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
                onClick={() => setTailoringIntensity && setTailoringIntensity(mode.id)}
              >
                {mode.label}
              </button>
            ))}
          </div>
        </div>

        <input
          type="text"
          placeholder="Job Application URL (LinkedIn, Greenhouse, Ashby…)"
          value={jobUrl}
          onChange={(e) => setJobUrl(e.target.value)}
          onBlur={handleUrlBlur}
        />
        {(urlScraping || urlScrapeError) && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.74rem',
            marginTop: '-8px', marginBottom: '10px',
            color: urlScrapeError ? 'var(--accent-red)' : 'var(--accent-secondary)'
          }}>
            {urlScraping ? (
              <>Scraping job description from URL…</>
            ) : (
              <>{urlScrapeError}</>
            )}
          </div>
        )}
        <input
          type="text"
          placeholder="Job Title (e.g. Senior Distributed Systems Engineer)"
          value={jobTitle}
          onChange={(e) => setJobTitle(e.target.value)}
        />
        <textarea
          placeholder="Paste Job Description (optional if URL provided)"
          rows="6"
          value={jobDescription}
          onChange={(e) => handleJdChange(e.target.value)}
        />
        <div style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)', color: jobDescription.length > 500 ? 'var(--accent-green)' : 'var(--text-muted)', marginTop: '-8px', marginBottom: '10px', textAlign: 'right' }}>
          {jobDescription.length.toLocaleString()} chars{jobDescription.length < 200 ? ' (paste more for higher accuracy)' : jobDescription.length < 500 ? ' (standard)' : ' (complete spec)'}
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
          {!analysisResult && (
            <button className="btn btn-secondary" style={{ flex: 1 }} onClick={() => handleAnalyzeJob()} disabled={loading || urlScraping} title="Analyze ATS match score without modifying resume">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              <span>{loading ? 'Analyzing…' : 'Analyze Spec'}</span>
            </button>
          )}
          <button className="btn" style={{ flex: 1.2, width: analysisResult ? '100%' : 'auto' }} onClick={() => handleGenerateTailoredResume(false)} disabled={loading || urlScraping} title="Score + rewrite your resume and cover letter for this job">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
            </svg>
            <span>{loading ? 'Tailoring…' : 'Analyze & Tailor'}</span>
          </button>
        </div>
        {!analysisResult && (
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '8px', lineHeight: 1.5 }}>
            <strong>Analyze Spec</strong> evaluates keyword vector match. <strong>Analyze &amp; Tailor</strong> optimizes LaTeX bullets to strict 1-page budget.
          </div>
        )}
        {analysisResult && (
          <button
            className="btn btn-secondary"
            style={{ marginTop: '10px', width: '100%' }}
            onClick={onGenerateOutreach}
            disabled={loading}
            title="Generate personalized recruiter outreach message"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
              <polyline points="22,6 12,13 2,6"></polyline>
            </svg>
            <span>Generate InMail &amp; Outreach</span>
          </button>
        )}
        {/* Optimization #2: Keyboard shortcut label - hidden on mobile */}
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '6px', textAlign: 'center', display: 'none' }}>
          <span style={{ display: 'none' }}>⌘ Cmd+Enter</span>
        </div>
        <style>{`
          @media (min-width: 641px) {
            .keyboard-hint { display: block !important; }
          }
        `}</style>
      </div>
    </>
  );
};

export default TailorMode;
