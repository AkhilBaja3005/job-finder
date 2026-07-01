import React, { useState, useEffect } from 'react';

const API_BASE = window.location.hostname === 'localhost' ? 'http://localhost:8000' : window.location.origin;

const RocketIcon = () => (
  <svg
    width="32"
    height="32"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className="rocket-icon"
  >
    <path
      d="M21 3C18 3 13.5 4.5 10.5 7.5C8.5 9.5 8 12.5 8.5 14.5L3.5 19.5C3.2 19.8 3.2 20.2 3.5 20.5C3.8 20.8 4.2 20.8 4.5 20.5L9.5 15.5C11.5 16 14.5 15.5 16.5 13.5C19.5 10.5 21 6 21 3Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M16 8L15 9"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M9 15L8 16"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M12 12C12.5523 12 13 11.5523 13 11C13 10.4477 12.5523 10 12 10C11.4477 10 11 10.4477 11 11C11 11.5523 11.4477 12 12 12Z"
      fill="currentColor"
    />
  </svg>
);

function App() {
  const [resumeData, setResumeData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [jobUrl, setJobUrl] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [tailoredResumeData, setTailoredResumeData] = useState(null);
  const [directMode, setDirectMode] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [statusLogs, setStatusLogs] = useState([]);
  const [activeTab, setActiveTab] = useState('preview');
  const [keepOriginalMode, setKeepOriginalMode] = useState(false);
  const [geminiApiKey, setGeminiApiKey] = useState(localStorage.getItem('gemini_api_key') || '');

  const [user, setUser] = useState(null);
  const [authToken, setAuthToken] = useState(localStorage.getItem('auth_token') || '');
  const [mockEmail, setMockEmail] = useState('');
  const [configStepActive, setConfigStepActive] = useState(true);

  const handleApiKeyChange = (e) => {
    const val = e.target.value;
    setGeminiApiKey(val);
    localStorage.setItem('gemini_api_key', val);
  };

  useEffect(() => {
    const urlToken = new URLSearchParams(window.location.search).get('token');
    if (urlToken) {
      localStorage.setItem('auth_token', urlToken);
      setAuthToken(urlToken);
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  useEffect(() => {
    const fetchUser = async () => {
      if (!authToken) {
        setUser(null);
        return;
      }
      try {
        const res = await fetch(`${API_BASE}/user/me`, {
          headers: { 'Authorization': `Bearer ${authToken}` }
        });
        if (res.ok) {
          const data = await res.json();
          setUser(data);
          if (data.gemini_api_key) {
            setGeminiApiKey(data.gemini_api_key);
          }
        } else {
          handleLogout();
        }
      } catch (err) {
        console.error('Failed to fetch user', err);
      }
    };
    fetchUser();
  }, [authToken]);

  // Fetch persisted resume state on boot
  useEffect(() => {
    const fetchResume = async () => {
      try {
        const headers = {};
        if (authToken) {
          headers['Authorization'] = `Bearer ${authToken}`;
        }
        const res = await fetch(`${API_BASE}/user/resume`, { headers });
        if (res.ok) {
          const body = await res.json();
          if (body.data && Object.keys(body.data).length > 0) {
            setResumeData(body.data);
            setStatusMessage('Loaded persisted resume state.');
          }
        }
      } catch (err) {
        console.error('Failed to load persisted resume', err);
      }
    };
    fetchResume();
  }, [authToken]);

  const handleLogout = () => {
    localStorage.removeItem('auth_token');
    setAuthToken('');
    setUser(null);
    setStatusMessage('Logged out successfully.');
  };

  const handleGoogleLogin = async () => {
    setLoading(true);
    setStatusMessage('Redirecting to Google login...');
    try {
      const res = await fetch(`${API_BASE}/auth/url`);
      const data = await res.json();
      window.location.href = data.url;
    } catch (err) {
      setStatusMessage(`OAuth failed: ${err.message}`);
      setLoading(false);
    }
  };

  const handleMockLogin = async () => {
    if (!mockEmail) {
      alert('Please enter a mock email.');
      return;
    }
    setLoading(true);
    setStatusMessage('Logging in via mock flow...');
    try {
      const res = await fetch(`${API_BASE}/auth/mock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: mockEmail })
      });
      const data = await res.json();
      localStorage.setItem('auth_token', data.token);
      setAuthToken(data.token);
      setStatusMessage('Mock logged in!');
    } catch (err) {
      setStatusMessage(`Mock login failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const saveApiKeyToCloud = async () => {
    if (!authToken) return;
    setLoading(true);
    setStatusMessage('Saving API key to cloud settings...');
    try {
      const res = await fetch(`${API_BASE}/user/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({ gemini_api_key: geminiApiKey })
      });
      if (res.ok) {
        setStatusMessage('API Key saved to cloud settings successfully!');
        const meRes = await fetch(`${API_BASE}/user/me`, {
          headers: { 'Authorization': `Bearer ${authToken}` }
        });
        const meData = await meRes.json();
        setUser(meData);
      } else {
        throw new Error('Failed to save settings');
      }
    } catch (err) {
      setStatusMessage(`Error saving settings: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Handle Resume Upload
  const handleResumeUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const headers = {};
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const response = await fetch(`${API_BASE}/upload_resume`, {
        method: 'POST',
        headers: headers,
        body: formData,
      });
      const result = await response.json();
      if (response.ok) {
        setResumeData(result.data);
        setStatusMessage('Resume parsed successfully!');
      } else {
        setStatusMessage(`Error parsing resume: ${result.detail}`);
      }
    } catch (err) {
      setStatusMessage(`Error connecting to backend: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Step 1: Initial Job Analysis & Scoring (Fast ATS evaluation)
  const handleAnalyzeJob = async () => {
    if (!resumeData) {
      alert('Please upload a resume first.');
      return;
    }

    setLoading(true);
    setAnalysisResult(null);
    setTailoredResumeData(null);
    setKeepOriginalMode(false);
    setStatusLogs([]);
    setStatusMessage('Connecting to AI agent pipeline...');

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) {
        headers['X-Gemini-API-Key'] = geminiApiKey;
      }
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const response = await fetch(`${API_BASE}/analyze_job`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          job_url: jobUrl || null,
          job_title: jobTitle || 'Target Role',
          job_description: jobDescription || null,
          skip_tailoring: true, // Only calculate ATS scores and gap analysis
        }),
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || 'Failed to analyze job.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line);
            if (event.type === 'log') {
              setStatusMessage(event.message);
              setStatusLogs((prev) => [...prev, event.message]);
            } else if (event.type === 'error') {
              throw new Error(event.message);
            } else if (event.type === 'result') {
              const result = event;
              setAnalysisResult(result.analysis);
              if (result.job_title) {
                setJobTitle(result.job_title);
              }
              if (result.job_description) {
                setJobDescription(result.job_description);
              }

              const updates = result.analysis.suggested_resume_updates || {};
              const tailored = {
                ...resumeData,
                summary: updates.summary || (resumeData || {}).summary || '',
                skills: updates.skills || (resumeData || {}).skills || [],
                experience: ((resumeData || {}).experience || []).map((job, idx) => {
                  const tailoredExperience = updates.experience && updates.experience[idx];
                  return {
                    ...job,
                    // If tailoredExperience is a list/array of bullets directly, use it, else fallback
                    description: Array.isArray(tailoredExperience) ? tailoredExperience : (tailoredExperience && tailoredExperience.description) || (job || {}).description || [],
                  };
                }),
              };
              setTailoredResumeData(tailored);
              setStatusMessage('ATS Scoring complete! Awaiting your instruction to tailor the resume.');
            }
          } catch (e) {
            if (e instanceof SyntaxError) {
              // Ignore incomplete lines
            } else {
              throw e;
            }
          }
        }
      }
    } catch (error) {
      console.error(error);
      setStatusMessage(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Full LaTeX tailoring and recruiter check loop (when user decides to go ahead)
  const handleGenerateTailoredResume = async () => {
    if (!resumeData) {
      alert('Please upload a resume first.');
      return;
    }

    setLoading(true);
    setStatusMessage('Tailoring resume LaTeX and running recruiter loop...');
    setStatusLogs((prev) => [...prev, '🤖 Requesting LaTeX tailoring and page-metric checks...']);

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) {
        headers['X-Gemini-API-Key'] = geminiApiKey;
      }
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const response = await fetch(`${API_BASE}/analyze_job`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          job_url: jobUrl || null,
          job_title: jobTitle || 'Target Role',
          job_description: jobDescription || null,
          skip_tailoring: false, // Run full LaTeX tailoring + page checks + reviewer checks
        }),
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || 'Failed to tailor resume.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line);
            if (event.type === 'log') {
              setStatusMessage(event.message);
              setStatusLogs((prev) => [...prev, event.message]);
            } else if (event.type === 'error') {
              throw new Error(event.message);
            } else if (event.type === 'result') {
               const result = event;
               setAnalysisResult(result.analysis);
               const updates = result.analysis.suggested_resume_updates || {};
               const tailored = {
                 ...resumeData,
                 summary: updates.summary || (resumeData || {}).summary || '',
                 skills: updates.skills || (resumeData || {}).skills || [],
                 experience: ((resumeData || {}).experience || []).map((job, idx) => {
                   const tailoredExperience = updates.experience && updates.experience[idx];
                   return {
                     ...job,
                     description: Array.isArray(tailoredExperience) ? tailoredExperience : (tailoredExperience && tailoredExperience.description) || (job || {}).description || [],
                   };
                 }),
               };
               setTailoredResumeData(tailored);
               setStatusMessage('LaTeX tailored resume and metrics prepared successfully!');
            }
          } catch (e) {
            if (e instanceof SyntaxError) {
              // Ignore incomplete lines
            } else {
              throw e;
            }
          }
        }
      }
    } catch (error) {
      console.error(error);
      setStatusMessage(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleUrlBlur = async () => {
    if (!jobUrl || !jobUrl.startsWith('http')) return;
    setLoading(true);
    setStatusMessage('Scraping job description automatically...');
    try {
      const res = await fetch(`${API_BASE}/scrape_job`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: jobUrl })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        if (data.title) setJobTitle(data.title);
        if (data.description) setJobDescription(data.description);
        setStatusMessage('Job description scraped successfully!');
      } else {
        throw new Error(data.detail || 'Scraping failed');
      }
    } catch (err) {
      setStatusMessage(`Auto-scrape failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Generate PDF from tailored data
  const generateTailoredPdf = async (data) => {
    setLoading(true);
    setStatusMessage('Compiling tailored PDF resume using backend compiler...');
    setStatusLogs((prev) => [...prev, '🤖 Starting LaTeX PDF compilation...']);
    try {
      const response = await fetch(`${API_BASE}/generate_tailored_resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (response.ok) {
        setStatusMessage('Resume compiled successfully!');
        setStatusLogs((prev) => [...prev, '✅ Tectonic LaTeX compilation completed.']);
      } else {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to compile');
      }
    } catch (err) {
      console.error('Failed to compile tailored PDF', err);
      setStatusMessage(`Compilation failed: ${err.message}`);
      setStatusLogs((prev) => [...prev, `⚠️ Compilation error: ${err.message}`]);
    } finally {
      setLoading(false);
    }
  };



  const openInOverleaf = async () => {
    if (!analysisResult || !analysisResult.latex_code) return;
    setLoading(true);
    setStatusMessage('Preparing project files and opening Overleaf...');
    try {
      const response = await fetch(`${API_BASE}/open_in_overleaf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latex_code: analysisResult.latex_code }),
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to prepare Overleaf link');
      }
      const data = await response.json();
      window.open(data.url, '_blank');
      setStatusMessage('Overleaf workspace opened!');
    } catch (err) {
      setStatusMessage(`Error opening in Overleaf: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Trigger Playwright Autofill Agent
  const handleApply = async () => {
    if (!jobUrl) {
      alert('Please provide a Job Application URL to auto-apply.');
      return;
    }

    setLoading(true);
    setStatusMessage('Spawning automated browser agent to autofill your application...');

    try {
      const response = await fetch(`${API_BASE}/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_url: jobUrl,
          direct_mode: directMode,
        }),
      });

      const result = await response.json();
      if (response.ok) {
        setStatusMessage(
          directMode
            ? 'Application submitted successfully (Direct Mode)!'
            : 'Form autofilled! Review details in the opened browser window and submit when ready.'
        );
      } else {
        setStatusMessage(`Error starting application: ${result.detail}`);
      }
    } catch (err) {
      setStatusMessage(`Network error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="title">
          Resume Tailor Suite
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
          {statusMessage && (
            <span className="status-badge" title={statusMessage}>
              {statusMessage.length > 50 ? `${statusMessage.substring(0, 80)}...` : statusMessage}
            </span>
          )}
          {user && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--accent-green)' }}>👤 {user.email}</span>
              <button className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.75rem' }} onClick={handleLogout}>
                Logout
              </button>
            </div>
          )}
        </div>
      </header>

      {!user ? (
        <div className="login-container" style={{ maxWidth: '450px', margin: '80px auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '35px' }}>
            <h2 style={{ textAlign: 'center', color: 'var(--accent-primary)', marginBottom: '5px' }}>Authentication Required</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', textAlign: 'center', marginBottom: '15px' }}>
              Log in to store your profile and access user-specific tailoring configurations in the cloud.
            </p>

            <button className="btn" style={{ background: '#4285F4', color: '#fff', fontSize: '0.95rem', padding: '12px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px' }} onClick={handleGoogleLogin}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" />
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
              </svg>
              Sign in with Google
            </button>

            <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', margin: '10px 0' }}>— OR —</div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Mock Dev Login</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="text"
                  placeholder="Enter test email (e.g., test@example.com)"
                  value={mockEmail}
                  onChange={(e) => setMockEmail(e.target.value)}
                  style={{ flexGrow: 1 }}
                />
                <button className="btn btn-secondary" onClick={handleMockLogin}>
                  Login
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : configStepActive ? (
        <div className="setup-container" style={{ maxWidth: '600px', margin: '40px auto', display: 'flex', flexDirection: 'column', gap: '25px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '30px' }}>
            <h2 style={{ color: 'var(--accent-primary)', marginBottom: '5px' }}>⚙️ Startup Setup & Keys</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '10px' }}>
              Configure your API settings and upload your master resume profile before you target a job search.
            </p>

            <div>
              <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-main)', fontWeight: '600' }}>
                LLM API Key (Gemini, Groq, or Claude)
              </label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="password"
                  placeholder="Paste your Gemini, Groq (gsk_...), or Claude (sk-ant-...) key..."
                  value={geminiApiKey}
                  onChange={handleApiKeyChange}
                  style={{ fontFamily: 'monospace', flexGrow: 1 }}
                />
                <button className="btn" style={{ padding: '8px 12px', fontSize: '0.8rem' }} onClick={saveApiKeyToCloud}>
                  Save Key
                </button>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                Supports native Gemini, Groq (gsk_), or Claude (sk-ant_) keys. Saved securely.
              </div>
            </div>

            <hr style={{ borderColor: 'var(--border-color)', margin: '10px 0' }} />

            <div>
              <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-main)', fontWeight: '600' }}>
                Upload Master Resume (PDF/DOCX)
              </label>
              <input type="file" accept=".pdf,.docx" onChange={handleResumeUpload} style={{ background: 'var(--bg-primary)' }} />
              {resumeData && (
                <div style={{ fontSize: '0.9rem', color: 'var(--accent-green)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>✓</span> Loaded profile: <strong>{resumeData.name}</strong>
                </div>
              )}
            </div>

            <button 
              className="btn" 
              style={{ marginTop: '15px', padding: '14px', width: '100%', fontSize: '1rem' }} 
              onClick={() => setConfigStepActive(false)}
            >
              Continue to Tailoring Dashboard ➡️
            </button>
          </div>
        </div>
      ) : (
        <div className="dashboard-grid">
          {/* Left Control Panel */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2>Active Profile</h2>
              <button 
                className="btn btn-secondary" 
                style={{ padding: '2px 8px', fontSize: '0.75rem' }} 
                onClick={() => setConfigStepActive(true)}
              >
                ⚙️ Configs
              </button>
            </div>
            
            <div style={{ background: 'var(--panel-bg)', padding: '12px 16px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                Master Resume Profile:
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 'bold', color: resumeData ? 'var(--accent-green)' : 'var(--accent-red)', marginTop: '4px' }}>
                {resumeData ? `👤 ${resumeData.name}` : '❌ No Resume Loaded'}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                API Key: <span style={{ fontFamily: 'monospace' }}>{geminiApiKey ? '••••••••' + geminiApiKey.slice(-4) : 'Not Configured'}</span>
              </div>
            </div>

            <h2>Target Application Details</h2>
            <div>
              <input
                type="text"
                placeholder="Job Application URL (LinkedIn, Indeed, etc.)"
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
                placeholder="Paste Job Description (Optional if URL provided)"
                rows="6"
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
              />
              <button className="btn" style={{ width: '100%' }} onClick={handleAnalyzeJob} disabled={loading}>
                {loading ? 'Analyzing...' : 'Analyze & Tailor'}
              </button>
            </div>
          </div>

          {/* Right Analysis Panel */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <h2>Analysis & Preview</h2>
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            {loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '15px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)', fontWeight: 'bold' }}>
                  <svg style={{ animation: 'spin 1s linear infinite', width: '20px', height: '20px' }} viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" style={{ opacity: 0.25 }} />
                    <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Agent Pipeline Executing...</span>
                </div>
                <div style={{
                  backgroundColor: '#1A202C',
                  padding: '15px',
                  borderRadius: '8px',
                  fontFamily: 'monospace',
                  fontSize: '0.82rem',
                  maxHeight: '280px',
                  overflowY: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  border: '1px solid #2D3748',
                  color: '#E2E8F0',
                  textAlign: 'left'
                }}>
                  {statusLogs.map((log, index) => {
                    let color = '#CBD5E0';
                    if (log.includes('✅')) color = '#48BB78';
                    if (log.includes('⚠️')) color = '#ECC94B';
                    if (log.includes('🤖') || log.includes('👀') || log.includes('📐')) color = '#63B3ED';
                    return (
                      <div key={index} style={{ color, whiteSpace: 'pre-wrap', lineHeight: '1.4' }}>
                        {log}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : !analysisResult ? (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '60px 0' }}>
                Upload your resume and input job details to start matching.
              </div>
            ) : (
              <div>
                {/* ── Hybrid ATS Score Dashboard ── */}
                <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start', flexWrap: 'wrap' }}>

                  {/* Overall ring */}
                  <div className="match-ring-container" style={{ flexShrink: 0 }}>
                    <div
                      className="match-ring"
                      style={{
                        '--percent': analysisResult.match_analysis.overall_score,
                        '--color':
                          analysisResult.match_analysis.overall_score >= 80
                            ? 'var(--accent-green)'
                            : analysisResult.match_analysis.overall_score >= 55
                              ? 'var(--accent-primary)'
                              : '#e57373',
                      }}
                    >
                      <span className="match-ring-text">
                        {analysisResult.match_analysis.overall_score}%
                      </span>
                    </div>
                    <span style={{ marginTop: '8px', fontWeight: '600' }}>Overall Match</span>
                    <span style={{ fontSize: '0.7rem', opacity: 0.5, marginTop: '2px' }}>
                      40% skills · 35% exp · 25% role
                    </span>
                  </div>

                  {/* Score breakdown bars */}
                  <div style={{ flex: 1, minWidth: '220px', display: 'flex', flexDirection: 'column', gap: '12px', justifyContent: 'center' }}>
                    {[
                      { label: 'Skills Match', score: analysisResult.match_analysis.skills_score, method: 'Deterministic', detail: analysisResult.match_analysis.keyword_stats?.required_matched ? `${analysisResult.match_analysis.keyword_stats.required_matched} keywords` : null },
                      { label: 'Experience', score: analysisResult.match_analysis.experience_score, method: 'Deterministic', detail: analysisResult.match_analysis.keyword_stats?.candidate_years ? `${analysisResult.match_analysis.keyword_stats.candidate_years}y / ${analysisResult.match_analysis.keyword_stats.required_years || '?'}y req` : null },
                      { label: 'Role Fit', score: analysisResult.match_analysis.role_fit_score, method: 'AI Semantic', detail: 'Domain · Seniority · Industry' },
                    ].map(({ label, score, method, detail }) => (
                      <div key={label}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                          <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{label}</span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '0.7rem', padding: '1px 6px', borderRadius: '999px', background: method === 'Deterministic' ? 'rgba(100,220,130,0.15)' : 'rgba(120,120,255,0.15)', color: method === 'Deterministic' ? '#64dc82' : '#9090ff' }}>
                              {method}
                            </span>
                            <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>{score}%</span>
                          </div>
                        </div>
                        <div style={{ background: 'rgba(255,255,255,0.08)', borderRadius: '6px', height: '6px', overflow: 'hidden' }}>
                          <div style={{ width: `${score}%`, height: '100%', borderRadius: '6px', background: score >= 80 ? 'var(--accent-green)' : score >= 55 ? 'var(--accent-primary)' : '#e57373', transition: 'width 0.6s ease' }} />
                        </div>
                        {detail && <span style={{ fontSize: '0.7rem', opacity: 0.5, marginTop: '2px', display: 'block' }}>{detail}</span>}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Skills Tags */}
                <div style={{ marginTop: '20px' }}>
                  <h3>Matched Skills</h3>
                  <div className="tag-list">
                    {(analysisResult.match_analysis.matched_skills || []).map((skill, i) => (
                      <span key={i} className="tag tag-match">
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>

                <div style={{ marginTop: '10px' }}>
                  <h3>Missing Required Skills</h3>
                  <div className="tag-list">
                    {(analysisResult.match_analysis.missing_skills || []).map((skill, i) => (
                      <span key={i} className="tag tag-missing">
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>


                {/* Workspace Panels or Tailor Resume Decision Banner */}
                {(!analysisResult.latex_code && !keepOriginalMode) ? (
                  <div style={{
                    marginTop: '30px',
                    padding: '30px',
                    borderRadius: '12px',
                    backgroundColor: 'rgba(99, 179, 237, 0.05)',
                    border: '1.5px dashed var(--accent-primary)',
                    textAlign: 'center',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '15px'
                  }}>
                    <h3 style={{ margin: 0, color: 'var(--accent-primary)' }}>🤖 ATS Score & Suggestions Ready!</h3>
                    <p style={{ maxWidth: '600px', margin: 0, fontSize: '0.9rem', color: 'var(--text-muted)', lineHeight: '1.5' }}>
                      The AI agent has computed the ATS compatibility scores, analyzed keyword alignments, and generated feedback.
                      Would you like to proceed and tailor your LaTeX resume and generate a customized cover letter for this role?
                    </p>
                    <div style={{ display: 'flex', gap: '15px', marginTop: '5px' }}>
                      <button
                        className="btn"
                        style={{ padding: '10px 24px', fontWeight: 'bold', background: 'var(--accent-primary)', color: '#fff', transition: 'all 0.2s ease', cursor: 'pointer' }}
                        onClick={handleGenerateTailoredResume}
                      >
                        🚀 Yes, Tailor My Resume & Cover Letter
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '10px 24px', transition: 'all 0.2s ease', cursor: 'pointer' }}
                        onClick={() => {
                          setKeepOriginalMode(true);
                          setStatusMessage('Keeping original resume. You can compile the PDF manually.');
                        }}
                      >
                        Keep Original Resume
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="workspace">
                    <div className="workspace-panel">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <div className="mode-toggle" style={{ margin: 0, padding: '2px' }}>
                          <button
                            className={`mode-btn ${activeTab === 'preview' ? 'active' : ''}`}
                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                            onClick={() => setActiveTab('preview')}
                          >
                            Preview
                          </button>
                          <button
                            className={`mode-btn ${activeTab === 'latex' ? 'active' : ''}`}
                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                            onClick={() => setActiveTab('latex')}
                          >
                            LaTeX Source
                          </button>
                        </div>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button className="btn" style={{ padding: '6px 12px', fontSize: '0.8rem', background: 'var(--accent-primary)', color: '#fff' }} onClick={openInOverleaf} disabled={loading}>
                            Open in Overleaf
                          </button>
                        </div>
                      </div>

                      {activeTab === 'preview' ? (
                        <div className="panel-content">
                          <h4 style={{ color: 'var(--accent-primary)' }}>{(tailoredResumeData || {}).name || ''}</h4>
                          <p style={{ fontStyle: 'italic', marginBottom: '10px' }}>
                            {(tailoredResumeData || {}).summary || ''}
                          </p>
                          <strong>Skills: </strong>
                          <p style={{ marginBottom: '10px' }}>{((tailoredResumeData || {}).skills || []).join(', ')}</p>
                          <strong>Experience:</strong>
                          {((tailoredResumeData || {}).experience || []).map((exp, idx) => (
                            <div key={idx} style={{ marginBottom: '10px' }}>
                              <div>
                                <strong>{exp.role}</strong> at {exp.company}
                              </div>
                              <ul style={{ paddingLeft: '15px' }}>
                                {(exp.description || []).map((bullet, bidx) => (
                                  <li key={bidx}>{bullet}</li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="panel-content" style={{ position: 'relative', background: '#090D1A' }}>
                          <button
                            className="btn"
                            style={{ position: 'absolute', right: '15px', top: '15px', padding: '4px 10px', fontSize: '0.75rem', zIndex: 10 }}
                            onClick={() => {
                              navigator.clipboard.writeText(analysisResult.latex_code);
                              setStatusMessage('Copied LaTeX source code to clipboard!');
                            }}
                          >
                            Copy Code
                          </button>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.8rem', color: '#CBD5E0', textAlign: 'left' }}>
                            {analysisResult.latex_code}
                          </pre>
                        </div>
                      )}
                    </div>

                    <div className="workspace-panel">
                      <h3>Generated Cover Letter</h3>
                      <div className="panel-content" style={{ whiteSpace: 'pre-wrap' }}>
                        {analysisResult.cover_letter}
                      </div>
                    </div>
                  </div>
                )}
                {/* Execution logs terminal rendering (always visible at bottom of dashboard after analysis) */}
                {statusLogs.length > 0 && (
                  <div style={{
                    marginTop: '25px',
                    padding: '16px 20px',
                    backgroundColor: 'rgba(0, 0, 0, 0.25)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '12px',
                    fontFamily: 'monospace',
                    fontSize: '0.82rem',
                    color: '#E2E8F0',
                    maxHeight: '180px',
                    overflowY: 'auto',
                    textAlign: 'left',
                    boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.4)'
                  }}>
                    <div style={{ color: 'var(--accent-primary)', fontWeight: 'bold', marginBottom: '8px', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' }}>
                      📋 Pipeline Execution Logs
                    </div>
                    {statusLogs.map((log, index) => (
                      <div key={index} style={{ marginBottom: '4px', lineHeight: '1.45', opacity: log.includes('⚠️') ? 0.95 : 0.75 }}>
                        {log}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
