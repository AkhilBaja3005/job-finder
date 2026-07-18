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
  handleUrlBlur,
  handleAnalyzeJob,
  handleGenerateTailoredResume,
  onGenerateOutreach,
}) => {
  return (
    <>
      <div className="section-label">Target Job</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
        <input
          type="text"
          placeholder="Job Application URL (LinkedIn, Indeed…)"
          value={jobUrl}
          onChange={(e) => setJobUrl(e.target.value)}
          onBlur={handleUrlBlur}
        />
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
            <button className="btn btn-secondary" style={{ flex: 1 }} onClick={() => handleAnalyzeJob()} disabled={loading}>
              {loading ? '⏳' : '🔍 Analyze Job'}
            </button>
          )}
          <button className="btn" style={{ flex: 1.2, width: analysisResult ? '100%' : 'auto' }} onClick={() => handleGenerateTailoredResume(false)} disabled={loading} title="Analyze & Tailor (Cmd+Enter)">
            {loading ? '⏳' : '⚡ Analyze & Tailor'}
          </button>
        </div>
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
