import React, { Suspense, lazy } from 'react';

const TailorMode = ({
  jobUrl,
  setJobUrl,
  jobTitle,
  setJobTitle,
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
  return (
    <>
      <div className="section-label">Target Job</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
        {/* Tailoring Intensity Segmented Control */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '10px',
          padding: '8px 10px',
          marginBottom: '12px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--accent-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Tailoring Strategy
            </span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {tailoringIntensity === 'conservative' ? '🛡️ Strict Keywords' : tailoringIntensity === 'impact' ? '🚀 Metrics & ROI Focus' : '⚖️ Balanced (Recommended)'}
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', marginTop: '2px' }}>
            {[
              { id: 'conservative', label: '🛡️ Strict' },
              { id: 'balanced', label: '⚖️ Balanced' },
              { id: 'impact', label: '🚀 Impact' }
            ].map((mode) => (
              <button
                key={mode.id}
                type="button"
                style={{
                  padding: '6px 4px',
                  fontSize: '0.76rem',
                  fontWeight: 700,
                  borderRadius: '6px',
                  border: `1px solid ${tailoringIntensity === mode.id ? 'var(--accent-primary)' : 'rgba(255,255,255,0.08)'}`,
                  background: tailoringIntensity === mode.id ? 'rgba(56, 189, 248, 0.2)' : 'rgba(0,0,0,0.2)',
                  color: tailoringIntensity === mode.id ? '#38bdf8' : 'var(--text-muted)',
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
          placeholder="Job Application URL (LinkedIn, Indeed…)"
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
              <>⏳ Scraping job description from URL…</>
            ) : (
              <>⚠️ {urlScrapeError}</>
            )}
          </div>
        )}
        <input
          type="text"
          placeholder="Job Title (e.g. Software Engineer)"
          value={jobTitle}
          onChange={(e) => setJobTitle(e.target.value)}
        />
        <textarea
          placeholder="Paste Job Description (optional if URL provided)"
          rows="6"
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
        />
        <div style={{ fontSize: '0.72rem', color: jobDescription.length > 500 ? 'var(--accent-green)' : 'var(--text-muted)', marginTop: '-8px', marginBottom: '10px', textAlign: 'right' }}>
          {jobDescription.length.toLocaleString()} chars{jobDescription.length < 200 ? ' — paste more for better results' : jobDescription.length < 500 ? ' — good' : ' — ✅ detailed'}
        </div>
        <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
          {!analysisResult && (
            <button className="btn btn-secondary" style={{ flex: 1 }} onClick={() => handleAnalyzeJob()} disabled={loading || urlScraping} title="Get your ATS match score only — no resume changes yet">
              {loading ? '⏳' : '🔍 Analyze Job'}
            </button>
          )}
          <button className="btn" style={{ flex: 1.2, width: analysisResult ? '100%' : 'auto' }} onClick={() => handleGenerateTailoredResume(false)} disabled={loading || urlScraping} title="Score + rewrite your resume and cover letter for this job (Cmd+Enter)">
            {loading ? '⏳' : '⚡ Analyze & Tailor'}
          </button>
        </div>
        {!analysisResult && (
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '6px', lineHeight: 1.5 }}>
            <strong>Analyze Job</strong> gives you a quick match score. <strong>Analyze &amp; Tailor</strong> also rewrites your resume &amp; cover letter for this job.
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
            {loading ? '⏳' : '💌 Generate Outreach'}
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
