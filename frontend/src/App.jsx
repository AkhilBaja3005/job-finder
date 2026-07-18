import React, { useState, useEffect, useRef, useCallback, useMemo, Suspense, lazy } from 'react';

// Optimization #3: Lazy-load dashboard modes for code splitting
const TailorMode = lazy(() => import('./components/TailorMode'));
const DiscoverMode = lazy(() => import('./components/DiscoverMode'));
const HistoryMode = lazy(() => import('./components/HistoryMode'));
const SkeletonLoader = lazy(() => import('./components/SkeletonLoader').then(m => ({ default: m.SkeletonLoader })));
const OutreachModal = lazy(() => import('./components/OutreachModal'));

const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://127.0.0.1:8000'
  : window.location.origin;

// Reads a newline-delimited JSON (NDJSON) streaming response body and yields
// each parsed event object as it arrives. Shared by every SSE/NDJSON endpoint
// consumer (analyze_job, search_matching_jobs, apply status, etc.) so the
// buffer/split/parse boilerplate isn't duplicated per call site. Malformed or
// incomplete lines (a line split across two chunks) are silently skipped,
// matching the previous per-handler behavior of ignoring JSON.parse errors.
async function* streamNdjson(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          yield JSON.parse(line);
        } catch (e) {
          // Ignore incomplete/malformed lines
        }
      }
    }
  } finally {
    // If the consumer stops iterating early (e.g. `return` inside a
    // `for await` loop), the JS runtime calls this generator's .return(),
    // running this block — release the underlying stream lock so the
    // connection can be cleanly torn down instead of left dangling.
    reader.cancel().catch(() => {});
  }
}

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
  const [company, setCompany] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [tailoredResumeData, setTailoredResumeData] = useState(null);
  const [directMode, setDirectMode] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [statusLogs, setStatusLogs] = useState([]); // each entry: { message, ts }
  const [activeTab, setActiveTab] = useState('preview');
  const [keepOriginalMode, setKeepOriginalMode] = useState(false);
  const [rejectionWarning, setRejectionWarning] = useState(null);
  const [forceTailorEnabled, setForceTailorEnabled] = useState(false);
  const [coverLetterCopied, setCoverLetterCopied] = useState(false);
  const [toast, setToast] = useState(null); // { message, type: 'success'|'error'|'info' }
  const [geminiApiKey, setGeminiApiKey] = useState(localStorage.getItem('gemini_api_key') || '');

  const [discoveredJobs, setDiscoveredJobs] = useState([]);
  const [discovering, setDiscovering] = useState(false);
  const [searchLocation, setSearchLocation] = useState('Remote');
  const [searchKeywords, setSearchKeywords] = useState('');
  const [searchTimeframe, setSearchTimeframe] = useState('48h'); // '24h' | '48h' | '1w' | '1m'
  const [isDiscoveryView, setIsDiscoveryView] = useState(false);
  const [dashboardMode, setDashboardMode] = useState('tailor'); // 'tailor' | 'discover' | 'history'
  const [searchSortMode, setSearchSortMode] = useState('overall'); // 'overall' | 'role_fit' | 'time'
  const [searchPage, setSearchPage] = useState(1);

  const [applicationHistory, setApplicationHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [user, setUser] = useState(null);
  const [authToken, setAuthToken] = useState(localStorage.getItem('auth_token') || '');
  const [mockEmail, setMockEmail] = useState('');
  const [configStepActive, setConfigStepActive] = useState(true);

  // Optimization #1: Progressive Disclosure - compact mode for mobile
  const [compactMode, setCompactMode] = useState(window.innerWidth < 640);
  const [showKeyboardHelp, setShowKeyboardHelp] = useState(false);

  // Optimization #5: Loading skeleton state
  const [showSkeleton, setShowSkeleton] = useState(false);

  // Outreach feature state
  const [outreachModalOpen, setOutreachModalOpen] = useState(false);
  const [outreachData, setOutreachData] = useState(null);
  const [outreachRecruiterInfo, setOutreachRecruiterInfo] = useState(null);
  const [outreachLoading, setOutreachLoading] = useState(false);

  // Store scraped job description in a ref so it's never lost
  const scrapedJobDescriptionRef = useRef('');
  const analysisPanelRef = useRef(null);
  const [outreachAnchorTop, setOutreachAnchorTop] = useState(0);

  // Returns the current time in HH:MM:SS using the browser's local timezone
  const nowTs = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  // Console auto-scroll ref — pauses when user scrolls up
  const consoleBodyRef = useRef(null);
  const consoleUserScrolled = useRef(false);
  const scrollConsoleToBottom = useCallback(() => {
    if (consoleBodyRef.current && !consoleUserScrolled.current) {
      consoleBodyRef.current.scrollTop = consoleBodyRef.current.scrollHeight;
    }
  }, []);


  // Expanded job cards set
  const [expandedCards, setExpandedCards] = useState(new Set());
  const toggleCard = (idx) => setExpandedCards(prev => {
    const next = new Set(prev);
    if (next.has(idx)) next.delete(idx); else next.add(idx);
    return next;
  });

  // Guest UUID token — persisted in localStorage so guest sessions survive refresh
  const [guestToken] = useState(() => {
    let t = localStorage.getItem('guest_token');
    if (!t) {
      t = 'guest-' + crypto.randomUUID();
      localStorage.setItem('guest_token', t);
    }
    return t;
  });

  // Returns the effective Authorization header value: real token > guest UUID
  const getAuthHeader = () => authToken || guestToken;


  // Show a transient toast for 3 seconds
  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Reset all job-related state so the user can target a new job
  const handleNewJob = () => {
    setJobUrl('');
    setJobTitle('');
    setJobDescription('');
    setCompany('');
    setAnalysisResult(null);
    setTailoredResumeData(null);
    setRejectionWarning(null);
    setKeepOriginalMode(false);
    setStatusLogs([]);
    setStatusMessage('');
    setActiveTab('preview');
    setCoverLetterCopied(false);
    scrapedJobDescriptionRef.current = '';
  };

  // Editing the job URL means the user is targeting a different posting —
  // any analysis/tailoring/JD tied to the previous URL is now stale and must
  // not linger on screen until the new URL is (re-)analyzed.
  const handleJobUrlChange = (newUrl) => {
    if (newUrl.trim() !== jobUrl.trim() && (analysisResult || tailoredResumeData || jobDescription)) {
      setJobTitle('');
      setJobDescription('');
      setCompany('');
      setAnalysisResult(null);
      setTailoredResumeData(null);
      setRejectionWarning(null);
      setKeepOriginalMode(false);
      setStatusLogs([]);
      setStatusMessage('');
      setActiveTab('preview');
      setCoverLetterCopied(false);
      scrapedJobDescriptionRef.current = '';
    }
    setJobUrl(newUrl);
  };

  // Cmd+Enter / Ctrl+Enter shortcut to trigger analysis
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !loading && resumeData) {
        handleAnalyzeJob();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, resumeData, jobUrl, jobTitle, jobDescription]);

  // Optimization #1: Handle window resize for compact mode
  useEffect(() => {
    const handleResize = () => {
      setCompactMode(window.innerWidth < 640);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Optimization #2: Keyboard shortcuts - handle ? key for help modal
  useEffect(() => {
    const handler = (e) => {
      if (e.key === '?' && !showKeyboardHelp) {
        setShowKeyboardHelp(true);
      }
      if (e.key === 'Escape' && showKeyboardHelp) {
        setShowKeyboardHelp(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showKeyboardHelp]);

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

  const handleClearCache = async () => {
    if (!window.confirm("Are you sure you want to clear all in-memory caches, active session state, and output PDF/TEX files?")) {
      return;
    }
    setLoading(true);
    setStatusMessage('Clearing application caches and temp files...');
    try {
      const headers = {};
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }
      const res = await fetch(`${API_BASE}/clear_cache`, {
        method: 'POST',
        headers
      });
      if (res.ok) {
        setResumeData(null);
        setAnalysisResult(null);
        setTailoredResumeData(null);
        setRejectionWarning(null);
        setJobUrl('');
        setJobTitle('');
        setJobDescription('');
        setCompany('');
        setStatusLogs([]);
        setStatusMessage('Caches cleared successfully!');
        showToast('🧹 All caches and files deleted!', 'success');
      } else {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to clear cache');
      }
    } catch (err) {
      setStatusMessage(`Clear cache failed: ${err.message}`);
      showToast(`❌ ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

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
    setStatusMessage('Uploading and parsing master resume...');
    const formData = new FormData();
    formData.append('file', file);

    try {
      const headers = {};
      headers['Authorization'] = `Bearer ${getAuthHeader()}`;

      const response = await fetch(`${API_BASE}/upload_resume`, {
        method: 'POST',
        headers: headers,
        body: formData,
      });
      const result = await response.json();
      if (response.ok) {
        setResumeData(result.data);
        setStatusMessage('✅ Master resume uploaded and parsed successfully!');
      } else {
        setStatusMessage(`❌ Error parsing resume: ${result.detail}`);
      }
    } catch (err) {
      setStatusMessage(`❌ Error connecting to backend: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Step 1: Initial Job Analysis & Scoring (Fast ATS evaluation)
  const handleAnalyzeJob = async (urlOverride = null, titleOverride = null) => {
    console.log('[handleAnalyzeJob] START - jobDescription state:', jobDescription?.substring(0, 100) + '...');
    console.log('[handleAnalyzeJob] START - scrapedJobDescriptionRef:', scrapedJobDescriptionRef.current?.substring(0, 100) + '...');

    if (!resumeData) {
      alert('Please upload a resume first.');
      return;
    }

    // ─── SAFE STRING SANITIZATION ──────────────────────────────────────────
    // Force inputs to be primitive strings. If an object/event slipped in,
    // extracting text fields prevents circular structure crashes.
    const extractString = (val) => {
      if (val === null || val === undefined) return null;
      if (typeof val === 'string') return val;
      if (val.target && typeof val.target.value === 'string') return val.target.value; // Catch accidental event objects
      if (typeof val.toString === 'function') return val.toString();
      return String(val);
    };

    const targetUrl = extractString(urlOverride || jobUrl);
    const targetTitle = extractString(titleOverride || jobTitle);

    // Clear out stale job description if we are switching to a new URL override
    let activeDescription = extractString(jobDescription);
    console.log('[handleAnalyzeJob] activeDescription extracted:', activeDescription?.substring(0, 100) + '...');

    // Use scraped JD from ref if current state is empty
    if (!activeDescription && scrapedJobDescriptionRef.current) {
      console.log('[handleAnalyzeJob] Using scraped JD from ref');
      activeDescription = scrapedJobDescriptionRef.current;
    }
    if (urlOverride) {
      activeDescription = null;
      setJobDescription('');
    }

    console.log('[handleAnalyzeJob] About to send to backend - activeDescription:', activeDescription?.substring(0, 100) + '...');

    setLoading(true);
    setAnalysisResult(null);
    setTailoredResumeData(null);
    setKeepOriginalMode(false);
    setStatusLogs([]);
    setCompany('');
    setStatusMessage('Connecting to AI agent pipeline...');
    consoleUserScrolled.current = false;

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) {
        headers['X-Gemini-API-Key'] = extractString(geminiApiKey);
      }
      headers['Authorization'] = `Bearer ${getAuthHeader()}`;

      // ─── DEFENSIVE SERIALIZATION ──────────────────────────────────────────
      let requestBody;
      try {
        const payload = {
          job_url: targetUrl || null,
          job_title: targetTitle || 'Target Role',
          job_description: activeDescription || null,
          skip_tailoring: true,
        };
        console.log('[handleAnalyzeJob] Sending payload:', {
          job_url: payload.job_url,
          job_title: payload.job_title,
          job_description: payload.job_description?.substring(0, 100) + '...',
          skip_tailoring: payload.skip_tailoring
        });
        requestBody = JSON.stringify(payload);
      } catch (jsonError) {
        console.error("CRITICAL: The payload items are circular!", { targetUrl, targetTitle, activeDescription });
        throw new Error(`Payload serialization failed: ${jsonError.message}. Check your state bindings.`);
      }

      const response = await fetch(`${API_BASE}/analyze_job`, {
        method: 'POST',
        headers: headers,
        body: requestBody,
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || 'Failed to analyze job.');
      }

      for await (const event of streamNdjson(response)) {
        console.log('[handleAnalyzeJob] Event received:', event);
        if (event.type === 'log') {
          setStatusMessage(event.message);
          setStatusLogs((prev) => [...prev, { message: event.message, ts: nowTs() }]);
          setTimeout(scrollConsoleToBottom, 30);
        } else if (event.type === 'llm_warn') {
          const msg = event.message || `⚠️ Rate limit hit on ${event.model}. Retrying in ${event.wait_s}s...`;
          setStatusMessage(msg);
          setStatusLogs((prev) => [...prev, { message: msg, ts: nowTs() }]);
          setTimeout(scrollConsoleToBottom, 30);
        } else if (event.type === 'scraped_data') {
          if (event.job_description) {
            setJobDescription(event.job_description);
            scrapedJobDescriptionRef.current = event.job_description;
            console.log('[handleAnalyzeJob] Scraped JD stored in ref:', event.job_description.substring(0, 100) + '...');
          }
          if (event.job_title) setJobTitle(event.job_title);
        } else if (event.type === 'error') {
          console.error('[handleAnalyzeJob] Error event from backend:', event);
          throw new Error(event.message);
        } else if (event.type === 'result') {
          try {
            const result = event;
            console.log('[handleAnalyzeJob] Result received:', result);
            console.log('[handleAnalyzeJob] result.analysis:', result.analysis);
            console.log('[handleAnalyzeJob] result.analysis type:', typeof result.analysis);
            console.log('[handleAnalyzeJob] result.job_description:', result.job_description?.substring(0, 100) + '...');

            setAnalysisResult(result.analysis);
            if (result.job_title) setJobTitle(result.job_title);
            if (result.company) setCompany(result.company);
            // Always use the job_description from result, or fall back to ref
            const finalJD = result.job_description || scrapedJobDescriptionRef.current || '';
            console.log('[handleAnalyzeJob] Setting JD to:', finalJD.substring(0, 100) + '...');
            setJobDescription(finalJD);
            scrapedJobDescriptionRef.current = finalJD;

            // ─── SAFE RESUME CLONING ──────────────────────────────────────
            console.log('[handleAnalyzeJob] resumeData:', resumeData);
            const baseResume = resumeData ? JSON.parse(JSON.stringify(resumeData)) : {};
            console.log('[handleAnalyzeJob] baseResume:', baseResume);

            const updates = result.analysis?.suggested_resume_updates || {};
            console.log('[handleAnalyzeJob] updates:', updates);

            // Ensure arrays are actually arrays
            const baseExperience = Array.isArray(baseResume.experience) ? baseResume.experience : [];
            const baseProjects = Array.isArray(baseResume.projects) ? baseResume.projects : [];
            console.log('[handleAnalyzeJob] baseExperience:', baseExperience);
            console.log('[handleAnalyzeJob] baseProjects:', baseProjects);

            console.log('[handleAnalyzeJob] Starting experience mapping...');
            const tailored = {
              ...baseResume,
              summary: updates.summary || baseResume.summary || '',
              skills: Array.isArray(updates.skills) ? updates.skills : (Array.isArray(baseResume.skills) ? baseResume.skills : []),
              experience: baseExperience.map((job, idx) => {
                console.log(`[handleAnalyzeJob] Processing experience item ${idx}:`, job);
                if (!job || typeof job !== 'object') {
                  console.warn('[handleAnalyzeJob] Invalid job item at index', idx, job);
                  return job || {};
                }
                const tailoredExperience = updates.experience?.[idx];

                let finalDescription = job.description || [];
                if (Array.isArray(tailoredExperience)) {
                  finalDescription = tailoredExperience;
                } else if (tailoredExperience && tailoredExperience.description) {
                  finalDescription = tailoredExperience.description;
                }

                return {
                  ...job,
                  description: finalDescription,
                };
              }),
              projects: baseProjects.map((proj, idx) => {
                console.log(`[handleAnalyzeJob] Processing project item ${idx}:`, proj);
                if (!proj || typeof proj !== 'object') {
                  console.warn('[handleAnalyzeJob] Invalid project item at index', idx, proj);
                  return proj || {};
                }
                const tailoredProject = updates.projects?.[idx];

                let finalDescription = proj.description || [];
                if (Array.isArray(tailoredProject)) {
                  finalDescription = tailoredProject;
                } else if (tailoredProject && tailoredProject.description) {
                  finalDescription = tailoredProject.description;
                }

                return {
                  ...proj,
                  description: finalDescription,
                };
              }),
            };

            console.log('[handleAnalyzeJob] tailored:', tailored);
            setTailoredResumeData(tailored);
            setStatusMessage('ATS Scoring complete! Awaiting your instruction to tailor the resume.');
          } catch (err) {
            console.error('[handleAnalyzeJob] Error processing result:', err);
            console.error('[handleAnalyzeJob] Error stack:', err.stack);
            throw err;
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
  const handleGenerateTailoredResume = async (overrideForce = false, urlOverride = null, titleOverride = null) => {
    if (!resumeData) {
      alert('Please upload a resume first.');
      return;
    }

    const targetUrl = urlOverride || jobUrl;
    const targetTitle = titleOverride || jobTitle;

    // Clear out stale job description if we are switching to a new URL override
    let activeDescription = jobDescription;
    console.log('[handleGenerateTailoredResume] activeDescription:', activeDescription);
    console.log('[handleGenerateTailoredResume] jobDescription state:', jobDescription);
    if (urlOverride) {
      activeDescription = null;
      setJobDescription('');
    }

    setLoading(true);
    setRejectionWarning(null);
    setStatusMessage('Tailoring resume LaTeX and running recruiter loop...');
    setStatusLogs((prev) => [...prev, { message: '🤖 Requesting LaTeX tailoring and page-metric checks...', ts: nowTs() }]);
    consoleUserScrolled.current = false;

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) {
        headers['X-Gemini-API-Key'] = geminiApiKey;
      }
      headers['Authorization'] = `Bearer ${getAuthHeader()}`;

      console.log('[handleGenerateTailoredResume] Sending payload:', {
        job_url: targetUrl,
        job_title: targetTitle,
        job_description: activeDescription ? activeDescription.substring(0, 100) + '...' : null,
        skip_tailoring: false,
        force_tailoring: overrideForce
      });

      const response = await fetch(`${API_BASE}/analyze_job`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          job_url: targetUrl || null,
          job_title: targetTitle || 'Target Role',
          job_description: activeDescription || null,
          skip_tailoring: false, // Run full LaTeX tailoring + page checks + reviewer checks
          force_tailoring: overrideForce
        }),
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || 'Failed to tailor resume.');
      }

      for await (const event of streamNdjson(response)) {
        if (event.type === 'log') {
          setStatusMessage(event.message);
          setStatusLogs((prev) => [...prev, { message: event.message, ts: nowTs() }]);
          setTimeout(scrollConsoleToBottom, 30);
        } else if (event.type === 'llm_warn') {
          const msg = event.message || `⚠️ Rate limit hit on ${event.model}. Retrying in ${event.wait_s}s...`;
          setStatusMessage(msg);
          setStatusLogs((prev) => [...prev, { message: msg, ts: nowTs() }]);
          setTimeout(scrollConsoleToBottom, 30);
        } else if (event.type === 'scraped_data') {
          if (event.job_description) setJobDescription(event.job_description);
          if (event.job_title) setJobTitle(event.job_title);
        } else if (event.type === 'rejection_warning') {
          setRejectionWarning(event.message);
          setStatusLogs((prev) => [...prev, { message: `❌ Warning Paused: ${event.message}`, ts: nowTs() }]);
          setStatusMessage('Process paused: Candidate may not be a fit.');
          return;
        } else if (event.type === 'error') {
          throw new Error(event.message);
        } else if (event.type === 'result') {
          const result = event;
          if (result.job_description) setJobDescription(result.job_description);
          if (result.job_title) setJobTitle(result.job_title);
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
            projects: ((resumeData || {}).projects || []).map((proj, idx) => {
              const tailoredProject = updates.projects && updates.projects[idx];
              return {
                ...proj,
                description: Array.isArray(tailoredProject) ? tailoredProject : (tailoredProject && tailoredProject.description) || (proj || {}).description || [],
              };
            }),
          };
          setTailoredResumeData(tailored);
          setStatusMessage('LaTeX tailored resume and metrics prepared successfully!');
        }
      }
    } catch (error) {
      console.error(error);
      setStatusMessage(`Error: ${error.message}`);
      setStatusLogs((prev) => [...prev, { message: `❌ Pipeline Interrupted: ${error.message}`, ts: nowTs() }]);
    } finally {
      setLoading(false);
    }
  };

  const handleFetchHistory = async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch(`${API_BASE}/applications`, {
        headers: { 'Authorization': `Bearer ${getAuthHeader()}` }
      });
      if (res.ok) {
        const data = await res.json();
        setApplicationHistory(data.applications || []);
      }
    } catch (err) {
      console.error('Failed to load application history', err);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleSearchJobs = async () => {
    if (!resumeData) {
      showToast("⚠️ Please upload a resume first to generate search queries.", "error");
      return;
    }
    setDiscovering(true);
    setIsDiscoveryView(true);
    setDiscoveredJobs([]);
    setStatusMessage(`🔎 Scanning LinkedIn and Indeed for matching jobs posted in the last ${searchTimeframe === '24h' ? '24 hours' : searchTimeframe === '48h' ? '48 hours' : searchTimeframe === '1w' ? '1 week' : '1 month'}...`);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) headers['X-Gemini-API-Key'] = geminiApiKey;
      headers['Authorization'] = `Bearer ${getAuthHeader()}`;

      setStatusLogs([]); // Clear logs before fresh sweep
      const response = await fetch(`${API_BASE}/search_matching_jobs`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          location: searchLocation,
          keywords: searchKeywords || null,
          timeframe: searchTimeframe
        }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Search failed");
      }

      for await (const event of streamNdjson(response)) {
        if (event.type === 'log') {
          setStatusMessage(event.message);
          setStatusLogs((prev) => [...prev, { message: event.message, ts: nowTs() }]);
          setTimeout(scrollConsoleToBottom, 30);
        } else if (event.type === 'result') {
          setDiscoveredJobs(event.jobs || []);
          setStatusMessage(`Found ${event.jobs?.length || 0} matching jobs.`);
          showToast(`Discovered ${event.jobs?.length || 0} matching jobs!`, 'success');
        }
      }
    } catch (err) {
      setStatusMessage(`Discovery failed: ${err.message}`);
      setStatusLogs((prev) => [...prev, { message: `❌ Discovery failed: ${err.message}`, ts: nowTs() }]);
      showToast(`❌ ${err.message}`, 'error');
    } finally {
      setDiscovering(false);
    }
  };

  const sortedAndPaginatedJobs = useMemo(() => {
    // 1. Sort copy of jobs array. Accurate (JD-scored) jobs always sort
    // before estimated (title-only) ones, since an estimated job's score
    // isn't directly comparable to a real ATS-scored one — within each
    // group, apply the user's chosen sort mode.
    const sorted = [...discoveredJobs];
    const estimatedRank = (j) => (j.estimated ? 1 : 0);
    if (searchSortMode === 'overall') {
      sorted.sort((a, b) => estimatedRank(a) - estimatedRank(b) || (b.score || 0) - (a.score || 0));
    } else if (searchSortMode === 'role_fit') {
      sorted.sort((a, b) => estimatedRank(a) - estimatedRank(b) || (b.role_fit_score || 0) - (a.role_fit_score || 0));
    } else if (searchSortMode === 'time') {
      // Sort by age keyword estimation: if age contains "minute" or "hour" it is newer than "day"
      const getAgeValue = (ageStr) => {
        if (!ageStr) return 999999;
        const val = parseInt(ageStr, 10) || 1;
        const lowerAge = ageStr.toLowerCase();
        if (lowerAge.includes('minute')) return val;
        if (lowerAge.includes('hour')) return val * 60;
        if (lowerAge.includes('day')) return val * 1440;
        return 999999;
      };
      sorted.sort((a, b) => estimatedRank(a) - estimatedRank(b) || getAgeValue(a.age) - getAgeValue(b.age));
    }

    // 2. Paginate items (30 items per page)
    const itemsPerPage = 30;
    const totalPages = Math.ceil(sorted.length / itemsPerPage) || 1;
    const currentPage = Math.max(1, Math.min(searchPage, totalPages));
    const paginated = sorted.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

    return { sorted, paginated, totalPages, currentPage };
  }, [discoveredJobs, searchSortMode, searchPage]);

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
    setStatusLogs((prev) => [...prev, { message: '🤖 Starting LaTeX PDF compilation...', ts: nowTs() }]);
    try {
      const response = await fetch(`${API_BASE}/generate_tailored_resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (response.ok) {
        setStatusMessage('Resume compiled successfully!');
        setStatusLogs((prev) => [...prev, { message: '✅ Tectonic LaTeX compilation completed.', ts: nowTs() }]);
      } else {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to compile');
      }
    } catch (err) {
      console.error('Failed to compile tailored PDF', err);
      setStatusMessage(`Compilation failed: ${err.message}`);
      setStatusLogs((prev) => [...prev, { message: `⚠️ Compilation error: ${err.message}`, ts: nowTs() }]);
    } finally {
      setLoading(false);
    }
  };



  const handleDownloadCoverLetter = async () => {
    if (!analysisResult?.cover_letter) return;
    try {
      const response = await fetch(`${API_BASE}/download_cover_letter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cover_letter: analysisResult.cover_letter }),
      });
      if (!response.ok) throw new Error('Failed to prepare cover letter download');
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'cover_letter.txt';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      showToast(`❌ ${err.message}`, 'error');
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
        body: JSON.stringify({
          latex_code: analysisResult.latex_code,
          candidate_name: resumeData?.name || '',
          job_title: jobTitle || '',
          company: company || '',
        }),
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to prepare Overleaf link');
      }
      const data = await response.json();
      window.open(data.url, '_blank');
      setStatusMessage('Overleaf workspace opened!');
      showToast('✅ Overleaf opened in a new tab!', 'success');
    } catch (err) {
      setStatusMessage(`Error opening in Overleaf: ${err.message}`);
      showToast(`❌ ${err.message}`, 'error');
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
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) {
        headers['X-Gemini-API-Key'] = geminiApiKey;
      }
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const response = await fetch(`${API_BASE}/apply`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          job_url: jobUrl,
          direct_mode: directMode,
          job_title: jobTitle || '',
          company: company || '',
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

  // Generate personalized recruiter outreach message
  const handleGenerateOutreach = async () => {
    console.log('[handleGenerateOutreach] Called', {
      analysisResult: !!analysisResult,
      jobDescription: jobDescription?.substring(0, 100) + '...',
      jobTitle,
      company,
      scrapedJDRef: scrapedJobDescriptionRef.current?.substring(0, 100) + '...'
    });

    // Use ref as fallback if state is empty
    const finalJD = jobDescription || scrapedJobDescriptionRef.current;

    if (!analysisResult || !finalJD || !jobTitle) {
      console.log('[handleGenerateOutreach] Missing required fields:', {
        analysisResult: !!analysisResult,
        finalJD: !!finalJD,
        jobTitle: !!jobTitle
      });
      showToast('Please analyze a job first', 'error');
      return;
    }

    console.log('[handleGenerateOutreach] Starting outreach generation');
    setOutreachLoading(true);
    setStatusMessage('Generating personalized outreach message...');

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) {
        headers['X-Gemini-API-Key'] = geminiApiKey;
      }
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const payload = {
        job_url: jobUrl,
        job_description: finalJD,
        job_title: jobTitle,
        company_name: company,
        recruiter_name: null,
        platform: jobUrl.includes('linkedin') ? 'linkedin' : jobUrl.includes('indeed') ? 'indeed' : 'unknown',
      };
      console.log('[handleGenerateOutreach] Sending request to /generate_outreach', {
        job_url: payload.job_url,
        job_description: payload.job_description?.substring(0, 100) + '...',
        job_title: payload.job_title,
        company_name: payload.company_name,
        platform: payload.platform
      });

      const response = await fetch(`${API_BASE}/generate_outreach`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(payload),
      });

      console.log('[handleGenerateOutreach] Response received', { status: response.status });

      const result = await response.json();
      if (response.ok) {
        console.log('[handleGenerateOutreach] Success', result);
        setOutreachRecruiterInfo(result.recruiter_info);
        setOutreachData(result.message);
        if (analysisPanelRef.current) {
          setOutreachAnchorTop(analysisPanelRef.current.getBoundingClientRect().top);
        }
        setOutreachModalOpen(true);
        setStatusMessage('Outreach message generated successfully!');
        showToast('Outreach message ready!', 'success');
      } else {
        console.log('[handleGenerateOutreach] Error response', result);
        setStatusMessage(`Error generating outreach: ${result.detail}`);
        showToast(`Error: ${result.detail}`, 'error');
      }
    } catch (err) {
      console.log('[handleGenerateOutreach] Exception', err);
      setStatusMessage(`Network error: ${err.message}`);
      showToast(`Error: ${err.message}`, 'error');
    } finally {
      setOutreachLoading(false);
    }
  };

  const handleSendOutreachEmail = async (emailData) => {
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const response = await fetch(`${API_BASE}/send_outreach_email`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(emailData),
      });

      const result = await response.json();
      if (response.ok) {
        showToast('Email prepared for sending!', 'success');
        setOutreachModalOpen(false);
      } else {
        showToast(`Error: ${result.detail}`, 'error');
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    }
  };

  return (
    <div className="app-container">
      {/* Optimization #5: Progress bar at top of page */}
      {loading && <div className="progress-bar" />}

      {/* Toast Notification */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: '28px', left: '50%', transform: 'translateX(-50%)',
          zIndex: 9999, padding: '12px 22px', borderRadius: '12px', fontWeight: 600,
          fontSize: '0.88rem', display: 'flex', alignItems: 'center', gap: '10px',
          animation: 'slideDown 0.3s ease both',
          background: toast.type === 'success' ? 'rgba(16,185,129,0.15)' : toast.type === 'error' ? 'rgba(239,68,68,0.15)' : 'rgba(56,189,248,0.15)',
          border: `1px solid ${toast.type === 'success' ? 'rgba(16,185,129,0.4)' : toast.type === 'error' ? 'rgba(239,68,68,0.4)' : 'rgba(56,189,248,0.4)'}`,
          color: toast.type === 'success' ? '#34D399' : toast.type === 'error' ? '#F87171' : '#7DD3FC',
          backdropFilter: 'blur(16px)', boxShadow: '0 8px 32px rgba(0,0,0,0.4)'
        }}>
          {toast.message}
        </div>
      )}

      <header className="app-header">
        <h1 className="title">
          Resume Tailor Suite
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {statusMessage && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '7px',
              padding: '5px 12px', borderRadius: '20px', maxWidth: '340px',
              background: statusMessage.includes('Error') || statusMessage.includes('error') || statusMessage.includes('failed')
                ? 'rgba(239,68,68,0.1)' : statusMessage.includes('✅') || statusMessage.includes('success') || statusMessage.includes('Success')
                  ? 'rgba(16,185,129,0.1)' : 'rgba(56,189,248,0.1)',
              border: `1px solid ${statusMessage.includes('Error') || statusMessage.includes('error') || statusMessage.includes('failed')
                ? 'rgba(239,68,68,0.25)' : statusMessage.includes('✅') || statusMessage.includes('success') || statusMessage.includes('Success')
                  ? 'rgba(16,185,129,0.25)' : 'rgba(56,189,248,0.25)'}`,
            }}>
              <span style={{
                width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0, animation: 'pulseGlow 2s infinite',
                background: statusMessage.includes('Error') || statusMessage.includes('error') || statusMessage.includes('failed')
                  ? '#EF4444' : statusMessage.includes('✅') || statusMessage.includes('success') || statusMessage.includes('Success')
                    ? '#10B981' : '#38BDF8'
              }} />
              <span style={{ fontSize: '0.78rem', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {statusMessage.length > 55 ? `${statusMessage.substring(0, 55)}…` : statusMessage}
              </span>
            </div>
          )}
          {/* Optimization #2: Keyboard help button */}
          <button
            className="btn btn-secondary"
            style={{ padding: '6px 10px', fontSize: '0.9rem', minWidth: '36px', minHeight: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => setShowKeyboardHelp(true)}
            aria-label="Show keyboard shortcuts help"
            title="Press ? for keyboard shortcuts"
          >
            ?
          </button>
          {user && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--accent-green)', fontWeight: 500 }}>{user.email}</span>
              <button className="btn btn-secondary" style={{ padding: '5px 11px', fontSize: '0.76rem' }} onClick={handleLogout}>
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      {!user ? (
        <div className="login-container" style={{ maxWidth: '460px', margin: '70px auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '24px', padding: '38px' }}>
            {/* Brand mark */}
            <div style={{ textAlign: 'center' }}>
              <div style={{ width: '52px', height: '52px', borderRadius: '14px', background: 'var(--accent-gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.5rem', margin: '0 auto 14px', boxShadow: '0 8px 24px rgba(56,189,248,0.3)' }}>📄</div>
              <h2 style={{ textAlign: 'center', fontSize: '1.4rem', marginBottom: '6px' }}>Welcome to Resume Tailor</h2>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.87rem', lineHeight: 1.6 }}>
                Paste a job URL, get your ATS score, and receive a tailored LaTeX resume + cover letter in under 60 seconds.
              </p>
            </div>

            {/* Value props */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {['🎯 Keyword-matched ATS scoring', '✍️ AI-tailored LaTeX resume & cover letter', '🔍 Recruiter truthfulness validation', '📄 One-click Overleaf export'].map(item => (
                <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.84rem', color: 'var(--text-muted)', padding: '7px 12px', background: 'var(--panel-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  {item}
                </div>
              ))}
            </div>

            <button className="btn" style={{ background: '#4285F4', color: '#fff', fontSize: '0.92rem', padding: '13px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px' }} onClick={handleGoogleLogin}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" />
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
              </svg>
              Sign in with Google
            </button>

            {(window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') && (
              <>
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
              </>
            )}
          </div>
        </div>
      ) : configStepActive ? (
        <div className="setup-container" style={{ maxWidth: '580px', margin: '40px auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '24px', padding: '32px' }}>
            <div>
              <h2 style={{ marginBottom: '4px' }}>Setup & Configuration</h2>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.87rem' }}>Configure your AI key and upload your master resume to get started.</p>
            </div>

            {/* API Key section */}
            <div>
              <div className="section-label">LLM API Key</div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="password"
                  placeholder="Gemini (AIza...), Groq (gsk_...), or Claude (sk-ant-...)"
                  value={geminiApiKey}
                  onChange={handleApiKeyChange}
                  style={{ fontFamily: 'var(--font-mono)', flexGrow: 1, marginBottom: 0, fontSize: '0.84rem' }}
                />
                <button className="btn" style={{ padding: '10px 14px', fontSize: '0.82rem', flexShrink: 0 }} onClick={saveApiKeyToCloud}>
                  Save
                </button>
              </div>
              <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                Supports Gemini, Groq, and Anthropic Claude keys. Stored securely in the cloud.
              </div>
            </div>

            {/* Resume upload section */}
            <div>
              <div className="section-label">Master Resume</div>
              <label style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px',
                padding: '28px 20px', borderRadius: '12px', cursor: 'pointer',
                border: resumeData ? '1.5px solid rgba(16,185,129,0.4)' : '1.5px dashed var(--border-color)',
                background: resumeData ? 'rgba(16,185,129,0.04)' : 'var(--panel-bg)',
                transition: 'all 0.25s ease'
              }}>
                <input type="file" accept=".pdf,.docx" onChange={handleResumeUpload} style={{ display: 'none' }} />
                {resumeData ? (
                  <>
                    <div style={{ fontSize: '1.6rem' }}>✅</div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontWeight: 700, color: 'var(--accent-green)', fontSize: '0.92rem' }}>{resumeData.name}</div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '3px' }}>Click to replace</div>
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: '1.6rem' }}>📄</div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>Drop your resume here or click to browse</div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '3px' }}>PDF or DOCX — this becomes your master profile</div>
                    </div>
                  </>
                )}
              </label>
            </div>

            {statusMessage && (
              <div style={{
                fontSize: '0.82rem',
                color: statusMessage.includes('❌') ? 'var(--accent-red)' : statusMessage.includes('✅') ? 'var(--accent-green)' : 'var(--accent-primary)',
                textAlign: 'center',
                padding: '4px',
                fontWeight: 600
              }}>
                {statusMessage}
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
              <button
                className="btn btn-secondary"
                style={{ padding: '14px', flex: 1, fontSize: '0.95rem', borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}
                onClick={handleClearCache}
              >
                🧹 Clear Caches & Data
              </button>
              <button
                className="btn"
                style={{ padding: '14px', flex: 2, fontSize: '0.95rem' }}
                onClick={() => setConfigStepActive(false)}
              >
                Continue to Dashboard →
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="dashboard-grid">
          {/* Left Control Panel */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>

            {/* Profile header row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ marginBottom: 0 }}>Active Profile</h2>
              <button
                className="btn btn-secondary"
                style={{ padding: '5px 12px', fontSize: '0.76rem', gap: '5px' }}
                onClick={() => setConfigStepActive(true)}
                aria-label="Open settings"
              >
                ⚙️ Settings
              </button>
            </div>

            {/* Profile status card */}
            <div className="profile-status">
              <div className="profile-avatar">👤</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: resumeData ? '#fff' : 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {resumeData ? resumeData.name : 'No Resume Loaded'}
                </div>
                <div style={{ fontSize: '0.75rem', color: resumeData ? 'var(--accent-green)' : 'var(--accent-red)', marginTop: '2px' }}>
                  {resumeData ? '✓ Profile ready' : '↑ Upload a resume to get started'}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '3px', fontFamily: 'var(--font-mono)' }}>
                  API Key: {geminiApiKey ? '••••••' + geminiApiKey.slice(-4) : 'Not configured'}
                </div>
              </div>
            </div>

            {/* Mode Switcher */}
            <div style={{ display: 'flex', borderRadius: '8px', background: 'rgba(255,255,255,0.03)', padding: '4px', border: '1px solid rgba(255,255,255,0.05)', marginTop: '4px' }}>
              <button
                className={`mode-btn ${dashboardMode === 'tailor' ? 'active' : ''}`}
                style={{
                  flex: 1,
                  padding: '10px 8px',
                  fontSize: '0.82rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: 'none',
                  background: dashboardMode === 'tailor' ? 'var(--accent-primary)' : 'transparent',
                  color: '#fff',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  minHeight: '40px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                onClick={() => {
                  setDashboardMode('tailor');
                  setIsDiscoveryView(false);
                }}
              >
                🎯 Tailor Resume
              </button>
              <button
                className={`mode-btn ${dashboardMode === 'discover' ? 'active' : ''}`}
                style={{
                  flex: 1,
                  padding: '10px 8px',
                  fontSize: '0.82rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: 'none',
                  background: dashboardMode === 'discover' ? 'var(--accent-primary)' : 'transparent',
                  color: '#fff',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  minHeight: '40px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                onClick={() => {
                  setDashboardMode('discover');
                  setIsDiscoveryView(true);
                }}
              >
                🔍 Discover Jobs
              </button>
              <button
                className={`mode-btn ${dashboardMode === 'history' ? 'active' : ''}`}
                style={{
                  flex: 1,
                  padding: '10px 8px',
                  fontSize: '0.82rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: 'none',
                  background: dashboardMode === 'history' ? 'var(--accent-primary)' : 'transparent',
                  color: '#fff',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  minHeight: '40px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                onClick={() => {
                  setDashboardMode('history');
                  setIsDiscoveryView(false);
                  handleFetchHistory();
                }}
              >
                🕘 History
              </button>
            </div>

            {dashboardMode === 'tailor' && (
              <Suspense fallback={<div style={{ fontSize: '0.88rem', color: 'var(--text-muted)' }}>Loading...</div>}>
                <TailorMode
                  jobUrl={jobUrl}
                  setJobUrl={handleJobUrlChange}
                  jobTitle={jobTitle}
                  setJobTitle={setJobTitle}
                  jobDescription={jobDescription}
                  setJobDescription={setJobDescription}
                  analysisResult={analysisResult}
                  loading={loading}
                  handleUrlBlur={handleUrlBlur}
                  handleAnalyzeJob={handleAnalyzeJob}
                  handleGenerateTailoredResume={handleGenerateTailoredResume}
                  onGenerateOutreach={handleGenerateOutreach}
                />
              </Suspense>
            )}

            {dashboardMode === 'discover' && (
              <Suspense fallback={<div style={{ fontSize: '0.88rem', color: 'var(--text-muted)' }}>Loading...</div>}>
                <DiscoverMode
                  searchKeywords={searchKeywords}
                  setSearchKeywords={setSearchKeywords}
                  searchLocation={searchLocation}
                  setSearchLocation={setSearchLocation}
                  searchTimeframe={searchTimeframe}
                  setSearchTimeframe={setSearchTimeframe}
                  discovering={discovering}
                  loading={loading}
                  handleSearchJobs={handleSearchJobs}
                />
              </Suspense>
            )}
            {dashboardMode === 'history' && (
              <Suspense fallback={<div style={{ fontSize: '0.88rem', color: 'var(--text-muted)' }}>Loading...</div>}>
                <HistoryMode
                  historyLoading={historyLoading}
                  handleFetchHistory={handleFetchHistory}
                />
              </Suspense>
            )}
          </div>

          {/* Right Analysis Panel */}
          <div ref={analysisPanelRef} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ marginBottom: 0 }}>
                {dashboardMode === 'history'
                  ? 'Application History'
                  : isDiscoveryView
                  ? `Job Discoveries (${searchTimeframe === '24h' ? 'Last 24h' : searchTimeframe === '48h' ? 'Last 48h' : searchTimeframe === '1w' ? 'Last 1 Week' : 'Last 1 Month'})`
                  : 'Analysis & Preview'}
              </h2>
              {dashboardMode !== 'history' && (analysisResult || isDiscoveryView) && (
                <button
                  className="btn btn-secondary"
                  style={{ padding: '5px 12px', fontSize: '0.76rem', gap: '6px' }}
                  onClick={() => {
                    if (isDiscoveryView) {
                      setIsDiscoveryView(false);
                    } else {
                      handleNewJob();
                    }
                  }}
                  aria-label={isDiscoveryView ? 'Back to active job' : 'Start analyzing a new job'}
                >
                  {isDiscoveryView ? '← Back to Active' : '+ New Job'}
                </button>
              )}
            </div>

            {/* Personalized Outreach Modal - Moved to top */}
            {outreachModalOpen && (
              <Suspense fallback={null}>
                <OutreachModal
                  isOpen={outreachModalOpen}
                  onClose={() => setOutreachModalOpen(false)}
                  recruiterInfo={outreachRecruiterInfo}
                  messageData={outreachData}
                  jobTitle={jobTitle}
                  company={company}
                  onSendEmail={handleSendOutreachEmail}
                  onCopyToClipboard={() => {}}
                  anchorTop={outreachAnchorTop}
                />
              </Suspense>
            )}

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            {dashboardMode === 'history' ? (
              historyLoading ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                  <svg style={{ animation: 'spin 1s linear infinite', width: '18px', height: '18px', flexShrink: 0 }} viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" style={{ opacity: 0.25 }} />
                    <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Loading history…</span>
                </div>
              ) : applicationHistory.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                  <div style={{ fontSize: '1.8rem', marginBottom: '8px' }}>🕘</div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 600 }}>No history yet</div>
                  <div style={{ fontSize: '0.78rem', marginTop: '4px' }}>Tailor a resume or apply to a job to see it recorded here.</div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '560px', overflowY: 'auto', paddingRight: '4px' }}>
                  {applicationHistory.map((entry, idx) => {
                    const statusColor = entry.status === 'applied' ? '#10B981' : entry.status === 'autofilled' ? '#38BDF8' : '#7dd3fc';
                    const statusLabel = entry.status === 'applied' ? 'Applied' : entry.status === 'autofilled' ? 'Autofilled' : 'Tailored';
                    const date = entry.timestamp ? new Date(entry.timestamp * 1000).toLocaleString() : '';
                    return (
                      <div key={idx} className="card" style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontWeight: 700, fontSize: '0.92rem', color: '#fff' }}>{entry.job_title || 'Untitled Role'}</div>
                            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>{entry.company || 'Unknown Company'}</div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '4px' }}>{date}</div>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px', flexShrink: 0 }}>
                            <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '999px', background: `${statusColor}22`, color: statusColor, fontWeight: 700 }}>
                              {statusLabel}
                            </span>
                            {typeof entry.score === 'number' && (
                              <span style={{ fontSize: '0.76rem', fontWeight: 700, color: '#fff' }}>{entry.score}% match</span>
                            )}
                            {entry.job_url && (
                              <a href={entry.job_url} target="_blank" rel="noreferrer" style={{ fontSize: '0.72rem', color: 'var(--accent-primary)' }}>View Post →</a>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )
            ) : isDiscoveryView && discovering ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                  <svg style={{ animation: 'spin 1s linear infinite', width: '18px', height: '18px', flexShrink: 0 }} viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" style={{ opacity: 0.25 }} />
                    <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Searching Platform Feeds…</span>
                </div>
                <div className="log-terminal">
                  <div className="log-terminal-header">
                    <div className="log-terminal-dots">
                      <div className="log-terminal-dot" style={{ background: '#FF5F57' }} />
                      <div className="log-terminal-dot" style={{ background: '#FFBD2E' }} />
                      <div className="log-terminal-dot" style={{ background: '#28CA41' }} />
                    </div>
                    📋 SEARCH PIPELINE LOGS
                  </div>
                  <div
                    className="log-terminal-body"
                    ref={consoleBodyRef}
                    onScroll={(e) => {
                      const el = e.currentTarget;
                      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                      consoleUserScrolled.current = !atBottom;
                    }}
                    style={{ maxHeight: '200px' }}
                  >
                    {statusLogs.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', padding: '12px', fontStyle: 'italic' }}>
                        Initializing...
                      </div>
                    ) : (
                      statusLogs.map((entry, index) => {
                        const msg = typeof entry === 'string' ? entry : entry.message;
                        const ts = typeof entry === 'object' ? entry.ts : '';
                        let cls = 'log-entry-msg log-default';
                        if (msg.includes('🏁') || msg.includes('✅')) cls = 'log-entry-msg log-ok';
                        else if (msg.includes('🔎') || msg.includes('🌐') || msg.includes('🤖')) cls = 'log-entry-msg log-ai';
                        else if (msg.includes('❌')) cls = 'log-entry-msg log-warn';
                        return (
                          <div key={index} className="log-entry">
                            <span className="log-entry-ts">{ts}</span>
                            <span className={cls}>{msg}</span>
                          </div>
                        );
                      })
                    )}
                    <span className="log-cursor" />
                  </div>
                </div>
              </div>
            ) : isDiscoveryView ? (
              (() => {
                const { sorted, paginated, totalPages, currentPage } = sortedAndPaginatedJobs;
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                    {/* Filter & Sorting Controls */}
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      paddingBottom: '12px',
                      borderBottom: '1px solid rgba(255,255,255,0.06)',
                      gap: '12px',
                      flexWrap: 'wrap'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                        {/* Two-row text container on the left */}
                        <div style={{
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          lineHeight: 1.15,
                          fontSize: '0.74rem',
                          color: 'var(--text-muted)',
                          fontWeight: 600,
                          letterSpacing: '0.03em',
                          textTransform: 'uppercase'
                        }}>
                          <div>Sort:</div>
                          <div>by</div>
                        </div>

                        {/* Select box on the right */}
                        <select
                          value={searchSortMode}
                          onChange={(e) => {
                            setSearchSortMode(e.target.value);
                            setSearchPage(1); // Reset to page 1 on sort change
                          }}
                          style={{
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.12)',
                            color: '#fff',
                            fontSize: '0.74rem',
                            padding: '5px 10px',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            outline: 'none',
                            minWidth: '160px',
                            transition: 'all 0.2s ease',
                            boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                          }}
                        >
                          <option value="overall">Overall Match %</option>
                          <option value="role_fit">Role Fit % (Semantic)</option>
                          <option value="time">Time/Age (Newest)</option>
                        </select>
                      </div>
                      <span style={{ fontSize: '0.74rem', color: 'var(--accent-green)' }}>
                        Scanned: <strong>{sorted.length} matches</strong>
                      </span>
                    </div>

                    {sorted.length === 0 ? (
                      <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                        <div style={{ fontSize: '1.8rem', marginBottom: '8px' }}>🔍</div>
                        <div style={{ fontSize: '0.88rem', fontWeight: 600 }}>No matching listings found</div>
                        <div style={{ fontSize: '0.78rem', marginTop: '4px' }}>Enter search keywords or location and scan matches.</div>
                      </div>
                    ) : (
                      <>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '500px', overflowY: 'auto', paddingRight: '4px' }}>
                          {paginated.map((job, idx) => {
                            const isExpanded = expandedCards.has(idx);
                            const score = job.score || 0;
                            const scoreColor = score >= 80 ? '#10B981' : score >= 60 ? '#38BDF8' : '#E57373';
                            // Mini SVG arc for score
                            const r = 18, circ = 2 * Math.PI * r;
                            const arc = (score / 100) * circ;
                            return (
                              <div key={idx} className="card job-card" style={{ padding: '14px 16px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)', cursor: 'pointer' }}
                                onClick={() => toggleCard(idx)}>
                                {/* Collapsed header row - responsive layout */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: compactMode ? 'wrap' : 'nowrap' }}>
                                  <div style={{ flex: 1, minWidth: 0, order: compactMode ? 2 : 0 }}>
                                    {/* Hide platform/age badges on mobile compact mode */}
                                    {!compactMode && (
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                        <span style={{
                                          fontSize: '0.7rem', padding: '2px 6px', borderRadius: '4px', fontWeight: 700,
                                          background: job.platform === 'LinkedIn' ? 'rgba(10,102,194,0.12)' : 'rgba(255,111,0,0.12)',
                                          color: job.platform === 'LinkedIn' ? '#0a66c2' : '#ff6f00'
                                        }}>{job.platform}</span>
                                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{job.age}</span>
                                        {job.estimated && (
                                          <span
                                            title="Score estimated from job title only (beyond the accurate-scan cap) — not yet based on the full job description."
                                            style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '4px', fontWeight: 700, background: 'rgba(234,179,8,0.12)', color: '#eab308' }}
                                          >EST.</span>
                                        )}
                                      </div>
                                    )}
                                    <div style={{ fontWeight: 700, fontSize: compactMode ? '0.88rem' : '0.95rem', color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{job.title}</div>
                                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>{job.company} • {job.location}</div>
                                    {/* Hide skill tags on mobile compact mode - only show on expand */}
                                    {!compactMode && (
                                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px', marginTop: '8px' }}>
                                        {(job.matched_skills || []).slice(0, 3).map((s, i) => (
                                          <span key={i} style={{ padding: '2px 6px', borderRadius: '4px', background: 'rgba(72,187,120,0.08)', color: '#48bb78', border: '1px solid rgba(72,187,120,0.15)', fontSize: '0.68rem' }}>✓ {s}</span>
                                        ))}
                                        {(job.missing_skills || []).slice(0, 2).map((s, i) => (
                                          <span key={i} style={{ padding: '2px 6px', borderRadius: '4px', background: 'rgba(229,115,115,0.08)', color: '#e57373', border: '1px solid rgba(229,115,115,0.15)', fontSize: '0.68rem' }}>✗ {s}</span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                  {/* Mini score ring - always visible, reorder on mobile */}
                                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0, order: compactMode ? 1 : 0 }}>
                                    <svg width={compactMode ? '40' : '48'} height={compactMode ? '40' : '48'} viewBox="0 0 48 48">
                                      <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="4" />
                                      <circle
                                        cx="24" cy="24" r={r} fill="none"
                                        stroke={scoreColor} strokeWidth="4"
                                        strokeDasharray={`${arc} ${circ - arc}`}
                                        strokeLinecap="round"
                                        transform="rotate(-90 24 24)"
                                        style={{ transition: 'stroke-dasharray 0.6s cubic-bezier(0.16,1,0.3,1)' }}
                                      />
                                      <text x="24" y="28" textAnchor="middle" fill="#fff" fontSize={compactMode ? '9' : '11'} fontWeight="800" fontFamily="Plus Jakarta Sans, sans-serif">{score}%</text>
                                    </svg>
                                    {!compactMode && <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', marginTop: '2px' }}>Overall</span>}
                                  </div>
                                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', flexShrink: 0, order: compactMode ? 3 : 0 }}>{isExpanded ? '▲' : '▼'}</span>
                                </div>

                                {/* Expanded details */}
                                {isExpanded && (
                                  <div style={{ marginTop: '12px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '12px', display: 'flex', flexDirection: 'column', gap: '10px', animation: 'fadeIn 0.2s ease both' }}>
                                    {/* Show skill tags on expand for mobile */}
                                    {compactMode && (
                                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                                        {(job.matched_skills || []).slice(0, 3).map((s, i) => (
                                          <span key={i} style={{ padding: '2px 6px', borderRadius: '4px', background: 'rgba(72,187,120,0.08)', color: '#48bb78', border: '1px solid rgba(72,187,120,0.15)', fontSize: '0.68rem' }}>✓ {s}</span>
                                        ))}
                                        {(job.missing_skills || []).slice(0, 2).map((s, i) => (
                                          <span key={i} style={{ padding: '2px 6px', borderRadius: '4px', background: 'rgba(229,115,115,0.08)', color: '#e57373', border: '1px solid rgba(229,115,115,0.15)', fontSize: '0.68rem' }}>✗ {s}</span>
                                        ))}
                                      </div>
                                    )}
                                    {/* Detailed sub-scores grid */}
                                    <div style={{
                                      display: 'grid', gridTemplateColumns: compactMode ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)', gap: '8px',
                                      background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.03)',
                                      borderRadius: '8px', padding: '10px', fontSize: '0.72rem', textAlign: 'center'
                                    }}>
                                      <div>
                                        <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Skills</div>
                                        <div style={{ fontWeight: 700, color: '#7dd3fc' }}>{job.skills_score || 50}%</div>
                                        <div style={{ fontSize: '0.58rem', opacity: 0.55 }}>
                                          {((job.matched_skills?.length || 0) + (job.missing_skills?.length || 0)) > 0
                                            ? `${job.matched_skills?.length || 0}/${(job.matched_skills?.length || 0) + (job.missing_skills?.length || 0)} key`
                                            : 'no keywords found'}
                                        </div>
                                      </div>
                                      <div>
                                        <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Experience</div>
                                        <div style={{ fontWeight: 700, color: '#7dd3fc' }}>{job.experience_score || 70}%</div>
                                        <div style={{ fontSize: '0.58rem', opacity: 0.55 }}>{job.candidate_years || 3}y / {job.required_years || 4}y req</div>
                                      </div>
                                      {!compactMode && (
                                        <>
                                          <div>
                                            <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Role Fit</div>
                                            <div style={{ fontWeight: 700, color: '#7dd3fc' }}>{job.role_fit_score || 65}%</div>
                                            <div style={{ fontSize: '0.58rem', opacity: 0.55 }}>Semantic</div>
                                          </div>
                                          <div>
                                            <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Overall</div>
                                            <div style={{ fontWeight: 800, color: scoreColor }}>{score}%</div>
                                          </div>
                                        </>
                                      )}
                                    </div>
                                    {job.platform === 'LinkedIn' && !job.estimated && (
                                      job.recruiter_name ? (
                                        <div style={{
                                          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px',
                                          background: 'rgba(56,189,248,0.06)', border: '1px solid rgba(56,189,248,0.15)',
                                          borderRadius: '8px', padding: '8px 12px', fontSize: '0.76rem'
                                        }}>
                                          <span style={{ color: 'var(--text-muted)' }}>
                                            👤 Job poster: <span style={{ color: '#fff', fontWeight: 600 }}>{job.recruiter_name}</span>
                                          </span>
                                          {job.recruiter_profile_url && (
                                            <a
                                              href={job.recruiter_profile_url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              onClick={(e) => e.stopPropagation()}
                                              style={{ color: '#7dd3fc', fontWeight: 600, flexShrink: 0 }}
                                            >
                                              View Profile ↗
                                            </a>
                                          )}
                                        </div>
                                      ) : (
                                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', opacity: 0.7 }}>
                                          👤 Job poster not available for this posting
                                        </div>
                                      )
                                    )}
                                    <div style={{ display: 'flex', gap: '8px', marginTop: '4px', flexDirection: compactMode ? 'column' : 'row' }}>
                                      <button
                                        className="btn btn-secondary"
                                        style={{ padding: '8px 12px', fontSize: '0.76rem', flex: 1 }}
                                        onClick={(e) => { e.stopPropagation(); window.open(job.url, '_blank'); }}
                                        aria-label="View job post on external site"
                                      >
                                        🔗 View Post
                                      </button>
                                      <button
                                        className="btn"
                                        style={{ padding: '8px 12px', fontSize: '0.76rem', flex: 1, fontWeight: 700 }}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setJobUrl(job.url);
                                          setJobTitle(job.title);
                                          setCompany(job.company);
                                          setJobDescription('');
                                          setAnalysisResult(null);
                                          setTailoredResumeData(null);
                                          setStatusLogs([]);
                                          setIsDiscoveryView(false);
                                          setDashboardMode('tailor');
                                          // Trigger fit analysis first to populate JD and show ATS score panel
                                          setTimeout(() => {
                                            handleAnalyzeJob(job.url, job.title);
                                          }, 50);
                                        }}
                                      >
                                        ⚡ Tailor Resume
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>

                        {/* Pagination Controls */}
                        {totalPages > 1 && (
                          <div style={{
                            display: 'flex',
                            justifyContent: 'center',
                            alignItems: 'center',
                            gap: '12px',
                            marginTop: '16px',
                            paddingTop: '12px',
                            borderTop: '1px solid rgba(255,255,255,0.06)'
                          }}>
                            <button
                              className="btn btn-secondary"
                              style={{ padding: '6px 14px', fontSize: '0.74rem' }}
                              onClick={() => setSearchPage((p) => Math.max(1, p - 1))}
                              disabled={currentPage === 1}
                            >
                              ← Prev
                            </button>
                            <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                              Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
                            </span>
                            <button
                              className="btn btn-secondary"
                              style={{ padding: '6px 14px', fontSize: '0.74rem' }}
                              onClick={() => setSearchPage((p) => Math.min(totalPages, p + 1))}
                              disabled={currentPage === totalPages}
                            >
                              Next →
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })()
            ) : rejectionWarning ? (
              <div className="rejection-warning-panel" style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'slideDown 0.4s ease both' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ fontSize: '1.4rem' }}>⚠️</span>
                  <h3 style={{ margin: 0, color: 'var(--accent-amber)', fontSize: '1rem' }}>Candidate Suitability Warning</h3>
                </div>
                <p style={{ maxWidth: '600px', margin: 0, fontSize: '0.87rem', color: 'var(--text-muted)', lineHeight: '1.65' }}>
                  The AI Recruiter flagged potential mismatches after 3 checks. Review the feedback below before proceeding.
                </p>
                <div className="rejection-feedback-box" style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.18)', borderRadius: '8px', padding: '16px', fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.6, maxHeight: '200px', overflowY: 'auto' }}>
                  {rejectionWarning}
                </div>
                <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', margin: 0 }}>
                  Would you still like to proceed and generate the tailored resume anyway?
                </p>
                <div style={{ display: 'flex', gap: '12px', marginTop: '4px' }}>
                  <button
                    className="btn"
                    style={{ padding: '10px 22px', fontWeight: 700, background: 'linear-gradient(135deg,#F59E0B,#D97706)', boxShadow: '0 4px 14px rgba(245,158,11,0.3)' }}
                    onClick={() => handleGenerateTailoredResume(true)}
                  >
                    🚀 Yes, Generate Anyway
                  </button>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: '10px 22px' }}
                    onClick={() => {
                      setRejectionWarning(null);
                      setKeepOriginalMode(true);
                      setStatusMessage('Tailoring cancelled by user.');
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                  <svg style={{ animation: 'spin 1s linear infinite', width: '18px', height: '18px', flexShrink: 0 }} viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" style={{ opacity: 0.25 }} />
                    <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Agent Pipeline Executing…</span>
                </div>
                <div className="log-terminal">
                  <div className="log-terminal-header">
                    <div className="log-terminal-dots">
                      <div className="log-terminal-dot" style={{ background: '#FF5F57' }} />
                      <div className="log-terminal-dot" style={{ background: '#FFBD2E' }} />
                      <div className="log-terminal-dot" style={{ background: '#28CA41' }} />
                    </div>
                    📋 PIPELINE LOGS
                  </div>
                  <div
                    className="log-terminal-body"
                    ref={consoleBodyRef}
                    onScroll={(e) => {
                      const el = e.currentTarget;
                      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                      consoleUserScrolled.current = !atBottom;
                    }}
                  >
                    {statusLogs.map((entry, index) => {
                      const msg = typeof entry === 'string' ? entry : entry.message;
                      const ts = typeof entry === 'object' ? entry.ts : '';
                      let cls = 'log-entry-msg log-default';
                      if (msg.includes('✅')) cls = 'log-entry-msg log-ok';
                      else if (msg.includes('⚠️') || msg.includes('❌')) cls = 'log-entry-msg log-warn';
                      else if (msg.includes('🤖') || msg.includes('👀') || msg.includes('📐') || msg.includes('⚙️') || msg.includes('✍️')) cls = 'log-entry-msg log-ai';
                      else if (msg.includes('Rate limit') || msg.includes('429')) cls = 'log-entry-msg log-ratelimit';
                      return (
                        <div key={index} className="log-entry">
                          <span className="log-entry-ts">{ts}</span>
                          <span className={cls}>{msg}</span>
                        </div>
                      );
                    })}
                    {/* Blinking cursor on last line while loading */}
                    <span className="log-cursor" />
                  </div>
                </div>
              </div>
            ) : !analysisResult ? (
              loading ? (
                // Optimization #5: Show skeleton while loading
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ width: '120px', height: '120px', borderRadius: '50%', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', flexShrink: 0 }} />
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', minWidth: '200px' }}>
                      <div style={{ height: '20px', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', borderRadius: '4px', width: '60%' }} />
                      <div style={{ height: '16px', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', borderRadius: '4px', width: '40%' }} />
                      <div style={{ height: '16px', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', borderRadius: '4px', width: '50%' }} />
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
                    {[1, 2, 3].map((i) => (
                      <div key={i} style={{ height: '80px', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', borderRadius: '8px' }} />
                    ))}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ height: '16px', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', borderRadius: '4px' }} />
                    <div style={{ height: '16px', background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)', backgroundSize: '200% 100%', animation: 'skeleton-loading 1.5s infinite', borderRadius: '4px', width: '80%' }} />
                  </div>
                </div>
              ) : (
                <div className="empty-state">
                  <div className="empty-state-icon">🎯</div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: '6px' }}>Ready to find your fit</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem', maxWidth: '340px', margin: '0 auto' }}>Upload your resume and paste a job description to get your ATS match score and a tailored resume in seconds.</div>
                  </div>
                  <div className="empty-state-steps">
                    <div className="empty-step">
                      <div className="empty-step-num">1</div>
                      <div className="empty-step-label">Paste job URL or description</div>
                    </div>
                    <div className="empty-step">
                      <div className="empty-step-num">2</div>
                      <div className="empty-step-label">Get tailored resume & score</div>
                    </div>
                  </div>
                </div>
              )
            ) : (
              <div>
                {/* ── Job context banner ── */}
                {(jobTitle || company) && (
                  <div className="job-banner" style={{ animation: 'slideDown 0.4s ease both' }}>
                    <span style={{ fontSize: '0.85rem' }}>🎯</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>Targeting:</span>
                    {jobTitle && <span className="job-banner-chip job-banner-role">{jobTitle}</span>}
                    {company && <span className="job-banner-chip job-banner-company">{company}</span>}
                  </div>
                )}

                {/* ── Job Description Display ── */}
                {jobDescription && (
                  <div style={{ marginBottom: '20px', padding: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', borderRadius: '12px', maxHeight: '300px', overflowY: 'auto' }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '10px', color: 'var(--text-muted)' }}>📋 Job Description</div>
                    <div style={{ fontSize: '0.82rem', lineHeight: '1.5', color: 'var(--text-main)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {jobDescription.substring(0, 1000)}{jobDescription.length > 1000 ? '...' : ''}
                    </div>
                  </div>
                )}

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
                    <span style={{ marginTop: '8px', fontWeight: '600', fontSize: '0.85rem' }}>Overall Match</span>
                    <span style={{ fontSize: '0.68rem', opacity: 0.45, marginTop: '2px' }}>
                      40% skills · 35% exp · 25% role
                    </span>
                  </div>

                  {/* Score breakdown bars */}
                  <div style={{ flex: 1, minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '13px', justifyContent: 'center' }}>
                    {[
                      { label: 'Skills Match', score: analysisResult.match_analysis.skills_score, method: 'Deterministic', detail: analysisResult.match_analysis.keyword_stats?.required_matched ? `${analysisResult.match_analysis.keyword_stats.required_matched} keywords` : null },
                      { label: 'Experience', score: analysisResult.match_analysis.experience_score, method: 'Deterministic', detail: analysisResult.match_analysis.keyword_stats?.candidate_years ? `${analysisResult.match_analysis.keyword_stats.candidate_years}y / ${analysisResult.match_analysis.keyword_stats.required_years || '?'}y req` : null },
                      { label: 'Role Fit', score: analysisResult.match_analysis.role_fit_score, method: 'AI Semantic', detail: 'Domain · Seniority · Industry' },
                    ].map(({ label, score, method, detail }, i) => (
                      <div key={label}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '5px' }}>
                          <span style={{ fontSize: '0.83rem', fontWeight: 600 }}>{label}</span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                            <span style={{ fontSize: '0.68rem', padding: '2px 7px', borderRadius: '999px', background: method === 'Deterministic' ? 'rgba(100,220,130,0.12)' : 'rgba(56,189,248,0.12)', color: method === 'Deterministic' ? '#64dc82' : '#38bdf8', fontWeight: 600 }}>
                              {method}
                            </span>
                            <span style={{ fontWeight: 700, fontSize: '0.88rem' }}>{score}%</span>
                          </div>
                        </div>
                        <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '6px', height: '7px', overflow: 'hidden' }}>
                          <div
                            className="score-bar-fill"
                            style={{
                              width: `${score}%`,
                              background: score >= 80 ? 'var(--accent-green)' : score >= 55 ? 'var(--accent-primary)' : '#e57373',
                              animationDelay: `${i * 0.12}s`
                            }}
                          />
                        </div>
                        {detail && <span style={{ fontSize: '0.68rem', opacity: 0.45, marginTop: '3px', display: 'block' }}>{detail}</span>}
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
                    marginTop: '24px', padding: '32px 28px', borderRadius: '16px',
                    background: 'linear-gradient(135deg, rgba(56,189,248,0.08) 0%, rgba(37,99,235,0.04) 100%)',
                    border: '1px solid rgba(56,189,248,0.22)',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '18px', textAlign: 'center',
                    animation: 'slideDown 0.4s ease both'
                  }}>
                    <div style={{ width: '48px', height: '48px', borderRadius: '14px', background: 'var(--accent-gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.4rem', boxShadow: '0 6px 20px rgba(56,189,248,0.3)' }}>🤖</div>
                    <div>
                      <h3 style={{ margin: '0 0 8px', fontSize: '1.05rem', color: '#fff' }}>ATS Score & Analysis Ready</h3>
                      <p style={{ maxWidth: '520px', margin: 0, fontSize: '0.87rem', color: 'var(--text-muted)', lineHeight: '1.65' }}>
                        Keyword alignment, experience scoring, and role-fit analysis are complete.
                        Ready to generate a tailored LaTeX resume and custom cover letter?
                      </p>
                    </div>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', justifyContent: 'center' }}>
                      <button
                        className="btn"
                        style={{ padding: '11px 26px', fontWeight: 700, fontSize: '0.92rem', boxShadow: 'var(--accent-glow)' }}
                        onClick={() => handleGenerateTailoredResume(false)}
                      >
                        ⚡ Tailor Resume & Cover Letter
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '11px 20px' }}
                        onClick={() => {
                          setKeepOriginalMode(true);
                          showToast('📄 Keeping original resume — Overleaf export is ready.', 'info');
                        }}
                      >
                        Keep Original
                      </button>
                    </div>
                  </div>
                ) : keepOriginalMode && !analysisResult.latex_code ? (
                  <div style={{
                    marginTop: '24px', padding: '28px', borderRadius: '14px',
                    background: 'rgba(56,189,248,0.05)', border: '1px solid rgba(56,189,248,0.18)',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px', textAlign: 'center',
                    animation: 'slideDown 0.3s ease both'
                  }}>
                    <div style={{ fontSize: '2rem' }}>📄</div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '1rem', marginBottom: '6px' }}>Using Your Original Resume</div>
                      <div style={{ fontSize: '0.86rem', color: 'var(--text-muted)', maxWidth: '400px', lineHeight: 1.6 }}>
                        Your original resume profile is loaded. You can open it in Overleaf directly, or go back and tailor it for this role.
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', justifyContent: 'center' }}>
                      <button
                        className="btn-overleaf"
                        disabled={loading}
                        onClick={async () => {
                          if (!resumeData) return;
                          setLoading(true);
                          setStatusMessage('Preparing original resume for Overleaf…');
                          try {
                            const res = await fetch(`${API_BASE}/open_original_in_overleaf`, {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                resume_data: resumeData,
                                job_title: jobTitle || '',
                                company: company || '',
                              }),
                            });
                            if (!res.ok) {
                              const err = await res.json();
                              throw new Error(err.detail || 'Failed to prepare Overleaf link');
                            }
                            const data = await res.json();
                            window.open(data.url, '_blank');
                          } catch (err) {
                            console.error(err);
                          } finally {
                            setLoading(false);
                          }
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12s5.37 12 12 12 12-5.37 12-12S18.63 0 12 0zm-1.5 17.5l-4-4 1.41-1.41L10.5 14.67l6.59-6.59L18.5 9.5l-8 8z" /></svg>
                        {loading ? 'Preparing…' : 'Open Original in Overleaf'}
                      </button>
                      <button className="btn btn-secondary" style={{ padding: '9px 18px', fontSize: '0.84rem' }} onClick={() => setKeepOriginalMode(false)}>
                        ← Go Back & Tailor
                      </button>
                    </div>
                  </div>

                ) : (
                  <div className="workspace">
                    <div className="workspace-panel">
                      <div className="panel-toolbar">
                        <div className="mode-toggle">
                          <button
                            className={`mode-btn ${activeTab === 'preview' ? 'active' : ''}`}
                            onClick={() => setActiveTab('preview')}
                          >
                            Preview
                          </button>
                          <button
                            className={`mode-btn ${activeTab === 'latex' ? 'active' : ''}`}
                            onClick={() => setActiveTab('latex')}
                          >
                            LaTeX
                          </button>
                        </div>
                        <button className="btn-overleaf" onClick={openInOverleaf} disabled={loading}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12s5.37 12 12 12 12-5.37 12-12S18.63 0 12 0zm-1.5 17.5l-4-4 1.41-1.41L10.5 14.67l6.59-6.59L18.5 9.5l-8 8z" /></svg>
                          Open in Overleaf
                        </button>
                      </div>

                      {activeTab === 'preview' ? (
                        <div className="panel-content">
                          <div className="resume-preview">
                            <div className="resume-preview-name">{(tailoredResumeData || {}).name || ''}</div>
                            {(tailoredResumeData || {}).summary && (
                              <p style={{ textAlign: 'center', fontSize: '0.82rem', color: 'var(--text-muted)', fontStyle: 'italic', marginTop: '4px', lineHeight: 1.6 }}>
                                {(tailoredResumeData || {}).summary}
                              </p>
                            )}
                            <hr className="resume-preview-divider" />
                            {((tailoredResumeData || {}).skills || []).length > 0 && (
                              <>
                                <div className="resume-section-title">Skills</div>
                                <div className="resume-skills-grid">
                                  {((tailoredResumeData || {}).skills || []).map((skill, i) => (
                                    <span key={i} className="resume-skill-chip">{skill}</span>
                                  ))}
                                </div>
                              </>
                            )}
                            {((tailoredResumeData || {}).experience || []).length > 0 && (
                              <>
                                <div className="resume-section-title">Experience</div>
                                {((tailoredResumeData || {}).experience || []).map((exp, idx) => (
                                  <div key={idx} className="resume-exp-item">
                                    <div className="resume-exp-header">
                                      <span className="resume-exp-role">{exp.role}</span>
                                      <span className="resume-exp-company">@ {exp.company}</span>
                                    </div>
                                    <ul className="resume-exp-bullets">
                                      {(exp.description || []).map((bullet, bidx) => (
                                        <li key={bidx}>{bullet}</li>
                                      ))}
                                    </ul>
                                  </div>
                                ))}
                              </>
                            )}
                            {((tailoredResumeData || {}).projects || []).length > 0 && (
                              <>
                                <div className="resume-section-title">Projects</div>
                                {((tailoredResumeData || {}).projects || []).map((proj, idx) => (
                                  <div key={idx} className="resume-exp-item">
                                    <div className="resume-exp-header">
                                      <span className="resume-exp-role">{proj.title}</span>
                                    </div>
                                    <ul className="resume-exp-bullets">
                                      {(proj.description || []).map((bullet, bidx) => (
                                        <li key={bidx}>{bullet}</li>
                                      ))}
                                    </ul>
                                  </div>
                                ))}
                              </>
                            )}
                          </div>
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
                      <div className="panel-toolbar">
                        <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700 }}>Generated Cover Letter</h3>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '5px 12px', fontSize: '0.76rem', gap: '5px' }}
                            onClick={handleDownloadCoverLetter}
                          >
                            ⬇️ Download
                          </button>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '5px 12px', fontSize: '0.76rem', gap: '5px' }}
                            onClick={() => {
                              navigator.clipboard.writeText(analysisResult.cover_letter || '');
                              setCoverLetterCopied(true);
                              setTimeout(() => setCoverLetterCopied(false), 2000);
                            }}
                          >
                            {coverLetterCopied ? '✓ Copied!' : '📋 Copy'}
                          </button>
                        </div>
                      </div>
                      <div className="panel-content" style={{ whiteSpace: 'pre-wrap' }}>
                        {analysisResult.cover_letter}
                      </div>
                    </div>
                  </div>
                )}
                {/* Execution logs terminal (always visible after analysis) */}
                {statusLogs.length > 0 && (
                  <div className="log-terminal" style={{ marginTop: '22px' }}>
                    <div className="log-terminal-header">
                      <div className="log-terminal-dots">
                        <div className="log-terminal-dot" style={{ background: '#FF5F57' }} />
                        <div className="log-terminal-dot" style={{ background: '#FFBD2E' }} />
                        <div className="log-terminal-dot" style={{ background: '#28CA41' }} />
                      </div>
                      📋 PIPELINE EXECUTION LOGS
                    </div>
                    <div
                      className="log-terminal-body"
                      ref={consoleBodyRef}
                      onScroll={(e) => {
                        const el = e.currentTarget;
                        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                        consoleUserScrolled.current = !atBottom;
                      }}
                    >
                      {statusLogs.map((entry, index) => {
                        const msg = typeof entry === 'string' ? entry : entry.message;
                        const ts = typeof entry === 'object' ? entry.ts : '';
                        let cls = 'log-entry-msg log-default';
                        if (msg.includes('✅')) cls = 'log-entry-msg log-ok';
                        else if (msg.includes('⚠️') || msg.includes('❌')) cls = 'log-entry-msg log-warn';
                        else if (msg.includes('🤖') || msg.includes('👀') || msg.includes('📐') || msg.includes('⚙️') || msg.includes('✍️')) cls = 'log-entry-msg log-ai';
                        else if (msg.includes('Rate limit') || msg.includes('429')) cls = 'log-entry-msg log-ratelimit';
                        return (
                          <div key={index} className="log-entry">
                            <span className="log-entry-ts">{ts}</span>
                            <span className={cls}>{msg}</span>
                          </div>
                        );
                      })}
                      {/* Blinking cursor while loading */}
                      {loading && <span className="log-cursor" />}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Optimization #2: Keyboard Shortcuts Help Modal */}
      {showKeyboardHelp && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 10000, backdropFilter: 'blur(4px)', animation: 'fadeIn 0.2s ease both'
        }} onClick={() => setShowKeyboardHelp(false)}>
          <div style={{
            background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
            borderRadius: '16px', padding: '32px', maxWidth: '500px', width: '90%',
            boxShadow: '0 20px 60px rgba(0,0,0,0.5)', animation: 'slideDown 0.3s ease both'
          }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h2 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 700 }}>Keyboard Shortcuts</h2>
              <button
                className="btn btn-secondary"
                style={{ padding: '4px 8px', fontSize: '1.2rem', minWidth: '32px', minHeight: '32px' }}
                onClick={() => setShowKeyboardHelp(false)}
                aria-label="Close keyboard shortcuts help"
              >
                ✕
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '0.88rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span>Analyze & Tailor Resume</span>
                <kbd style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600 }}>Cmd+Enter</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span>Show Keyboard Shortcuts</span>
                <kbd style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600 }}>?</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span>Close Modal</span>
                <kbd style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600 }}>Esc</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>Expand/Collapse Job Card</span>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Click card</span>
              </div>
            </div>
            <button
              className="btn"
              style={{ width: '100%', marginTop: '24px', fontWeight: 700 }}
              onClick={() => setShowKeyboardHelp(false)}
            >
              Got it
            </button>
          </div>
        </div>
      )}

    </div>
  );
}

export default App;
