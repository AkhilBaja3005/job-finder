import React, { useState, useEffect, useRef, useCallback, useMemo, Suspense, lazy } from 'react';
import { useModalA11y } from './hooks/useModalA11y';

// Optimization #3: Lazy-load dashboard modes for code splitting
const TailorMode = lazy(() => import('./components/TailorMode'));
const DiscoverMode = lazy(() => import('./components/DiscoverMode'));
const HistoryMode = lazy(() => import('./components/HistoryMode'));
const SkeletonLoader = lazy(() => import('./components/SkeletonLoader').then(m => ({ default: m.SkeletonLoader })));
const OutreachModal = lazy(() => import('./components/OutreachModal'));
const DocsGuide = lazy(() => import('./components/DocsGuide'));

// Automatically inject ngrok-skip-browser-warning header into all frontend fetch requests
const originalFetch = window.fetch;
window.fetch = async function (resource, config = {}) {
  config.headers = {
    ...config.headers,
    'ngrok-skip-browser-warning': 'true',
  };
  return originalFetch(resource, config);
};

const API_BASE = import.meta.env.VITE_API_BASE
  || import.meta.env.VITE_BACKEND_URL
  || ((window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:8000'
    : window.location.origin);

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
      // Race stream read against a fresh 120-second stall timer per chunk
      let timerId;
      const readPromise = reader.read();
      const timeoutPromise = new Promise((_, reject) => {
        timerId = setTimeout(() => reject(new Error('Stream stalled: No response chunk received for 120s')), 120000);
      });

      let res;
      try {
        res = await Promise.race([readPromise, timeoutPromise]);
      } finally {
        clearTimeout(timerId);
      }

      const { value, done } = res;
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
    reader.cancel().catch(() => { });
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

// Single source of truth for score → color mapping, used by every score
// ring/bar/badge in the app. Previously each call site hardcoded its own
// thresholds (some used >=55 for the "medium" cutoff, others >=60), so the
// same score could render a different color depending on which screen showed it.
const getScoreColor = (score) => (score >= 80 ? '#10B981' : score >= 60 ? '#38BDF8' : '#E57373');

function App() {
  const [resumeData, setResumeData] = useState(null);
  const [resumeEvaluation, setResumeEvaluation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [jobUrl, setJobUrl] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [company, setCompany] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [urlScraping, setUrlScraping] = useState(false);
  const [urlScrapeError, setUrlScrapeError] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [tailoredResumeData, setTailoredResumeData] = useState(null);
  const [statusMessage, setStatusMessage] = useState('');
  const [statusLogs, setStatusLogs] = useState([]); // each entry: { message, ts }
  const [activeTab, setActiveTab] = useState('preview');
  const [keepOriginalMode, setKeepOriginalMode] = useState(false);
  const [rejectionWarning, setRejectionWarning] = useState(null);
  const [forceTailorEnabled, setForceTailorEnabled] = useState(false);
  const [coverLetterCopied, setCoverLetterCopied] = useState(false);
  const [toast, setToast] = useState(null); // { message, type: 'success'|'error'|'info' }
  const [geminiApiKey, setGeminiApiKey] = useState(localStorage.getItem('gemini_api_key') || '');
  const [backendHealth, setBackendHealth] = useState('checking'); // 'healthy' | 'warming' | 'checking'
  const [commitSha, setCommitSha] = useState('');
  const [commitTime, setCommitTime] = useState('');

  const [discoveredJobs, setDiscoveredJobs] = useState(() => {
    try {
      const saved = sessionStorage.getItem('discovered_jobs');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [discovering, setDiscovering] = useState(false);
  const [searchLocation, setSearchLocation] = useState(() => sessionStorage.getItem('search_location') || 'Remote');
  const [searchKeywords, setSearchKeywords] = useState(() => sessionStorage.getItem('search_keywords') || '');
  const [searchTimeframe, setSearchTimeframe] = useState(() => sessionStorage.getItem('search_timeframe') || '48h'); // '24h' | '48h' | '1w' | '1m'
  const [isDiscoveryView, setIsDiscoveryView] = useState(() => sessionStorage.getItem('is_discovery_view') === 'true');
  const [dashboardMode, setDashboardMode] = useState(() => {
    if (typeof window !== 'undefined' && window.location.pathname.startsWith('/docs')) {
      return 'docs';
    }
    return sessionStorage.getItem('dashboard_mode') || 'tailor';
  });
  const [searchSortMode, setSearchSortMode] = useState('overall'); // 'overall' | 'role_fit' | 'time'
  const [searchPage, setSearchPage] = useState(1);

  const [applicationHistory, setApplicationHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Sync /docs path with dashboardMode
  useEffect(() => {
    const handleLocation = () => {
      if (window.location.pathname.startsWith('/docs')) {
        setDashboardMode('docs');
      }
    };
    handleLocation();
    window.addEventListener('popstate', handleLocation);
    return () => window.removeEventListener('popstate', handleLocation);
  }, []);

  
  // 1-Click Chrome Extension Auto-Sync & Auto-Download Handler
  const handleOneClickExtensionSync = (syncCode) => {
    const targetKey = syncCode || (user && user.sync_code) || "GABY48";
    
    // 1. Copy Key to Clipboard
    try { navigator.clipboard.writeText(targetKey); } catch (e) {}

    // 2. Broadcast postMessage to extension if already installed
    let synced = false;
    const handleResponse = (event) => {
      if (event.data && event.data.type === "SYNC_JOB_FINDER_KEY_SUCCESS") {
        synced = true;
        showToast(`🚀 Extension Auto-Synced to Key: ${targetKey}!`, "success");
        window.removeEventListener("message", handleResponse);
      }
    };
    window.addEventListener("message", handleResponse);
    window.postMessage({ type: "SYNC_JOB_FINDER_KEY", syncKey: targetKey }, "*");

    // 3. Always trigger direct ZIP package download
    const downloadUrl = `${API_BASE}/download_extension?key=${encodeURIComponent(targetKey)}`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `Job_Finder_Extension_${targetKey}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    showToast(`📦 Extension ZIP (${targetKey}) downloading! Unzip & load in chrome://extensions`, "success");

    setTimeout(() => {
      window.removeEventListener("message", handleResponse);
    }, 1500);
  };

  const [user, setUser] = useState(null);
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false);
  const [showExtensionGuide, setShowExtensionGuide] = useState(false);
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

  // Interview Prep feature state
  const [prepModalOpen, setPrepModalOpen] = useState(false);
  const [prepMarkdown, setPrepMarkdown] = useState('');
  const [prepJobInfo, setPrepJobInfo] = useState({ jobTitle: '', company: '' });
  // Cover Letter Modal feature state
  const [coverLetterModalOpen, setCoverLetterModalOpen] = useState(false);
  const [coverLetterText, setCoverLetterText] = useState('');
  const [coverLetterJobInfo, setCoverLetterJobInfo] = useState({ jobTitle: '', company: '' });
  const [coverLetterCopiedModal, setCoverLetterCopiedModal] = useState(false);

  // Escape-to-close + focus trap/return for each modal (shared behavior)
  const [applyingSugIdx, setApplyingSugIdx] = useState(null);
  const [showAllSkills, setShowAllSkills] = useState(false);
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [reviewedResumeData, setReviewedResumeData] = useState(null);
  const [previousResumeData, setPreviousResumeData] = useState(null);
  const [reviewedLatex, setReviewedLatex] = useState('');
  const [beforePdfUrl, setBeforePdfUrl] = useState(null);
  const [afterPdfUrl, setAfterPdfUrl] = useState(null);
  const [reviewModalTab, setReviewModalTab] = useState('diff'); // 'diff' | 'pdf' | 'latex'
  const closeKeyboardHelp = useCallback(() => setShowKeyboardHelp(false), []);
  const keyboardHelpModalRef = useModalA11y(showKeyboardHelp, closeKeyboardHelp);
  const closePrepModal = useCallback(() => setPrepModalOpen(false), []);
  const prepModalRef = useModalA11y(prepModalOpen, closePrepModal);

  // Cron Job Match Mailer Subscription states
  const [cronEnabled, setCronEnabled] = useState(false);
  const [sendTailoredEmail, setSendTailoredEmail] = useState(false);
  const [mailerExpanded, setMailerExpanded] = useState(false);
  const [cronRole, setCronRole] = useState('');
  const [cronLocation, setCronLocation] = useState('Remote');
  const [cronTime, setCronTime] = useState('18:00');

  const [historyFilter, setHistoryFilter] = useState('all');
  const [userSelectedSkills, setUserSelectedSkills] = useState(new Set()); // 'all' | 'tailored' | 'applied'
  const [historySortOrder, setHistorySortOrder] = useState('newest'); // 'newest' | 'oldest'
  const [minHistoryScore, setMinHistoryScore] = useState(0); // Custom match percentage filter
  const [tailoringIntensity, setTailoringIntensity] = useState('balanced'); // 'conservative' | 'balanced' | 'impact'
  const [userArchetypes, setUserArchetypes] = useState([]);
  const [activeArchetype, setActiveArchetype] = useState('Primary');
  const [newArchetypeName, setNewArchetypeName] = useState('');
  const [archetypeLoading, setArchetypeLoading] = useState(false);
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
    setUrlScrapeError('');
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

  // Backend health & warm-up monitoring loop (verifies HF container readiness)
  useEffect(() => {
    let checkTimer;
    const checkHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/healthz`, { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          setBackendHealth('healthy');
          if (data.commit_sha) setCommitSha(data.commit_sha.substring(0, 7));
          if (data.commit_time) {
            try {
              const d = new Date(data.commit_time);
              setCommitTime(d.toLocaleString([], {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false, timeZoneName: 'short'
              }));
            } catch {
              setCommitTime(data.commit_time);
            }
          }
        } else {
          setBackendHealth('warming');
        }
      } catch (e) {
        setBackendHealth('warming');
      }
    };

    checkHealth();
    checkTimer = setInterval(checkHealth, 25000);
    return () => clearInterval(checkTimer);
  }, []);

  // Save active dashboardMode to sessionStorage
  useEffect(() => {
    sessionStorage.setItem('dashboard_mode', dashboardMode);
  }, [dashboardMode]);

  // Optimization #1: Handle window resize for compact mode
  useEffect(() => {
    const handleResize = () => {
      setCompactMode(window.innerWidth < 640);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Optimization #2: Keyboard shortcut - '?' opens the help modal.
  // Escape-to-close and focus trapping for the modal itself are handled by
  // useModalA11y (shared across all modals) once it's open.
  useEffect(() => {
    const handler = (e) => {
      if (e.key === '?' && !showKeyboardHelp) {
        setShowKeyboardHelp(true);
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
          setCronEnabled(!!data.cron_enabled);
          setSendTailoredEmail(data.send_tailored_email !== undefined ? !!data.send_tailored_email : true);
          setCronRole(data.cron_role || '');
          setCronLocation(data.cron_location || 'Remote');
          if (data.cron_time) {
            setCronTime(data.cron_time.slice(0, 5)); // format HH:MM
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

  // Deep-linking / URL Parameter pre-fill from Extension
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const targetJobUrl = params.get("job_url");
    const targetJobTitle = params.get("job_title");
    const targetCompany = params.get("company");
    const targetJd = params.get("job_description");

    if (targetJobUrl || targetJobTitle || targetJd) {
      if (targetJobUrl) setJobUrl(targetJobUrl);
      if (targetJobTitle) setJobTitle(targetJobTitle);
      if (targetCompany) setCompany(targetCompany);
      if (targetJd) {
        setJobDescription(targetJd);
        scrapedJobDescriptionRef.current = targetJd;
      }
      setDashboardMode("tailor");
      setIsDiscoveryView(false);

      // Clean URL bar parameters without refreshing page
      window.history.replaceState({}, document.title, window.location.pathname);

      // Auto-trigger analysis if resume is loaded
      if (resumeData) {
        setTimeout(() => {
          handleAnalyzeJob(targetJobUrl, targetJobTitle);
        }, 500);
      }
    }
  }, [resumeData]);

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
            if (body.evaluation) {
              setResumeEvaluation(body.evaluation);
            }
            setStatusMessage('Loaded persisted resume state.');
          }
        }
      } catch (err) {
        console.error('Failed to load persisted resume', err);
      }
    };
    fetchResume();
    fetchArchetypes();
  }, [authToken]);

  const fetchArchetypes = async () => {
    try {
      const headers = {};
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
      const res = await fetch(`${API_BASE}/user/archetypes`, { headers });
      if (res.ok) {
        const body = await res.json();
        setUserArchetypes(body.archetypes || []);
        if (body.active_archetype) setActiveArchetype(body.active_archetype);
      }
    } catch (e) {}
  };

  const handleSaveArchetype = async () => {
    const name = newArchetypeName.trim();
    if (!name) return;
    setArchetypeLoading(true);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
      const res = await fetch(`${API_BASE}/user/archetypes/save`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ archetype_name: name, latex_code: masterLatex })
      });
      if (res.ok) {
        const body = await res.json();
        setUserArchetypes(body.archetypes || []);
        setActiveArchetype(body.active_archetype || name);
        setNewArchetypeName('');
        showToast(`✅ Saved master archetype: ${name}`, 'success');
      } else {
        showToast('Failed to save archetype', 'error');
      }
    } catch (e) {
      showToast('Failed to save archetype: ' + e.message, 'error');
    } finally {
      setArchetypeLoading(false);
    }
  };

  const handleSwitchArchetype = async (name) => {
    if (!name || name === activeArchetype) return;
    setArchetypeLoading(true);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
      const res = await fetch(`${API_BASE}/user/archetypes/switch`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ archetype_name: name })
      });
      if (res.ok) {
        const body = await res.json();
        setActiveArchetype(body.active_archetype || name);
        if (body.data) setResumeData(body.data);
        if (body.evaluation) setResumeEvaluation(body.evaluation);
        showToast(`⚡ Switched active master profile to: ${name}`, 'success');
        fetchArchetypes();
      }
    } catch (e) {
      showToast('Failed to switch archetype: ' + e.message, 'error');
    } finally {
      setArchetypeLoading(false);
    }
  };

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
        setResumeEvaluation(null);
        setAnalysisResult(null);
        setTailoredResumeData(null);
        setRejectionWarning(null);
        setJobUrl('');
        setJobTitle('');
        setJobDescription('');
        setCompany('');
        setStatusLogs([]);
        setStatusMessage('Caches cleared successfully!');
        // showToast('🧹 All caches and files deleted!', 'success');
      } else {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to clear cache');
      }
    } catch (err) {
      setStatusMessage(`Clear cache failed: ${err.message}`);
      // showToast(`❌ ${err.message}`, 'error');
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
      if (data && data.url) {
        window.location.href = data.url;
      } else {
        throw new Error(data.detail || 'Google OAuth is not configured on this server.');
      }
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

  const saveSubscriptionToCloud = async (enabled, role, location, time, tailoredEmail = sendTailoredEmail) => {
    if (!authToken) return;
    setLoading(true);
    setStatusMessage('Updating job matching subscription preferences...');
    try {
      const res = await fetch(`${API_BASE}/user/subscription`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({
          cron_enabled: enabled,
          cron_role: role || null,
          cron_location: location || 'Remote',
          cron_time: time ? `${time}:00` : '18:00:00',
          send_tailored_email: tailoredEmail
        })
      });
      if (res.ok) {
        setStatusMessage('Subscription preferences updated successfully!');
        // showToast('📬 Subscription updated!', 'success');
        const meRes = await fetch(`${API_BASE}/user/me`, {
          headers: { 'Authorization': `Bearer ${authToken}` }
        });
        const meData = await meRes.json();
        setUser(meData);
      } else {
        throw new Error('Failed to save subscription preferences');
      }
    } catch (err) {
      setStatusMessage(`Error updating subscription: ${err.message}`);
      // showToast(`Error: ${err.message}`, 'error');
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
        setResumeEvaluation(result.evaluation || null);
        // Fully clear all previous job analysis, tailoring cache, and modal states like a fresh first-time launch
        setJobUrl('');
        setJobTitle('');
        setJobDescription('');
        setCompany('');
        setAnalysisResult(null);
        setTailoredResumeData(null);
        setRejectionWarning(null);
        setKeepOriginalMode(false);
        setStatusLogs([]);
        setPreviousResumeData(null);
        setReviewedResumeData(null);
        setReviewedLatex('');
        setBeforePdfUrl(null);
        setAfterPdfUrl(null);
        setShowReviewModal(false);
        setCoverLetterCopied(false);
        setStatusMessage('✅ Baseline PDF generated & master resume evaluated successfully!');
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
          tailoring_intensity: tailoringIntensity,
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
          force_tailoring: overrideForce,
          tailoring_intensity: tailoringIntensity
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

          // Save overleaf_url to history if returned in result
          if (result.overleaf_url) {
            fetch(`${API_BASE}/open_in_overleaf`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getAuthHeader()}` },
              body: JSON.stringify({
                latex_code: result.analysis.latex_code,
                candidate_name: resumeData?.name || '',
                job_title: jobTitle || '',
                company: company || ''
              })
            }).catch(() => { });
          }
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
      return;
    }
    setDiscovering(true);
    setIsDiscoveryView(true);
    setDiscoveredJobs([]);

    const initMsg = `🔎 Scanning LinkedIn, Indeed, Reed, Greenhouse, Ashby & Lever for matching jobs posted in the last ${searchTimeframe === '24h' ? '24 hours' : searchTimeframe === '48h' ? '48 hours' : searchTimeframe === '1w' ? '1 week' : '1 month'}...`;
    setStatusMessage(initMsg);
    setStatusLogs([{ message: initMsg, ts: nowTs() }]);

    // ── SSE log stream: connect to /user/logs/stream to pipe all backend logs
    // into the pipeline log box in real time, independently of the main search fetch.
    let logEventSource = null;
    try {
      const sseUrl = new URL(`${API_BASE}/user/logs/stream`);
      logEventSource = new EventSource(sseUrl.toString());
      // NOTE: EventSource doesn't support custom headers, so we send auth as query param
      // Recreate with token query param approach via fetch-based SSE reader instead
      logEventSource.close();
      logEventSource = null;
    } catch (e) { /* ignore */ }

    // Filter: which log messages to show in the UI pipeline log box.
    // The admin stream stays fully verbose; we only suppress internal recruiter noise here.
    const shouldShowLog = (msg) => {
      // Strip timestamp prefix e.g. "[19:53:56 IST] " for pattern matching
      const body = msg.replace(/^\[\d{2}:\d{2}:\d{2} IST\]\s*/, '');
      // Drop recruiter pre-fetched HTML verbose lines (not useful to users)
      if (/^\[extract_recruiter_from_linkedin\] Using pre-fetched HTML for:/.test(body)) return false;
      // Drop raw recruiter_extractor found lines (redundant in UI)
      if (/^\[recruiter_extractor\]/.test(body)) return false;
      return true;
    };

    // Use fetch-based SSE reader (supports Authorization header)
    let sseAbort = new AbortController();
    const sseHeaders = { 'Authorization': `Bearer ${getAuthHeader()}`, 'ngrok-skip-browser-warning': 'true' };
    (async () => {
      try {
        const sseRes = await fetch(`${API_BASE}/user/logs/stream`, { headers: sseHeaders, signal: sseAbort.signal });
        if (!sseRes.ok) return;
        const sseReader = sseRes.body.getReader();
        const sseDec = new TextDecoder();
        let sseBuf = '';
        while (true) {
          const { value, done } = await sseReader.read();
          if (done) break;
          sseBuf += sseDec.decode(value, { stream: true });
          const lines = sseBuf.split('\n');
          sseBuf = lines.pop();
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const msg = line.slice(6).trim();
              if (!msg || msg.startsWith('🟢')) continue;
              if (!shouldShowLog(msg)) continue;
              setStatusMessage(msg);
              setStatusLogs((prev) => [...prev, { message: msg, ts: nowTs() }]);
              setTimeout(scrollConsoleToBottom, 30);
            }
          }
        }
      } catch (e) {
        // SSE closed normally (aborted) — ignore
      }
    })();

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (geminiApiKey) headers['X-Gemini-API-Key'] = geminiApiKey;
      headers['Authorization'] = `Bearer ${getAuthHeader()}`;

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
        if (event.type === 'partial_result' && event.job) {
          setDiscoveredJobs((prev) => {
            if (prev.some((j) => j.url === event.job.url)) return prev;
            const updated = [...prev, event.job].sort((a, b) => (a.estimated === b.estimated ? b.score - a.score : a.estimated ? 1 : -1));
            try { sessionStorage.setItem('discovered_jobs', JSON.stringify(updated)); } catch (e) { }
            return updated;
          });
        } else if (event.type === 'result') {
          const jobsList = event.jobs || [];
          setDiscoveredJobs(jobsList);
          try {
            sessionStorage.setItem('discovered_jobs', JSON.stringify(jobsList));
            sessionStorage.setItem('search_location', searchLocation);
            sessionStorage.setItem('search_keywords', searchKeywords);
            sessionStorage.setItem('search_timeframe', searchTimeframe);
            sessionStorage.setItem('is_discovery_view', 'true');
            sessionStorage.setItem('dashboard_mode', 'discover');
          } catch (e) {
            console.error('Failed to save discovered jobs to sessionStorage:', e);
          }
          setStatusMessage(`Found ${jobsList.length} matching jobs.`);
        }
      }
    } catch (err) {
      setStatusMessage(`Discovery failed: ${err.message}`);
      setStatusLogs((prev) => [...prev, { message: `❌ Discovery failed: ${err.message}`, ts: nowTs() }]);
    } finally {
      // Close the SSE log stream
      sseAbort.abort();
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

    // Normalise LinkedIn search-results URLs → canonical /jobs/view/{id}
    let cleanUrl = jobUrl;
    if (cleanUrl.includes('linkedin.com') && cleanUrl.includes('currentJobId=')) {
      const match = cleanUrl.match(/currentJobId=(\d+)/);
      if (match) {
        cleanUrl = `https://www.linkedin.com/jobs/view/${match[1]}/`;
        setJobUrl(cleanUrl);
      }
    }

    setUrlScraping(true);
    setUrlScrapeError('');
    setStatusMessage('Scraping job description automatically...');
    try {
      const res = await fetch(`${API_BASE}/scrape_job`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: cleanUrl })
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
      setUrlScrapeError(err.message);
    } finally {
      setUrlScraping(false);
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
      // showToast(`❌ ${err.message}`, 'error');
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
      // showToast('✅ Overleaf opened in a new tab!', 'success');
    } catch (err) {
      setStatusMessage(`Error opening in Overleaf: ${err.message}`);
      // showToast(`❌ ${err.message}`, 'error');
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
      // showToast('Please analyze a job first', 'error');
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
        // showToast('Outreach message ready!', 'success');
      } else {
        console.log('[handleGenerateOutreach] Error response', result);
        setStatusMessage(`Error generating outreach: ${result.detail}`);
        // showToast(`Error: ${result.detail}`, 'error');
      }
    } catch (err) {
      console.log('[handleGenerateOutreach] Exception', err);
      setStatusMessage(`Network error: ${err.message}`);
      // showToast(`Error: ${err.message}`, 'error');
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
        // showToast('Email prepared for sending!', 'success');
        setOutreachModalOpen(false);
      } else {
        // showToast(`Error: ${result.detail}`, 'error');
      }
    } catch (err) {
      // showToast(`Error: ${err.message}`, 'error');
    }
  };

  return (
    <>
      <div className="app-container">
      {/* Optimization #5: Progress bar at top of page */}
      {loading && <div className="progress-bar" />}

      {/* Toast Notification */}
      {toast && (
        <div style={{
          position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
          zIndex: 99999, padding: '16px 28px', borderRadius: '16px', fontWeight: 700,
          fontSize: '0.94rem', display: 'flex', alignItems: 'center', gap: '12px',
          animation: 'fadeIn 0.25s ease both',
          background: 'rgba(9, 13, 26, 0.95)',
          border: `1.5px solid ${toast.type === 'success' ? '#10B981' : toast.type === 'error' ? '#EF4444' : '#0284C7'}`,
          color: toast.type === 'success' ? '#34D399' : toast.type === 'error' ? '#F87171' : '#7DD3FC',
          backdropFilter: 'blur(24px)', boxShadow: '0 20px 50px rgba(0,0,0,0.8)'
        }}>
          {toast.message}
        </div>
      )}

      {/* Full-Screen Review Changes Modal after Auto-Apply */}
      {showReviewModal && reviewedResumeData && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(9, 13, 26, 0.92)', backdropFilter: 'blur(12px)',
          zIndex: 999999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px'
        }}>
          <div className="card" style={{
            maxWidth: '900px', width: '100%', maxHeight: '88vh', overflowY: 'auto',
            border: '1px solid rgba(56, 189, 248, 0.4)', padding: '28px',
            display: 'flex', flexDirection: 'column', gap: '20px', background: '#0F172A',
            boxShadow: '0 25px 60px rgba(0,0,0,0.8)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: '1.25rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>✨ Master Resume Profile Updated</span>
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '3px' }}>
                  The AI enhancement has been incorporated into your master profile. Review the exact additions highlighted in green below:
                </div>
              </div>
              <button
                className="btn btn-secondary"
                style={{ padding: '6px 14px', fontSize: '0.82rem' }}
                onClick={() => setShowReviewModal(false)}
              >
                ✕ Close Review
              </button>
            </div>

            {/* Toggle view tabs: PDF Side-by-Side Comparison vs Master Profile Diff vs LaTeX Source Code */}
            <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
              <button
                className="btn btn-secondary"
                style={{
                  padding: '6px 14px', fontSize: '0.8rem', fontWeight: 700,
                  borderColor: reviewModalTab === 'pdf' ? '#10B981' : 'rgba(255,255,255,0.1)',
                  color: reviewModalTab === 'pdf' ? '#10B981' : 'var(--text-muted)',
                  background: reviewModalTab === 'pdf' ? 'rgba(16, 185, 129, 0.15)' : 'transparent'
                }}
                onClick={() => setReviewModalTab('pdf')}
              >
                📄 PDF Comparison (Before vs After)
              </button>
              <button
                className="btn btn-secondary"
                style={{
                  padding: '6px 14px', fontSize: '0.8rem', fontWeight: 600,
                  borderColor: reviewModalTab === 'diff' ? 'var(--accent-secondary)' : 'rgba(255,255,255,0.1)',
                  color: reviewModalTab === 'diff' ? '#fff' : 'var(--text-muted)',
                  background: reviewModalTab === 'diff' ? 'rgba(56, 189, 248, 0.15)' : 'transparent'
                }}
                onClick={() => setReviewModalTab('diff')}
              >
                📊 Structured Diff View
              </button>
              {reviewedLatex && (
                <button
                  className="btn btn-secondary"
                  style={{
                    padding: '6px 14px', fontSize: '0.8rem', fontWeight: 600,
                    borderColor: reviewModalTab === 'latex' ? 'var(--accent-secondary)' : 'rgba(255,255,255,0.1)',
                    color: reviewModalTab === 'latex' ? '#fff' : 'var(--text-muted)',
                    background: reviewModalTab === 'latex' ? 'rgba(56, 189, 248, 0.15)' : 'transparent'
                  }}
                  onClick={() => setReviewModalTab('latex')}
                >
                  📝 LaTeX Source Code
                </button>
              )}
            </div>

            {/* TAB 1: PDF BEFORE VS AFTER SIDE-BY-SIDE VIEW */}
            {reviewModalTab === 'pdf' && (
              <div style={{ display: 'grid', gridTemplateColumns: beforePdfUrl ? '1fr 1fr' : '1fr', gap: '16px', marginTop: '6px' }}>
                {beforePdfUrl && (
                  <div style={{ background: '#090D1A', padding: '12px', borderRadius: '10px', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 800, color: '#F87171', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>🔴 BEFORE (Previous Baseline PDF)</span>
                      <a href={beforePdfUrl} target="_blank" rel="noreferrer" style={{ fontSize: '0.74rem', color: '#F87171', textDecoration: 'underline' }}>Open Full PDF ↗</a>
                    </div>
                    <iframe
                      src={beforePdfUrl}
                      title="Before Resume PDF"
                      style={{ width: '100%', height: '480px', border: 'none', borderRadius: '6px', background: '#fff' }}
                    />
                  </div>
                )}

                <div style={{ background: '#090D1A', padding: '12px', borderRadius: '10px', border: '1px solid rgba(16, 185, 129, 0.4)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 800, color: '#34D399', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>🟢 AFTER (Updated Auto-Applied PDF)</span>
                    {afterPdfUrl && <a href={afterPdfUrl} target="_blank" rel="noreferrer" style={{ fontSize: '0.74rem', color: '#34D399', textDecoration: 'underline' }}>Open Full PDF ↗</a>}
                  </div>
                  {afterPdfUrl ? (
                    <iframe
                      src={afterPdfUrl}
                      title="After Resume PDF"
                      style={{ width: '100%', height: '480px', border: 'none', borderRadius: '6px', background: '#fff' }}
                    />
                  ) : (
                    <div style={{ height: '480px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '0.84rem' }}>
                      ⏳ Compiling updated PDF...
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: LATEX CODE */}
            {reviewModalTab === 'latex' && reviewedLatex && (
              <div style={{ background: '#090D1A', padding: '16px', borderRadius: '10px', border: '1px solid rgba(56, 189, 248, 0.3)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent-secondary)' }}>UPDATED MASTER RESUME LATEX SOURCE</div>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                    onClick={() => {
                      navigator.clipboard.writeText(reviewedLatex);
                      showToast('LaTeX code copied to clipboard!', 'success');
                    }}
                  >
                    📋 Copy LaTeX Code
                  </button>
                </div>
                <pre style={{
                  fontFamily: 'Consolas, Monaco, "Andale Mono", monospace',
                  fontSize: '0.78rem',
                  color: '#E2E8F0',
                  background: 'rgba(0,0,0,0.4)',
                  padding: '14px',
                  borderRadius: '8px',
                  maxHeight: '440px',
                  overflowY: 'auto',
                  lineHeight: 1.45,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  margin: 0
                }}>
                  {reviewedLatex}
                </pre>
              </div>
            )}

            {/* TAB 3: STRUCTURED DIFF VIEW */}
            {reviewModalTab === 'diff' && (
              <>
                {/* Professional Summary Diff View */}
                {reviewedResumeData.summary && (
                  <div style={{ background: 'var(--panel-bg)', padding: '16px', borderRadius: '10px', borderLeft: '4px solid var(--accent-cyan)' }}>
                    <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-cyan)', marginBottom: '6px' }}>PROFESSIONAL SUMMARY</div>
                    {previousResumeData && previousResumeData.summary && previousResumeData.summary.trim() !== reviewedResumeData.summary.trim() ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div style={{ fontSize: '0.8rem', color: '#F87171', background: 'rgba(239,68,68,0.12)', padding: '10px 12px', borderRadius: '6px', borderLeft: '3px solid #EF4444' }}>
                          <span style={{ fontWeight: 800, marginRight: '6px' }}>- OLD:</span>
                          <span style={{ textDecoration: 'line-through' }}>{previousResumeData.summary}</span>
                        </div>
                        <div style={{ fontSize: '0.82rem', color: '#34D399', background: 'rgba(16,185,129,0.12)', padding: '10px 12px', borderRadius: '6px', borderLeft: '3px solid #10B981', fontWeight: 600 }}>
                          <span style={{ fontWeight: 800, marginRight: '6px' }}>+ NEW:</span>
                          {reviewedResumeData.summary}
                        </div>
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.84rem', color: 'var(--text-main)', fontStyle: 'italic', lineHeight: 1.55 }}>
                        {reviewedResumeData.summary}
                      </div>
                    )}
                  </div>
                )}

                {/* Skills Diff View */}
                {reviewedResumeData.skills && (
                  <div style={{ background: 'var(--panel-bg)', padding: '16px', borderRadius: '10px', borderLeft: '4px solid var(--accent-secondary)' }}>
                    <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-secondary)', marginBottom: '8px' }}>SKILLS & FRAMEWORKS</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {(Array.isArray(reviewedResumeData.skills) ? reviewedResumeData.skills : [reviewedResumeData.skills]).map((s, i) => {
                        const prevSkills = previousResumeData ? (Array.isArray(previousResumeData.skills) ? previousResumeData.skills.map(x => String(x).trim().toLowerCase()) : [String(previousResumeData.skills).trim().toLowerCase()]) : [];
                        const isNewSkill = previousResumeData && !prevSkills.includes(String(s).trim().toLowerCase());
                        return (
                          <span key={i} style={{
                            padding: '4px 10px', borderRadius: '6px',
                            background: isNewSkill ? 'rgba(16,185,129,0.22)' : 'rgba(56, 189, 248, 0.1)',
                            color: isNewSkill ? '#34D399' : 'var(--accent-secondary)',
                            border: isNewSkill ? '1px solid #10B981' : '1px solid transparent',
                            fontSize: '0.78rem', fontWeight: isNewSkill ? 700 : 600
                          }}>
                            {isNewSkill ? `+ ${s}` : s}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Work Experience Diff View */}
                {reviewedResumeData.experience && reviewedResumeData.experience.length > 0 && (
                  <div style={{ background: 'var(--panel-bg)', padding: '16px', borderRadius: '10px', borderLeft: '4px solid var(--accent-green)' }}>
                    <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-green)', marginBottom: '10px' }}>WORK EXPERIENCE</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                      {reviewedResumeData.experience.map((exp, i) => {
                        const prevExp = previousResumeData && previousResumeData.experience ? previousResumeData.experience.find(e => e.role === exp.role || e.company === exp.company) : null;
                        const prevBullets = prevExp ? (prevExp.description || []).map(b => String(b).trim()) : [];
                        return (
                          <div key={i} style={{ fontSize: '0.84rem' }}>
                            <div style={{ fontWeight: 700, color: '#fff', fontSize: '0.9rem' }}>{exp.role} <span style={{ color: 'var(--text-muted)' }}>@ {exp.company}</span></div>
                            <ul style={{ margin: '6px 0 0 18px', padding: 0, color: 'var(--text-main)', fontSize: '0.81rem', lineHeight: 1.5, listStyleType: 'disc' }}>
                              {(exp.description || []).map((b, bi) => {
                                const isNewBullet = previousResumeData && !prevBullets.includes(String(b).trim());
                                return (
                                  <li key={bi} style={{
                                    color: isNewBullet ? '#34D399' : 'var(--text-main)',
                                    background: isNewBullet ? 'rgba(16,185,129,0.15)' : 'transparent',
                                    borderLeft: isNewBullet ? '3px solid #10B981' : 'none',
                                    padding: isNewBullet ? '6px 10px' : '0',
                                    borderRadius: isNewBullet ? '4px' : '0',
                                    margin: isNewBullet ? '6px 0' : '0'
                                  }}>
                                    {isNewBullet ? <strong>+ {b}</strong> : b}
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '12px' }}>
              <button
                className="btn"
                style={{ padding: '10px 24px', fontSize: '0.9rem', fontWeight: 700 }}
                onClick={() => setShowReviewModal(false)}
              >
                ✓ Looks Good, Done
              </button>
            </div>
          </div>
        </div>
      )}

      <header className="app-header">
        <h1 className="title">
          Resume Tailor Suite
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Hugging Face / Backend Health Badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '4px 10px', borderRadius: '20px', fontSize: '0.74rem', fontWeight: 600,
            background: backendHealth === 'healthy' ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.15)',
            border: `1px solid ${backendHealth === 'healthy' ? 'rgba(16,185,129,0.25)' : 'rgba(245,158,11,0.3)'}`,
            color: backendHealth === 'healthy' ? 'var(--accent-green)' : 'var(--accent-amber)',
            cursor: 'default'
          }} title={
            backendHealth === 'healthy'
              ? `HF Space Active • Commit SHA: ${commitSha || 'latest'}${commitTime ? ` • commit time: ${commitTime}` : ''}`
              : 'Hugging Face container warming up...'
          }>
            <span style={{
              width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
              background: backendHealth === 'healthy' ? 'var(--accent-green)' : 'var(--accent-amber)',
              boxShadow: backendHealth === 'healthy' ? '0 0 8px rgba(16,185,129,0.6)' : '0 0 8px rgba(245,158,11,0.6)',
              animation: backendHealth === 'healthy' ? 'none' : 'pulseGlow 1.5s infinite'
            }} />
            {backendHealth === 'healthy' ? 'HF Space Active' : 'HF Warming Up...'}
          </div>

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
                  ? 'var(--accent-red)' : statusMessage.includes('✅') || statusMessage.includes('success') || statusMessage.includes('Success')
                    ? 'var(--accent-green)' : 'var(--accent-secondary)'
              }} />
              <span style={{ fontSize: '0.78rem', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {statusMessage.length > 55 ? `${statusMessage.substring(0, 55)}…` : statusMessage}
              </span>
            </div>
          )}
          {/* Docs & Setup Guide Button */}
          <button
            className="btn btn-secondary"
            style={{
              padding: '6px 13px',
              fontSize: '0.82rem',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: dashboardMode === 'docs' ? 'rgba(56, 189, 248, 0.2)' : 'rgba(255,255,255,0.06)',
              borderColor: dashboardMode === 'docs' ? 'var(--accent-primary)' : 'rgba(255,255,255,0.15)',
              color: dashboardMode === 'docs' ? '#38bdf8' : '#e2e8f0',
              cursor: 'pointer',
              borderRadius: '8px'
            }}
            onClick={() => {
              if (dashboardMode === 'docs') {
                setDashboardMode('tailor');
                window.history.pushState(null, '', '/');
              } else {
                setDashboardMode('docs');
                window.history.pushState(null, '', '/docs');
              }
            }}
            title="View Setup Guide & Documentation"
          >
            <span>📖</span>
            <span>Docs & Guide</span>
          </button>

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
            <div style={{ position: 'relative', display: 'inline-block', zIndex: 10000 }}>
              <button
                className="btn btn-secondary"
                style={{
                  padding: '6px 14px', fontSize: '0.84rem', fontWeight: 700,
                  display: 'flex', alignItems: 'center', gap: '8px',
                  borderColor: profileDropdownOpen ? '#38bdf8' : 'rgba(255,255,255,0.15)',
                  background: profileDropdownOpen ? 'rgba(56, 189, 248, 0.15)' : '#0f172a'
                }}
                onClick={() => setProfileDropdownOpen(!profileDropdownOpen)}
              >
                <span>👤</span>
                <span style={{ color: '#fff' }}>{user.email ? user.email.split("@")[0] : "Account"}</span>
                <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{profileDropdownOpen ? "▲" : "▼"}</span>
              </button>

              {profileDropdownOpen && (
                <div style={{
                  position: 'absolute', top: 'calc(100% + 10px)', right: 0,
                  width: '300px', background: 'rgba(15, 23, 42, 0.95)', border: '1px solid rgba(56, 189, 248, 0.3)',
                  borderRadius: '18px', padding: '18px', zIndex: 99999,
                  boxShadow: '0 24px 50px rgba(0, 0, 0, 0.85), 0 0 20px rgba(56, 189, 248, 0.15)',
                  backdropFilter: 'blur(24px)', display: 'flex', flexDirection: 'column', gap: '14px'
                }}>
                  {/* User Profile Header Badge */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', paddingBottom: '12px', borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                    <div style={{
                      width: '40px', height: '40px', borderRadius: '50%',
                      background: 'linear-gradient(135deg, #0284c7 0%, #10b981 100%)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 800, color: '#fff', fontSize: '1.1rem',
                      boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)', flexShrink: 0
                    }}>
                      {user.email ? user.email.charAt(0).toUpperCase() : "U"}
                    </div>
                    <div style={{ overflow: 'hidden' }}>
                      <div style={{ fontSize: '0.7rem', fontWeight: 800, color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Account</div>
                      <div style={{ fontSize: '0.84rem', fontWeight: 700, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.email}</div>
                    </div>
                  </div>

                  {/* Subtle Action Button */}
                  <button
                    className="btn btn-secondary"
                    style={{
                      padding: '9px 14px', fontSize: '0.8rem', fontWeight: 700,
                      borderColor: 'rgba(56, 189, 248, 0.4)', color: '#38bdf8',
                      background: 'rgba(2, 132, 199, 0.12)', borderRadius: '10px',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', cursor: 'pointer'
                    }}
                    onClick={() => {
                      handleOneClickExtensionSync(user.sync_code);
                      setShowExtensionGuide(true);
                      setProfileDropdownOpen(false);
                    }}
                  >
                    <span>⚡ 1-Click Auto-Sync & Download</span>
                  </button>

                  <button
                    className="btn btn-secondary"
                    style={{ padding: '7px 10px', fontSize: '0.76rem', color: '#94a3b8', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px' }}
                    onClick={() => {
                      setShowExtensionGuide(true);
                      setProfileDropdownOpen(false);
                    }}
                  >
                    <span>📖 Setup Instructions</span>
                  </button>

                  <button
                    className="btn btn-secondary"
                    style={{
                      padding: '8px', fontSize: '0.8rem', width: '100%',
                      color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.25)',
                      borderRadius: '10px', background: 'rgba(239, 68, 68, 0.05)'
                    }}
                    onClick={() => {
                      setProfileDropdownOpen(false);
                      handleLogout();
                    }}
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {dashboardMode === 'docs' ? (
        <Suspense fallback={<div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading Documentation & Setup Guide...</div>}>
          <DocsGuide
            user={user}
            userToken={authToken}
            onDownloadExtension={() => handleOneClickExtensionSync(user?.sync_code)}
            onNavigateMode={(mode) => {
              setDashboardMode(mode);
              window.history.pushState(null, '', '/');
            }}
          />
        </Suspense>
      ) : !user ? (
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
        <div className="setup-container" style={{
          maxWidth: resumeData && resumeEvaluation ? '1100px' : '580px',
          margin: '40px auto',
          display: resumeData && resumeEvaluation ? 'grid' : 'flex',
          gridTemplateColumns: resumeData && resumeEvaluation ? '1fr 1fr' : undefined,
          flexDirection: resumeData && resumeEvaluation ? undefined : 'column',
          gap: '24px',
          alignItems: 'stretch',
          justifyContent: 'center'
        }}>
          {/* Left Panel: Configuration & Master Resume Upload */}
          <div className="card" style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            padding: '32px'
          }}>
            <div>
              <h2 style={{ marginBottom: '4px' }}>Setup & Configuration</h2>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.87rem' }}>Configure your AI key and upload your master resume to get started.</p>
            </div>

            {/* API Key section */}
            <div>
              <div className="section-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>LLM API Key</span>
                <a
                  href="https://aistudio.google.com/app/apikey"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: '0.73rem', color: 'var(--accent-secondary)', fontWeight: 600, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '3px' }}
                >
                  🔑 Get Free Gemini Key from Google ↗
                </a>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="password"
                  placeholder="Paste Gemini (AIza...), Groq (gsk_...), or Claude (sk-ant-...) key"
                  value={geminiApiKey}
                  onChange={handleApiKeyChange}
                  style={{ fontFamily: 'var(--font-mono)', flexGrow: 1, marginBottom: 0, fontSize: '0.84rem' }}
                />
                <button className="btn" style={{ padding: '10px 14px', fontSize: '0.82rem', flexShrink: 0 }} onClick={saveApiKeyToCloud}>
                  Save
                </button>
              </div>
              <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                Supports Gemini, Groq, and Anthropic Claude keys. Stored securely in your session/cloud account.
              </div>
            </div>

            {/* Resume upload section */}
            <div>
              <div className="section-label">Master Resume</div>
              <label style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px',
                padding: '24px 20px', borderRadius: '12px', cursor: 'pointer',
                border: resumeData ? '1.5px solid rgba(16,185,129,0.4)' : '1.5px dashed var(--border-color)',
                background: resumeData ? 'rgba(16,185,129,0.04)' : 'var(--panel-bg)',
                transition: 'all 0.25s ease'
              }}>
                <input type="file" accept=".tex,.pdf,.docx" onChange={handleResumeUpload} style={{ display: 'none' }} />
                {resumeData ? (
                  <>
                    <div style={{ fontSize: '1.5rem' }}>✅</div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontWeight: 700, color: 'var(--accent-green)', fontSize: '0.92rem' }}>{resumeData.name}</div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '3px' }}>Click to replace master resume (.TEX, .PDF, .DOCX)</div>
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: '1.5rem' }}>📄</div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>Drop your resume here or click to browse</div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '3px' }}>LaTeX (.tex), PDF, or DOCX — becomes your master profile</div>
                    </div>
                  </>
                )}
              </label>

              {resumeData && (
                <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                  <button
                    className="btn-overleaf"
                    disabled={loading}
                    style={{ flex: 1, padding: '8px 12px', fontSize: '0.78rem', justifyContent: 'center' }}
                    onClick={async (e) => {
                      e.stopPropagation();
                      setLoading(true);
                      setStatusMessage('Preparing Master Resume LaTeX for Overleaf…');
                      try {
                        const res = await fetch(`${API_BASE}/open_original_in_overleaf`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            resume_data: resumeData,
                            job_title: 'Master Resume',
                            company: '',
                          }),
                        });
                        if (!res.ok) throw new Error('Overleaf export failed');
                        const data = await res.json();
                        if (data.url) {
                          window.open(data.url, '_blank');
                          setStatusMessage('✅ Master Resume opened in Overleaf!');
                        }
                      } catch (err) {
                        setStatusMessage(`Failed to open in Overleaf: ${err.message}`);
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    🍃 Open Master in Overleaf
                  </button>
                  <button
                    className="btn btn-secondary"
                    disabled={loading}
                    style={{
                      flex: 1,
                      padding: '8px 12px',
                      fontSize: '0.78rem',
                      fontWeight: 700,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '5px',
                      background: 'rgba(56, 189, 248, 0.12)',
                      color: 'var(--accent-secondary)',
                      border: '1px solid rgba(56, 189, 248, 0.3)'
                    }}
                    onClick={async (e) => {
                      e.stopPropagation();
                      setLoading(true);
                      setStatusMessage('Compiling Master Resume PDF…');
                      try {
                        const res = await fetch(`${API_BASE}/compile_master_pdf`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            resume_data: resumeData,
                            job_title: 'Master Resume',
                            company: '',
                          }),
                        });
                        if (!res.ok) throw new Error('Master PDF compilation failed');
                        const data = await res.json();
                        if (data.pdf_url) {
                          window.open(`${API_BASE}${data.pdf_url}`, '_blank');
                          setStatusMessage('📄 Master PDF opened!');
                        }
                      } catch (err) {
                        setStatusMessage(`Failed to compile Master PDF: ${err.message}`);
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    📄 View Compiled Master PDF
                  </button>
                </div>
              )}
            </div>

            {/* Chrome Extension Pairing Key Card (hidden for now) */}
            {/*
            <div style={{
              background: 'rgba(56, 189, 248, 0.05)',
              borderRadius: '12px',
              padding: '14px 16px',
              border: '1px solid rgba(56, 189, 248, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px'
            }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: '0.86rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  ⚡ Chrome Extension Sync Key
                </div>
                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Enter this 6-digit key in the Chrome Extension to pair your account instantly.
                </div>
              </div>
              <div style={{
                fontSize: '1.1rem',
                fontWeight: 800,
                color: '#38bdf8',
                background: 'rgba(56, 189, 248, 0.12)',
                border: '1px solid rgba(56, 189, 248, 0.3)',
                padding: '6px 14px',
                borderRadius: '8px',
                letterSpacing: '2px',
                fontFamily: 'monospace'
              }}>
                {(user && user.sync_code) ? user.sync_code : 'GUEST1'}
              </div>
            </div>
            */}

            {/* Daily Cron Match Mailer Subscription settings */}
            <div style={{ border: '1px solid rgba(56, 189, 248, 0.1)', borderRadius: '12px', overflow: 'hidden', background: 'rgba(56, 189, 248, 0.03)' }}>
                {/* Collapsible header */}
                <div
                  onClick={() => setMailerExpanded(prev => !prev)}
                  style={{ padding: '16px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', userSelect: 'none', gap: '12px' }}
                >
                  <div style={{ flexGrow: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.94rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>📬 Daily Job Match Mailer</div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '3px', lineHeight: '1.4' }}>Get daily lists matching your resume automatically.</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
                    {/* Enable toggle — stop propagation so clicking it doesn't collapse */}
                    <label
                      className="toggle-switch"
                      style={{ position: 'relative', display: 'inline-block', width: '40px', height: '22px' }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={cronEnabled}
                        onChange={(e) => {
                          const val = e.target.checked;
                          setCronEnabled(val);
                          saveSubscriptionToCloud(val, cronRole, cronLocation, cronTime, sendTailoredEmail);
                        }}
                        style={{ opacity: 0, width: 0, height: 0 }}
                      />
                      <span style={{
                        position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                        backgroundColor: cronEnabled ? 'var(--accent-primary)' : 'rgba(255,255,255,0.1)',
                        transition: '.3s', borderRadius: '34px'
                      }}>
                        <span style={{
                          position: 'absolute', height: '16px', width: '16px', left: cronEnabled ? '20px' : '3px', bottom: '3px',
                          backgroundColor: 'white', transition: '.3s', borderRadius: '50%'
                        }} />
                      </span>
                    </label>
                    {/* Chevron */}
                    <svg
                      width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                      style={{ transition: 'transform 0.2s', transform: mailerExpanded ? 'rotate(180deg)' : 'rotate(0deg)', flexShrink: 0 }}
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </div>
                </div>

                {/* Collapsible body */}
                {mailerExpanded && (
                  <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: '10px', animation: 'fadeIn 0.2s ease both', borderTop: '1px solid rgba(56,189,248,0.08)' }}>
                    <div style={{ height: '12px' }} />
                    <div>
                      <div className="section-label" style={{ fontSize: '0.74rem', marginBottom: '4px' }}>Target Job Role</div>
                      <input
                        type="text"
                        placeholder="e.g. Software Engineer (leave blank to auto-extract)"
                        value={cronRole}
                        onChange={(e) => setCronRole(e.target.value)}
                        onBlur={() => saveSubscriptionToCloud(cronEnabled, cronRole, cronLocation, cronTime)}
                        style={{ fontSize: '0.8rem', padding: '8px 12px' }}
                      />
                    </div>
                    <div>
                      <div className="section-label" style={{ fontSize: '0.74rem', marginBottom: '4px' }}>Preferred Search Location</div>
                      <input
                        type="text"
                        placeholder="e.g. Remote, Hyderabad, Bengaluru"
                        value={cronLocation}
                        onChange={(e) => setCronLocation(e.target.value)}
                        onBlur={() => saveSubscriptionToCloud(cronEnabled, cronRole, cronLocation, cronTime)}
                        style={{ fontSize: '0.8rem', padding: '8px 12px' }}
                      />
                    </div>
                    <div>
                      <div className="section-label" style={{ fontSize: '0.74rem', marginBottom: '4px' }}>
                        Daily Send Time ({cronTime}) &bull; <span style={{ color: 'var(--accent-secondary)' }}>{Intl.DateTimeFormat().resolvedOptions().timeZone} ({new Date().toLocaleTimeString('en-us', { timeZoneName: 'short' }).split(' ')[2] || 'Local'})</span>
                      </div>
                      <input
                        type="time"
                        value={cronTime}
                        onChange={(e) => {
                          const val = e.target.value;
                          setCronTime(val);
                          saveSubscriptionToCloud(cronEnabled, cronRole, cronLocation, val, sendTailoredEmail);
                        }}
                        style={{ fontSize: '0.8rem', padding: '8px 12px' }}
                      />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)', marginTop: '4px' }}>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '0.78rem', color: '#fff' }}>📧 Email Tailored PDF Resumes</div>
                        <div style={{ fontSize: '0.70rem', color: 'var(--text-muted)', marginTop: '1px' }}>Automatically email PDF attachment when tailoring via website.</div>
                      </div>
                      <label
                        className="toggle-switch"
                        style={{ position: 'relative', display: 'inline-block', width: '36px', height: '20px', flexShrink: 0 }}
                      >
                        <input
                          type="checkbox"
                          checked={sendTailoredEmail}
                          onChange={(e) => {
                            const val = e.target.checked;
                            setSendTailoredEmail(val);
                            saveSubscriptionToCloud(cronEnabled, cronRole, cronLocation, cronTime, val);
                          }}
                          style={{ opacity: 0, width: 0, height: 0 }}
                        />
                        <span style={{
                          position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                          backgroundColor: sendTailoredEmail ? 'var(--accent-primary)' : 'rgba(255,255,255,0.1)',
                          transition: '.3s', borderRadius: '34px'
                        }}>
                          <span style={{
                            position: 'absolute', height: '14px', width: '14px', left: sendTailoredEmail ? '18px' : '3px', bottom: '3px',
                            backgroundColor: 'white', transition: '.3s', borderRadius: '50%'
                          }} />
                        </span>
                      </label>
                    </div>
                    <button
                      className="btn btn-secondary"
                      style={{ padding: '8px 12px', fontSize: '0.76rem', width: '100%', marginTop: '6px', border: '1px dashed var(--accent-primary)' }}
                      onClick={async () => {
                        setLoading(true);
                        setStatusMessage('Scraping 24h job matches & sending daily digest now...');
                        try {
                          const res = await fetch(`${API_BASE}/user/test_email`, {
                            method: 'POST',
                            headers: {
                              'Content-Type': 'application/json',
                              'Authorization': `Bearer ${authToken}`
                            }
                          });
                          if (res.ok) {
                            setStatusMessage('Daily matches digest sent successfully!');
                          } else {
                            const err = await res.json();
                            setStatusMessage(`Failed to send digest: ${err.detail || 'Error'}`);
                          }
                        } catch (err) {
                          setStatusMessage(`Error sending digest: ${err.message}`);
                        } finally {
                          setLoading(false);
                        }
                      }}
                    >
                      📬 Send Daily Digest Now
                    </button>
                  </div>
                )}
              </div>

            {statusMessage && (
              <div style={{
                fontSize: '0.82rem',
                color: statusMessage.includes('❌') ? 'var(--accent-red)' : statusMessage.includes('✅') ? 'var(--accent-green)' : 'var(--accent-primary)',
                textAlign: 'center',
                padding: '4px 0 0',
                fontWeight: 600
              }}>
                {statusMessage}
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', marginTop: '12px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <button
                className="btn btn-secondary"
                style={{ padding: '12px 14px', flex: 1, fontSize: '0.88rem', borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}
                onClick={handleClearCache}
              >
                🧹 Clear Caches & Data
              </button>
              <button
                className="btn"
                style={{ padding: '12px 14px', flex: 2, fontSize: '0.88rem' }}
                onClick={() => setConfigStepActive(false)}
              >
                Continue to Dashboard →
              </button>
            </div>
          </div>
          {/* Right Panel: Standalone Master Resume ATS Evaluation & Suggestions Card */}
          {resumeData && resumeEvaluation && (
            <div className="card" style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '20px',
              padding: '32px',
              boxSizing: 'border-box'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 800, fontSize: '1.05rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span>📊 Master Resume ATS Health Score</span>
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Baseline evaluation calculated before job tailoring
                  </div>
                </div>
                <div style={{
                  padding: '6px 16px',
                  borderRadius: '20px',
                  fontWeight: 800,
                  fontSize: '1.1rem',
                  background: resumeEvaluation.ats_score >= 80 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                  color: resumeEvaluation.ats_score >= 80 ? '#10B981' : '#F59E0B',
                  border: `1px solid ${resumeEvaluation.ats_score >= 80 ? '#10B981' : '#F59E0B'}`
                }}>
                  {resumeEvaluation.ats_score}% ATS
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', textAlign: 'center', margin: '4px 0' }}>
                <div style={{ background: 'var(--panel-bg)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Found Skills</div>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--accent-secondary)' }}>{resumeEvaluation.skills_count} Core</div>
                </div>
                <div style={{ background: 'var(--panel-bg)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Quantified Bullets</div>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--accent-green)' }}>{resumeEvaluation.quantified_percentage}% ({resumeEvaluation.quantified_bullets}/{resumeEvaluation.total_bullets})</div>
                </div>
                <div style={{ background: 'var(--panel-bg)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Experience</div>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem', color: '#fff' }}>{resumeEvaluation.candidate_years} Years</div>
                </div>
              </div>

              {/* Detected Skills Chip Showcase */}
              {resumeData && resumeData.skills && resumeData.skills.length > 0 && (
                <div style={{
                  background: 'rgba(0,0,0,0.2)',
                  borderRadius: '12px',
                  padding: '14px 16px',
                  border: '1px solid rgba(255,255,255,0.06)'
                }}>
                  <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    🔍 Detected Skills Profile
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {(showAllSkills ? resumeData.skills : resumeData.skills.slice(0, 12)).map((skill, i) => {
                      const skillPalette = [
                        { bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.35)', color: '#34D399' },
                        { bg: 'rgba(56,189,248,0.12)', border: 'rgba(56,189,248,0.35)', color: '#38BDF8' },
                        { bg: 'rgba(6,182,212,0.12)', border: 'rgba(6,182,212,0.35)', color: '#22D3EE' },
                        { bg: 'rgba(139,92,246,0.12)', border: 'rgba(139,92,246,0.35)', color: '#A78BFA' },
                        { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.35)', color: '#FCD34D' },
                      ];
                      const c = skillPalette[i % skillPalette.length];
                      return (
                        <span key={i} style={{
                          padding: '4px 10px',
                          borderRadius: '20px',
                          fontSize: '0.76rem',
                          fontWeight: 600,
                          background: c.bg,
                          border: `1px solid ${c.border}`,
                          color: c.color,
                          whiteSpace: 'nowrap'
                        }}>{skill}</span>
                      );
                    })}
                    {!showAllSkills && resumeData.skills.length > 12 && (
                      <span
                        onClick={() => setShowAllSkills(true)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: '20px',
                          fontSize: '0.76rem',
                          fontWeight: 600,
                          background: 'rgba(56,189,248,0.08)',
                          border: '1px solid rgba(56,189,248,0.25)',
                          color: 'var(--accent-secondary)',
                          cursor: 'pointer',
                          whiteSpace: 'nowrap'
                        }}>+{resumeData.skills.length - 12} more ▾</span>
                    )}
                    {showAllSkills && (
                      <span
                        onClick={() => setShowAllSkills(false)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: '20px',
                          fontSize: '0.76rem',
                          fontWeight: 600,
                          background: 'rgba(255,255,255,0.05)',
                          border: '1px solid rgba(255,255,255,0.1)',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          whiteSpace: 'nowrap'
                        }}>▴ collapse</span>
                    )}
                  </div>
                </div>
              )}

              {resumeEvaluation.suggestions && resumeEvaluation.suggestions.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
                  <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                    💡 Recommended Master Playbook Enhancements:
                  </div>
                  {resumeEvaluation.suggestions.map((sug, idx) => (
                    <div key={idx} style={{
                      fontSize: '0.8rem',
                      color: 'var(--text-main)',
                      padding: '12px 14px',
                      background: 'var(--panel-bg)',
                      borderRadius: '8px',
                      borderLeft: '3px solid var(--accent-secondary)',
                      lineHeight: 1.45,
                      display: 'flex',
                      justify: 'space-between',
                      alignItems: 'center',
                      gap: '12px'
                    }}>
                      <span style={{ flexGrow: 1 }}>{sug}</span>
                      <button
                        className="btn btn-secondary"
                        disabled={loading || applyingSugIdx === idx}
                        style={{
                          padding: '5px 12px',
                          fontSize: '0.76rem',
                          fontWeight: 700,
                          color: 'var(--accent-secondary)',
                          borderColor: 'rgba(56, 189, 248, 0.3)',
                          flexShrink: 0,
                          whiteSpace: 'nowrap',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}
                        onClick={async () => {
                          let userInput = null;
                          const needsUserInput = /phone|mobile|number|email|address|contact|location|linkedin|github|quantify|metric|impact|scale|volume|financial|dollars|\$/i.test(sug);
                          if (needsUserInput) {
                            setApplyingSugIdx(idx);
                            setStatusMessage('🧠 Analyzing recommendation details...');
                            try {
                              const pRes = await fetch(`${API_BASE}/user/generate_prompt_query`, {
                                method: 'POST',
                                headers: {
                                  'Content-Type': 'application/json',
                                  'Authorization': `Bearer ${getAuthHeader()}`
                                },
                                body: JSON.stringify({ suggestion: sug })
                              });
                              const pData = await pRes.json();
                              const promptText = pData.prompt_text || `This recommendation requests additional metrics or details:\n\n"${sug}"\n\nPlease enter the requested detail:`;
                              userInput = window.prompt(promptText);
                              if (userInput === null) {
                                setApplyingSugIdx(null);
                                setStatusMessage('');
                                return; // User cancelled prompt
                              }
                            } catch (pErr) {
                              userInput = window.prompt(`Please enter details for this recommendation:\n\n"${sug}"`);
                              if (userInput === null) {
                                setApplyingSugIdx(null);
                                setStatusMessage('');
                                return;
                              }
                            }
                          } else {
                            if (!window.confirm(`Incorporate this enhancement into your master resume?\n\n"${sug}"`)) return;
                          }

                          setPreviousResumeData(resumeData);
                          setApplyingSugIdx(idx);
                          setStatusMessage('⏳ Incorporating AI enhancement into master profile...');
                          try {
                            const res = await fetch(`${API_BASE}/user/apply_suggestion`, {
                              method: 'POST',
                              headers: {
                                'Content-Type': 'application/json',
                                'Authorization': `Bearer ${getAuthHeader()}`
                              },
                              body: JSON.stringify({ suggestion: sug, user_input: userInput })
                            });
                            if (res.ok) {
                              const body = await res.json();
                              setResumeData(body.data);
                              const remainingSugs = (resumeEvaluation.suggestions || [])
                                .filter(s => s.trim().toLowerCase() !== sug.trim().toLowerCase());
                              const updatedEvaluation = {
                                ...body.evaluation,
                                suggestions: remainingSugs
                              };
                              setResumeEvaluation(updatedEvaluation);
                              setReviewedResumeData(body.data);
                              setReviewedLatex(body.latex || '');
                              setBeforePdfUrl(body.before_pdf_url ? `${API_BASE}${body.before_pdf_url}` : null);
                              setAfterPdfUrl(body.after_pdf_url ? `${API_BASE}${body.after_pdf_url}` : null);
                              setReviewModalTab(body.after_pdf_url ? 'pdf' : 'diff');
                              setShowReviewModal(true);
                              setStatusMessage('✨ Master resume profile updated successfully!');
                            } else {
                              throw new Error('Failed to update resume');
                            }
                          } catch (err) {
                            setStatusMessage(`❌ Error applying suggestion: ${err.message}`);
                          } finally {
                            setApplyingSugIdx(null);
                          }
                        }}
                      >
                        {applyingSugIdx === idx ? '⏳ Applying…' : '✨ Auto-Apply'}
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{
                  background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(56, 189, 248, 0.08) 100%)',
                  padding: '32px 28px',
                  borderRadius: '16px',
                  border: '1px solid rgba(16, 185, 129, 0.35)',
                  marginTop: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '28px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '18px' }}>
                    <div style={{
                      width: '62px', height: '62px', borderRadius: '50%',
                      background: 'rgba(16, 185, 129, 0.22)', border: '2px solid #10B981',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '2rem', flexShrink: 0, boxShadow: '0 0 24px rgba(16, 185, 129, 0.25)'
                    }}>
                      🏆
                    </div>
                    <div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#34D399', letterSpacing: '-0.01em' }}>
                        Master Playbook Optimization Complete!
                      </div>
                      <div style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '6px', lineHeight: 1.55 }}>
                        Your baseline profile satisfies all elite ATS score criteria, metric density guidelines, and skill taxonomy rules.
                      </div>
                    </div>
                  </div>

                  {/* Circular Achievement Trophy Badges */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px' }}>
                    <div style={{
                      background: 'rgba(0,0,0,0.35)', padding: '26px 14px', borderRadius: '14px',
                      border: '1px solid rgba(16, 185, 129, 0.3)', textAlign: 'center',
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px'
                    }}>
                      <div style={{
                        width: '54px', height: '54px', borderRadius: '50%',
                        background: 'rgba(16, 185, 129, 0.2)', border: '2px solid #10B981',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.4rem'
                      }}>
                        🎯
                      </div>
                      <div>
                        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>ATS Rating</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#34D399', marginTop: '4px' }}>{resumeEvaluation.ats_score}% Elite</div>
                      </div>
                    </div>

                    <div style={{
                      background: 'rgba(0,0,0,0.35)', padding: '26px 14px', borderRadius: '14px',
                      border: '1px solid rgba(56, 189, 248, 0.3)', textAlign: 'center',
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px'
                    }}>
                      <div style={{
                        width: '54px', height: '54px', borderRadius: '50%',
                        background: 'rgba(56, 189, 248, 0.2)', border: '2px solid var(--accent-secondary)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.4rem'
                      }}>
                        ⚡
                      </div>
                      <div>
                        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Core Skills</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'var(--accent-secondary)', marginTop: '4px' }}>{resumeEvaluation.skills_count} Verified</div>
                      </div>
                    </div>

                    <div style={{
                      background: 'rgba(0,0,0,0.35)', padding: '26px 14px', borderRadius: '14px',
                      border: '1px solid rgba(6, 182, 212, 0.3)', textAlign: 'center',
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px'
                    }}>
                      <div style={{
                        width: '54px', height: '54px', borderRadius: '50%',
                        background: 'rgba(6, 182, 212, 0.2)', border: '2px solid var(--accent-cyan)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.4rem'
                      }}>
                        📊
                      </div>
                      <div>
                        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Metrics Density</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'var(--accent-cyan)', marginTop: '4px' }}>{resumeEvaluation.quantified_percentage}% ({resumeEvaluation.quantified_bullets}/{resumeEvaluation.total_bullets})</div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
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
              {user && user.picture_url ? (
                <img
                  src={user.picture_url}
                  alt="Profile"
                  className="profile-avatar"
                  style={{
                    width: '38px',
                    height: '38px',
                    borderRadius: '50%',
                    objectFit: 'cover',
                    border: '1.5px solid var(--accent-green)',
                    marginRight: '2px'
                  }}
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="profile-avatar">👤</div>
              )}
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

            {/* Mode Switcher 2x2 Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', borderRadius: '10px', background: 'rgba(255,255,255,0.03)', padding: '6px', border: '1px solid rgba(255,255,255,0.05)', marginTop: '4px' }}>
              <button
                className={`mode-btn ${dashboardMode === 'master' ? 'active' : ''}`}
                style={{
                  padding: '10px 12px',
                  fontSize: '0.84rem',
                  borderRadius: '8px',
                  fontWeight: 700,
                  border: '1px solid ' + (dashboardMode === 'master' ? 'var(--accent-primary)' : 'rgba(255,255,255,0.08)'),
                  background: dashboardMode === 'master' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                  color: dashboardMode === 'master' ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px'
                }}
                onClick={() => {
                  setDashboardMode('master');
                  setIsDiscoveryView(false);
                }}
              >
                📊 Master Profile
              </button>
              <button
                className={`mode-btn ${dashboardMode === 'tailor' ? 'active' : ''}`}
                style={{
                  padding: '10px 12px',
                  fontSize: '0.84rem',
                  borderRadius: '8px',
                  fontWeight: 700,
                  border: '1px solid ' + (dashboardMode === 'tailor' ? 'var(--accent-primary)' : 'rgba(255,255,255,0.08)'),
                  background: dashboardMode === 'tailor' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                  color: dashboardMode === 'tailor' ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px'
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
                  padding: '10px 12px',
                  fontSize: '0.84rem',
                  borderRadius: '8px',
                  fontWeight: 700,
                  border: '1px solid ' + (dashboardMode === 'discover' ? 'var(--accent-primary)' : 'rgba(255,255,255,0.08)'),
                  background: dashboardMode === 'discover' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                  color: dashboardMode === 'discover' ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px'
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
                  padding: '10px 12px',
                  fontSize: '0.84rem',
                  borderRadius: '8px',
                  fontWeight: 700,
                  border: '1px solid ' + (dashboardMode === 'history' ? 'var(--accent-primary)' : 'rgba(255,255,255,0.08)'),
                  background: dashboardMode === 'history' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                  color: dashboardMode === 'history' ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px'
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

            {/* Mobile Bottom Sticky Navigation Bar */}
            <div className="mobile-bottom-nav" style={{
              display: 'none',
              position: 'fixed',
              bottom: 0,
              left: 0,
              right: 0,
              height: '62px',
              backgroundColor: '#0b0f19',
              borderTop: '1px solid rgba(255,255,255,0.1)',
              zIndex: 9999,
              justifyContent: 'space-around',
              alignItems: 'center',
              padding: '0 8px',
              backdropFilter: 'blur(16px)',
              boxShadow: '0 -4px 20px rgba(0,0,0,0.5)'
            }}>
              <button
                onClick={() => { setDashboardMode('tailor'); setIsDiscoveryView(false); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'tailor' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px', fontSize: '0.72rem', fontWeight: 600
                }}
              >
                <span style={{ fontSize: '1.2rem' }}>🎯</span>
                Tailor
              </button>
              <button
                onClick={() => { setDashboardMode('discover'); setIsDiscoveryView(true); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'discover' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px', fontSize: '0.72rem', fontWeight: 600
                }}
              >
                <span style={{ fontSize: '1.2rem' }}>🔍</span>
                Discover
              </button>
              <button
                onClick={() => { setDashboardMode('history'); setIsDiscoveryView(false); handleFetchHistory(); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'history' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px', fontSize: '0.72rem', fontWeight: 600
                }}
              >
                <span style={{ fontSize: '1.2rem' }}>📂</span>
                History
              </button>
              <button
                onClick={() => { setDashboardMode('docs'); setIsDiscoveryView(false); window.history.pushState(null, '', '/docs'); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'docs' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px', fontSize: '0.72rem', fontWeight: 600
                }}
              >
                <span style={{ fontSize: '1.2rem' }}>📖</span>
                Docs
              </button>
            </div>
            <style>{`
              @media (max-width: 768px) {
                .mobile-bottom-nav { display: flex !important; }
              }
            `}</style>

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
                  urlScraping={urlScraping}
                  urlScrapeError={urlScrapeError}
                  handleUrlBlur={handleUrlBlur}
                  handleAnalyzeJob={handleAnalyzeJob}
                  handleGenerateTailoredResume={handleGenerateTailoredResume}
                  onGenerateOutreach={handleGenerateOutreach}
                  tailoringIntensity={tailoringIntensity}
                  setTailoringIntensity={setTailoringIntensity}
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
                  onCopyToClipboard={() => { }}
                  anchorTop={outreachAnchorTop}
                />
              </Suspense>
            )}


            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            {dashboardMode === 'master' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {/* Multi-Archetype Switcher Card */}
                <div style={{
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '12px',
                  padding: '16px 18px',
                  background: 'rgba(255, 255, 255, 0.02)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontWeight: 800, fontSize: '0.98rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span>👥 Master Profile Archetypes</span>
                      </div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                        Save and toggle distinct base profiles (e.g. GenAI vs. Data Science vs. Backend SWE)
                      </div>
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--accent-secondary)', fontWeight: 700 }}>
                      Active: {activeArchetype}
                    </div>
                  </div>

                  {/* Archetype Chips */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                    {userArchetypes.map((arch) => (
                      <button
                        key={arch.name}
                        type="button"
                        disabled={archetypeLoading}
                        onClick={() => handleSwitchArchetype(arch.name)}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '8px',
                          fontSize: '0.78rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          border: arch.name === activeArchetype ? '1px solid var(--accent-primary)' : '1px solid rgba(255,255,255,0.1)',
                          background: arch.name === activeArchetype ? 'rgba(56, 189, 248, 0.2)' : 'rgba(0,0,0,0.3)',
                          color: arch.name === activeArchetype ? '#38bdf8' : 'var(--text-muted)',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        <span>{arch.name === activeArchetype ? '✓' : '•'}</span>
                        <span>{arch.name}</span>
                        {arch.skills_count ? <span style={{ opacity: 0.6, fontSize: '0.7rem' }}>({arch.skills_count} skills)</span> : null}
                      </button>
                    ))}
                  </div>

                  {/* Save current state as new Archetype */}
                  <div style={{ display: 'flex', gap: '8px', marginTop: '2px' }}>
                    <input
                      type="text"
                      placeholder="New Archetype Name (e.g. Staff GenAI Engineer)"
                      value={newArchetypeName}
                      onChange={(e) => setNewArchetypeName(e.target.value)}
                      style={{ flex: 1, padding: '7px 12px', fontSize: '0.8rem', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#fff' }}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleSaveArchetype(); }}
                    />
                    <button
                      className="btn btn-secondary"
                      disabled={archetypeLoading || !newArchetypeName.trim()}
                      onClick={handleSaveArchetype}
                      style={{ padding: '7px 14px', fontSize: '0.78rem', fontWeight: 700, whiteSpace: 'nowrap' }}
                    >
                      {archetypeLoading ? '⏳ Saving...' : '💾 Save as Archetype'}
                    </button>
                  </div>
                </div>

                {/* Standalone Master Resume ATS Evaluation & Suggestions Card */}
                {resumeData && resumeEvaluation && (
                  <div style={{
                    border: '1px solid rgba(56, 189, 248, 0.25)',
                    borderRadius: '12px',
                    padding: '20px',
                    background: 'rgba(56, 189, 248, 0.04)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '14px'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontWeight: 800, fontSize: '1.05rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span>📊 Master Resume ATS Health Score</span>
                        </div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                          Baseline evaluation calculated before job tailoring
                        </div>
                      </div>
                      <div style={{
                        padding: '6px 16px',
                        borderRadius: '20px',
                        fontWeight: 800,
                        fontSize: '1.1rem',
                        background: resumeEvaluation.ats_score >= 80 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                        color: resumeEvaluation.ats_score >= 80 ? '#10B981' : '#F59E0B',
                        border: `1px solid ${resumeEvaluation.ats_score >= 80 ? '#10B981' : '#F59E0B'}`
                      }}>
                        {resumeEvaluation.ats_score}% ATS
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', textAlign: 'center', margin: '4px 0' }}>
                      <div style={{ background: 'var(--panel-bg)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Found Skills</div>
                        <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--accent-secondary)' }}>{resumeEvaluation.skills_count} Core</div>
                      </div>
                      <div style={{ background: 'var(--panel-bg)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Quantified Bullets</div>
                        <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--accent-green)' }}>{resumeEvaluation.quantified_percentage}% ({resumeEvaluation.quantified_bullets}/{resumeEvaluation.total_bullets})</div>
                      </div>
                      <div style={{ background: 'var(--panel-bg)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Experience</div>
                        <div style={{ fontWeight: 700, fontSize: '1.05rem', color: '#fff' }}>{resumeEvaluation.candidate_years} Years</div>
                      </div>
                    </div>

                    {resumeEvaluation.suggestions && resumeEvaluation.suggestions.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
                        <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                          💡 Recommended Master Playbook Enhancements:
                        </div>
                        {resumeEvaluation.suggestions.map((sug, idx) => (
                          <div key={idx} style={{
                            fontSize: '0.8rem',
                            color: 'var(--text-main)',
                            padding: '12px 14px',
                            background: 'var(--panel-bg)',
                            borderRadius: '8px',
                            borderLeft: '3px solid var(--accent-secondary)',
                            lineHeight: 1.45,
                            display: 'flex',
                            justify: 'space-between',
                            alignItems: 'center',
                            gap: '12px'
                          }}>
                            <span style={{ flexGrow: 1 }}>{sug}</span>
                            <button
                              className="btn btn-secondary"
                              disabled={loading || applyingSugIdx === idx}
                              style={{
                                padding: '5px 12px',
                                fontSize: '0.76rem',
                                fontWeight: 700,
                                color: 'var(--accent-secondary)',
                                borderColor: 'rgba(56, 189, 248, 0.3)',
                                flexShrink: 0,
                                whiteSpace: 'nowrap',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px'
                              }}
                              onClick={async () => {
                                let userInput = null;
                                const needsUserInput = /phone|mobile|number|email|address|contact|location|linkedin|github|quantify|metric|impact|scale|volume|financial|dollars|\$/i.test(sug);
                                if (needsUserInput) {
                                  setApplyingSugIdx(idx);
                                  setStatusMessage('🧠 Analyzing recommendation details...');
                                  try {
                                    const pRes = await fetch(`${API_BASE}/user/generate_prompt_query`, {
                                      method: 'POST',
                                      headers: {
                                        'Content-Type': 'application/json',
                                        'Authorization': `Bearer ${getAuthHeader()}`
                                      },
                                      body: JSON.stringify({ suggestion: sug })
                                    });
                                    const pData = await pRes.json();
                                    const promptText = pData.prompt_text || `This recommendation requests additional metrics or details:\n\n"${sug}"\n\nPlease enter the requested detail:`;
                                    userInput = window.prompt(promptText);
                                    if (userInput === null) {
                                      setApplyingSugIdx(null);
                                      setStatusMessage('');
                                      return; // User cancelled prompt
                                    }
                                  } catch (pErr) {
                                    userInput = window.prompt(`Please enter details for this recommendation:\n\n"${sug}"`);
                                    if (userInput === null) {
                                      setApplyingSugIdx(null);
                                      setStatusMessage('');
                                      return;
                                    }
                                  }
                                } else {
                                  if (!window.confirm(`Incorporate this enhancement into your master resume?\n\n"${sug}"`)) return;
                                }

                                setPreviousResumeData(resumeData);
                                setApplyingSugIdx(idx);
                                setStatusMessage('⏳ Incorporating AI enhancement into master profile...');
                                try {
                                  const res = await fetch(`${API_BASE}/user/apply_suggestion`, {
                                    method: 'POST',
                                    headers: {
                                      'Content-Type': 'application/json',
                                      'Authorization': `Bearer ${getAuthHeader()}`
                                    },
                                    body: JSON.stringify({ suggestion: sug, user_input: userInput })
                                  });
                                  if (res.ok) {
                                    const body = await res.json();
                                    setResumeData(body.data);
                                    setReviewedResumeData(body.data);
                                    setReviewedLatex(body.latex || '');
                                    setBeforePdfUrl(body.before_pdf_url ? `${API_BASE}${body.before_pdf_url}` : null);
                                    setAfterPdfUrl(body.after_pdf_url ? `${API_BASE}${body.after_pdf_url}` : null);
                                    setReviewModalTab(body.after_pdf_url ? 'pdf' : 'diff');
                                    const remainingSugs = (resumeEvaluation.suggestions || [])
                                      .filter(s => s.trim().toLowerCase() !== sug.trim().toLowerCase());
                                    const updatedEvaluation = {
                                      ...body.evaluation,
                                      suggestions: remainingSugs
                                    };
                                    setResumeEvaluation(updatedEvaluation);
                                    setShowReviewModal(true);
                                    setStatusMessage('✨ Master resume profile updated successfully!');
                                  } else {
                                    throw new Error('Failed to update resume');
                                  }
                                } catch (err) {
                                  setStatusMessage(`❌ Error applying suggestion: ${err.message}`);
                                } finally {
                                  setApplyingSugIdx(null);
                                }
                              }}
                            >
                              {applyingSugIdx === idx ? '⏳ Applying…' : '✨ Auto-Apply'}
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div style={{
                        background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(56, 189, 248, 0.08) 100%)',
                        padding: '18px 20px',
                        borderRadius: '12px',
                        border: '1px solid rgba(16, 185, 129, 0.3)',
                        marginTop: '10px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '1.4rem' }}>🏆</span>
                          <div>
                            <div style={{ fontSize: '0.9rem', fontWeight: 800, color: '#34D399' }}>
                              Master Playbook Optimization Complete!
                            </div>
                            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                              Your baseline profile satisfies all elite ATS score criteria, metric density guidelines, and skill taxonomy rules.
                            </div>
                          </div>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginTop: '4px' }}>
                          <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px 12px', borderRadius: '8px', borderLeft: '3px solid #10B981' }}>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>ATS Score</div>
                            <div style={{ fontSize: '0.86rem', fontWeight: 700, color: '#34D399' }}>Elite Grade ({resumeEvaluation.ats_score}%)</div>
                          </div>
                          <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px 12px', borderRadius: '8px', borderLeft: '3px solid var(--accent-secondary)' }}>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Core Skills</div>
                            <div style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--accent-secondary)' }}>{resumeEvaluation.skills_count} Verified</div>
                          </div>
                          <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px 12px', borderRadius: '8px', borderLeft: '3px solid var(--accent-cyan)' }}>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Quantified Bullets</div>
                            <div style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--accent-cyan)' }}>{resumeEvaluation.quantified_percentage}% ({resumeEvaluation.quantified_bullets}/{resumeEvaluation.total_bullets})</div>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span>🚀 Ready for instant 1-click tailoring against active job descriptions.</span>
                          </div>
                          <button
                            className="btn btn-primary"
                            style={{ padding: '8px 18px', fontSize: '0.82rem', fontWeight: 700 }}
                            onClick={() => setConfigStepActive(false)}
                          >
                            Start Tailoring Jobs →
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Render Full Master Resume Details in Dashboard */}
                {resumeData && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '6px' }}>
                    {resumeData.summary && (
                      <div style={{ background: 'var(--panel-bg)', padding: '14px', borderRadius: '10px', borderLeft: '3px solid var(--accent-cyan)' }}>
                        <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-cyan)', marginBottom: '4px' }}>PROFESSIONAL SUMMARY</div>
                        <div style={{ fontSize: '0.84rem', color: 'var(--text-main)', fontStyle: 'italic', lineHeight: 1.55 }}>
                          {resumeData.summary}
                        </div>
                      </div>
                    )}

                    {resumeData.skills && (
                      <div style={{ background: 'var(--panel-bg)', padding: '14px', borderRadius: '10px', borderLeft: '3px solid var(--accent-secondary)' }}>
                        <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-secondary)', marginBottom: '8px' }}>SKILLS & FRAMEWORKS</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                          {(
                            Array.isArray(resumeData.skills)
                              ? resumeData.skills
                              : typeof resumeData.skills === 'object'
                              ? Object.entries(resumeData.skills).flatMap(([cat, list]) =>
                                  Array.isArray(list) ? list.map(item => `${cat}: ${item}`) : [`${cat}: ${list}`]
                                )
                              : [String(resumeData.skills)]
                          ).map((s, i) => (
                            <span key={i} style={{ padding: '4px 9px', borderRadius: '4px', background: 'rgba(56, 189, 248, 0.1)', color: 'var(--accent-secondary)', fontSize: '0.76rem', fontWeight: 600 }}>
                              {s}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {resumeData.experience && resumeData.experience.length > 0 && (
                      <div style={{ background: 'var(--panel-bg)', padding: '14px', borderRadius: '10px', borderLeft: '3px solid var(--accent-green)' }}>
                        <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-green)', marginBottom: '10px' }}>WORK EXPERIENCE</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                          {resumeData.experience.map((exp, i) => (
                            <div key={i} style={{ fontSize: '0.82rem' }}>
                              <div style={{ fontWeight: 700, color: '#fff' }}>{exp.role} <span style={{ color: 'var(--text-muted)' }}>@ {exp.company}</span></div>
                              <ul style={{ margin: '4px 0 0 18px', padding: 0, color: 'var(--text-main)', fontSize: '0.8rem', lineHeight: 1.45 }}>
                                {(exp.description || []).map((b, bi) => (
                                  <li key={bi}>{b}</li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : dashboardMode === 'history' ? (
              historyLoading ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                  <svg style={{ animation: 'spin 1s linear infinite', width: '18px', height: '18px', flexShrink: 0 }} viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" style={{ opacity: 0.25 }} />
                    <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Loading history…</span>
                </div>
              ) : applicationHistory.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon">🕘</div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: '6px' }}>No history yet</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem', maxWidth: '340px', margin: '0 auto' }}>Tailor a resume or apply to a job to see it recorded here.</div>
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', maxHeight: '560px', overflowY: 'auto', paddingRight: '4px' }}>
                  {/* Funnel Metrics Dashboard Card */}
                  {(() => {
                    const tailoredCount = applicationHistory.filter(e => e.status === 'tailored').length;
                    const appliedCount = applicationHistory.filter(e => e.status === 'applied').length;
                    const total = applicationHistory.length || 1;

                    const tailoredPct = Math.round((tailoredCount / total) * 100);
                    const appliedPct = Math.round((appliedCount / total) * 100);

                    return (
                      <div className="card" style={{ padding: '14px', background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.5), rgba(15, 23, 42, 0.8))', border: '1px solid rgba(56, 189, 248, 0.15)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-primary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>📊 Application Pipeline Funnel</div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem', marginBottom: '3px' }}>
                              <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>🎯 Resumes Tailored</span>
                              <span style={{ color: '#fff', fontWeight: 700 }}>{tailoredCount} ({tailoredPct}%)</span>
                            </div>
                            <div style={{ height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '999px', overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${tailoredPct}%`, background: 'var(--accent-cyan)', borderRadius: '999px' }} />
                            </div>
                          </div>

                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem', marginBottom: '3px' }}>
                              <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>✅ Submitted / Applied</span>
                              <span style={{ color: '#fff', fontWeight: 700 }}>{appliedCount} ({appliedPct}%)</span>
                            </div>
                            <div style={{ height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '999px', overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${appliedPct}%`, background: 'var(--accent-green)', borderRadius: '999px' }} />
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })()}

                  {/* Filter / Sort Control Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0 2px', flexWrap: 'wrap', gap: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Filter:</span>
                      <button
                        onClick={() => setHistoryFilter('all')}
                        style={{
                          fontSize: '0.68rem', padding: '3px 9px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                          background: historyFilter === 'all' ? 'var(--accent-primary)' : 'rgba(255,255,255,0.05)',
                          color: historyFilter === 'all' ? '#fff' : 'var(--text-muted)',
                          border: historyFilter === 'all' ? '1px solid var(--accent-primary)' : '1px solid rgba(255,255,255,0.1)'
                        }}
                      >
                        All ({applicationHistory.length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('tailored')}
                        style={{
                          fontSize: '0.68rem', padding: '3px 9px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                          background: historyFilter === 'tailored' ? '#7dd3fc22' : 'rgba(255,255,255,0.05)',
                          color: historyFilter === 'tailored' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                          border: historyFilter === 'tailored' ? '1px solid var(--accent-cyan)' : '1px solid rgba(255,255,255,0.1)'
                        }}
                      >
                        🎯 Tailored ({applicationHistory.filter(e => e.status !== 'applied').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('applied')}
                        style={{
                          fontSize: '0.68rem', padding: '3px 9px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                          background: historyFilter === 'applied' ? '#10B98122' : 'rgba(255,255,255,0.05)',
                          color: historyFilter === 'applied' ? 'var(--accent-green)' : 'var(--text-muted)',
                          border: historyFilter === 'applied' ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.1)'
                        }}
                      >
                        ✅ Submitted ({applicationHistory.filter(e => e.status === 'applied').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('extension')}
                        style={{
                          fontSize: '0.68rem', padding: '3px 9px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                          background: historyFilter === 'extension' ? 'rgba(168,85,247,0.2)' : 'rgba(255,255,255,0.05)',
                          color: historyFilter === 'extension' ? '#c084fc' : 'var(--text-muted)',
                          border: historyFilter === 'extension' ? '1px solid #c084fc' : '1px solid rgba(255,255,255,0.1)'
                        }}
                      >
                        🧩 Extension Mode ({applicationHistory.filter(e => e.source_mode === 'extension').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('website')}
                        style={{
                          fontSize: '0.68rem', padding: '3px 9px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                          background: historyFilter === 'website' ? 'rgba(245,158,11,0.2)' : 'rgba(255,255,255,0.05)',
                          color: historyFilter === 'website' ? '#fbbf24' : 'var(--text-muted)',
                          border: historyFilter === 'website' ? '1px solid #fbbf24' : '1px solid rgba(255,255,255,0.1)'
                        }}
                      >
                        💻 Website Mode ({applicationHistory.filter(e => e.source_mode !== 'extension' && e.source_mode !== 'email').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('email')}
                        style={{
                          fontSize: '0.68rem', padding: '3px 9px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                          background: historyFilter === 'email' ? 'rgba(236,72,153,0.2)' : 'rgba(255,255,255,0.05)',
                          color: historyFilter === 'email' ? '#f472b6' : 'var(--text-muted)',
                          border: historyFilter === 'email' ? '1px solid #f472b6' : '1px solid rgba(255,255,255,0.1)'
                        }}
                      >
                        📧 Email Mode ({applicationHistory.filter(e => e.source_mode === 'email').length})
                      </button>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Min Score %:</span>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          placeholder="e.g. 70"
                          value={minHistoryScore === 0 ? '' : minHistoryScore}
                          onChange={(e) => {
                            const val = e.target.value === '' ? 0 : Math.max(0, Math.min(100, Number(e.target.value)));
                            setMinHistoryScore(val);
                          }}
                          style={{
                            width: '58px',
                            fontSize: '0.72rem',
                            padding: '2px 6px',
                            borderRadius: '6px',
                            background: '#0F172A',
                            color: minHistoryScore > 0 ? 'var(--accent-cyan)' : 'var(--text-muted)',
                            border: minHistoryScore > 0 ? '1px solid var(--accent-cyan)' : '1px solid rgba(255,255,255,0.15)',
                            textAlign: 'center',
                            fontWeight: 700,
                            outline: 'none'
                          }}
                        />
                        {minHistoryScore > 0 && (
                          <button
                            onClick={() => setMinHistoryScore(0)}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-muted)',
                              fontSize: '0.75rem',
                              cursor: 'pointer',
                              padding: '0 2px'
                            }}
                            title="Clear score filter"
                          >
                            ✕
                          </button>
                        )}
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Sort Date:</span>
                        <select
                          value={historySortOrder}
                          onChange={(e) => setHistorySortOrder(e.target.value)}
                          style={{
                            fontSize: '0.68rem', padding: '3px 8px', borderRadius: '6px', cursor: 'pointer', fontWeight: 700,
                            background: '#0F172A', color: 'var(--accent-secondary)', border: '1px solid rgba(56, 189, 248, 0.3)', outline: 'none'
                          }}
                        >
                          <option value="newest">📅 Newest First</option>
                          <option value="oldest">📅 Oldest First</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {applicationHistory
                      .filter(entry => {
                        if (historyFilter === 'tailored' && entry.status === 'applied') return false;
                        if (historyFilter === 'applied' && entry.status !== 'applied') return false;
                        if (historyFilter === 'extension' && entry.source_mode !== 'extension') return false;
                        if (historyFilter === 'website' && (entry.source_mode === 'extension' || entry.source_mode === 'email')) return false;
                        if (historyFilter === 'email' && entry.source_mode !== 'email') return false;
                        if (minHistoryScore > 0) {
                          const itemScore = typeof entry.score === 'number' ? entry.score : 0;
                          if (itemScore < minHistoryScore) return false;
                        }
                        return true;
                      })
                      .sort((a, b) => {
                        const tsA = a.timestamp || 0;
                        const tsB = b.timestamp || 0;
                        return historySortOrder === 'newest' ? tsB - tsA : tsA - tsB;
                      })
                      .map((entry, idx) => {
                        const statusColor = entry.status === 'applied' ? 'var(--accent-green)' : 'var(--accent-cyan)';
                        const date = entry.timestamp ? new Date(entry.timestamp * 1000).toLocaleString() : '';

                        // Determine platform source from job_url
                        let platformBadge = null;
                        const urlLower = (entry.job_url || '').toLowerCase();
                        if (urlLower.includes('linkedin.com')) {
                          platformBadge = { name: 'LinkedIn', color: '#0A66C2', icon: '💼' };
                        } else if (urlLower.includes('indeed.com')) {
                          platformBadge = { name: 'Indeed', color: '#2557A7', icon: '🔍' };
                        } else if (urlLower.includes('glassdoor.com')) {
                          platformBadge = { name: 'Glassdoor', color: '#00A264', icon: '🏢' };
                        } else if (urlLower.includes('ziprecruiter.com')) {
                          platformBadge = { name: 'ZipRecruiter', color: '#5B2C6F', icon: '⚡' };
                        } else if (entry.job_url) {
                          platformBadge = { name: 'Direct Web', color: '#64748B', icon: '🌐' };
                        }

                        return (
                          <div key={idx} className="card" style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                  <div style={{ fontWeight: 700, fontSize: '0.92rem', color: '#fff' }}>{entry.job_title || 'Untitled Role'}</div>
                                  {platformBadge && (
                                    <span style={{
                                      fontSize: '0.66rem', fontWeight: 700, padding: '2px 7px', borderRadius: '4px',
                                      backgroundColor: `${platformBadge.color}22`, color: platformBadge.color,
                                      border: `1px solid ${platformBadge.color}44`, display: 'inline-flex', alignItems: 'center', gap: '3px'
                                    }}>
                                      <span>{platformBadge.icon}</span> {platformBadge.name}
                                    </span>
                                  )}
                                  <span style={{
                                    fontSize: '0.66rem', fontWeight: 700, padding: '2px 7px', borderRadius: '4px',
                                    backgroundColor: entry.source_mode === 'extension' ? 'rgba(168,85,247,0.15)' : entry.source_mode === 'email' ? 'rgba(236,72,153,0.15)' : 'rgba(245,158,11,0.15)',
                                    color: entry.source_mode === 'extension' ? '#c084fc' : entry.source_mode === 'email' ? '#f472b6' : '#fbbf24',
                                    border: entry.source_mode === 'extension' ? '1px solid rgba(168,85,247,0.3)' : entry.source_mode === 'email' ? '1px solid rgba(236,72,153,0.3)' : '1px solid rgba(245,158,11,0.3)'
                                  }}>
                                    {entry.source_mode === 'extension' ? '🧩 Extension' : entry.source_mode === 'email' ? '📧 Email' : '💻 Website'}
                                  </span>
                                </div>
                                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>{entry.company || 'Unknown Company'}</div>
                                {entry.recruiter_name && (
                                  <div style={{ fontSize: '0.75rem', color: 'var(--accent-secondary)', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '5px' }}>
                                    <span>👤 Recruiter:</span>
                                    {entry.recruiter_profile_url ? (
                                      <a href={entry.recruiter_profile_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-secondary)', fontWeight: 600, textDecoration: 'underline' }}>
                                        {entry.recruiter_name}
                                      </a>
                                    ) : (
                                      <span style={{ fontWeight: 600 }}>{entry.recruiter_name}</span>
                                    )}
                                  </div>
                                )}
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '4px' }}>{date}</div>
                              </div>
                              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px', flexShrink: 0 }}>
                                <select
                                  value={entry.status === 'applied' ? 'applied' : 'tailored'}
                                  onChange={async (e) => {
                                    const newStatus = e.target.value;
                                    // Update local UI immediately
                                    setApplicationHistory(prev => prev.map(item => item.job_url === entry.job_url ? { ...item, status: newStatus } : item));
                                    try {
                                      await fetch(`${API_BASE}/update_application_status`, {
                                        method: 'POST',
                                        headers: {
                                          'Content-Type': 'application/json',
                                          'Authorization': `Bearer ${getAuthHeader()}`
                                        },
                                        body: JSON.stringify({
                                          job_url: entry.job_url || '',
                                          status: newStatus
                                        })
                                      });
                                    } catch (err) {
                                      console.error('Failed to update status', err);
                                    }
                                  }}
                                  style={{
                                    fontSize: '0.68rem', padding: '2px 6px', borderRadius: '6px',
                                    background: `${statusColor}22`, color: statusColor, fontWeight: 700,
                                    border: `1px solid ${statusColor}44`, cursor: 'pointer', outline: 'none'
                                  }}
                                >
                                  <option value="tailored" style={{ background: '#0F172A', color: 'var(--accent-cyan)' }}>Tailored</option>
                                  <option value="applied" style={{ background: '#0F172A', color: 'var(--accent-green)' }}>Applied</option>
                                </select>
                                {typeof entry.score === 'number' && (
                                  <span style={{ fontSize: '0.76rem', fontWeight: 700, color: '#fff' }}>{entry.score}% match</span>
                                )}
                                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                                  {entry.overleaf_url ? (
                                    <a
                                      href={entry.overleaf_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="btn-overleaf"
                                      style={{
                                        fontSize: '0.72rem',
                                        padding: '5px 11px',
                                        borderRadius: '6px',
                                        fontWeight: 600,
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '5px',
                                        textDecoration: 'none',
                                        boxShadow: '0 2px 8px rgba(16, 185, 129, 0.25)'
                                      }}
                                    >
                                      🍃 Overleaf
                                    </a>
                                  ) : (
                                    <button
                                      className="btn-overleaf"
                                      style={{ fontSize: '0.72rem', padding: '5px 11px', borderRadius: '6px', opacity: 0.9, fontWeight: 600 }}
                                      onClick={() => handleGenerateTailoredResume(false, entry.job_url, entry.job_title)}
                                    >
                                      🍃 Overleaf
                                    </button>
                                  )}
                                  {entry.job_url && (
                                    <a
                                      href={entry.job_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        fontSize: '0.72rem',
                                        padding: '5px 11px',
                                        borderRadius: '6px',
                                        fontWeight: 600,
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                        textDecoration: 'none',
                                        background: 'rgba(255, 255, 255, 0.05)',
                                        color: '#e2e8f0',
                                        border: '1px solid rgba(255, 255, 255, 0.12)'
                                      }}
                                      title="Open original job posting"
                                    >
                                      🔗 Job Link
                                    </a>
                                  )}
                                   {entry.pdf_url ? (
                                     <a
                                       href={API_BASE + entry.pdf_url}
                                       target="_blank"
                                       rel="noreferrer"
                                       style={{
                                         fontSize: '0.72rem',
                                         padding: '5px 11px',
                                         borderRadius: '6px',
                                         fontWeight: 700,
                                         display: 'inline-flex',
                                         alignItems: 'center',
                                         gap: '5px',
                                         textDecoration: 'none',
                                         background: 'rgba(56, 189, 248, 0.15)',
                                         color: 'var(--accent-secondary)',
                                         border: '1px solid rgba(56, 189, 248, 0.35)',
                                         boxShadow: '0 2px 8px rgba(56, 189, 248, 0.2)'
                                       }}
                                       title="View & Download compiled PDF resume"
                                     >
                                       📄 View & Download PDF
                                     </a>
                                   ) : (
                                     <button
                                       className="btn btn-secondary"
                                       style={{
                                         fontSize: '0.72rem',
                                         padding: '5px 11px',
                                         borderRadius: '6px',
                                         fontWeight: 700,
                                         display: 'inline-flex',
                                         alignItems: 'center',
                                         gap: '5px',
                                         background: 'rgba(56, 189, 248, 0.15)',
                                         color: 'var(--accent-secondary)',
                                         border: '1px solid rgba(56, 189, 248, 0.35)',
                                         cursor: 'pointer'
                                       }}
                                       onClick={() => handleGenerateTailoredResume(false, entry.job_url, entry.job_title)}
                                       title="Compile PDF for this role"
                                     >
                                       📄 Compile PDF
                                     </button>
                                   )}
                                   <button
                                     className="btn btn-secondary"
                                     style={{
                                       fontSize: '0.72rem',
                                       padding: '5px 11px',
                                       borderRadius: '6px',
                                       fontWeight: 700,
                                       display: 'inline-flex',
                                       alignItems: 'center',
                                       gap: '5px',
                                       background: 'rgba(16, 185, 129, 0.12)',
                                       color: '#10b981',
                                       border: '1px solid rgba(16, 185, 129, 0.3)',
                                       cursor: 'pointer'
                                     }}
                                     onClick={async (e) => {
                                       e.stopPropagation();
                                       setStatusMessage('Sending compiled PDF resume to your email...');
                                       try {
                                         const targetPdfUrl = entry.pdf_url || '/download_application_pdf/guest/tailored_resume.pdf';
                                         const res = await fetch(API_BASE + '/send_application_pdf_email', {
                                           method: 'POST',
                                           headers: {
                                             'Content-Type': 'application/json',
                                             'Authorization': 'Bearer ' + getAuthHeader()
                                           },
                                           body: JSON.stringify({
                                             pdf_url: targetPdfUrl,
                                             job_title: entry.job_title,
                                             company: entry.company,
                                             score: entry.score,
                                             overleaf_url: entry.overleaf_url,
                                             job_url: entry.job_url
                                           })
                                         });
                                         const data = await res.json();
                                         if (res.ok) {
                                           setStatusMessage('📧 ' + (data.message || 'Email sent successfully!'));
                                         } else {
                                           setStatusMessage('❌ ' + (data.detail || 'Failed to send email'));
                                         }
                                       } catch (err) {
                                         setStatusMessage('❌ Error: ' + err.message);
                                       }
                                     }}
                                     title="Send compiled PDF resume to your email"
                                   >
                                     📧 Send Email
                                   </button>
                                </div>
                                <div style={{ display: 'flex', gap: '8px', width: '100%', marginTop: '6px' }}>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ flex: 1, padding: '6px 8px', fontSize: '0.68rem', minHeight: '34px', whiteSpace: 'nowrap' }}
                                    onClick={async () => {
                                      setLoading(true);
                                      setStatusMessage('Preparing personalized interview pack...');
                                      try {
                                        const res = await fetch(`${API_BASE}/generate_interview_prep`, {
                                          method: 'POST',
                                          headers: {
                                            'Content-Type': 'application/json',
                                            'Authorization': `Bearer ${getAuthHeader()}`
                                          },
                                          body: JSON.stringify({
                                            job_title: entry.job_title || 'Target Role',
                                            company: entry.company || 'Target Company',
                                            job_url: entry.job_url || null
                                          })
                                        });
                                        if (res.ok) {
                                          const data = await res.json();
                                          setPrepJobInfo({ jobTitle: entry.job_title || 'Target Role', company: entry.company || 'Target Company' });
                                          setPrepMarkdown(data.markdown);
                                          setPrepModalOpen(true);
                                          setStatusMessage('Interview preparation pack generated!');
                                        } else {
                                          const err = await res.json();
                                          // showToast(`Error: ${err.detail}`, 'error');
                                        }
                                      } catch (e) {
                                        // showToast(`Error: ${e.message}`, 'error');
                                      } finally {
                                        setLoading(false);
                                      }
                                    }}
                                  >
                                    🎤 Interview Prep
                                  </button>
                                  <button
                                     className="btn btn-secondary"
                                     style={{ flex: 1, padding: '6px 8px', fontSize: '0.68rem', minHeight: '34px', borderColor: 'var(--accent-cyan)', color: 'var(--accent-cyan)', whiteSpace: 'nowrap' }}
                                     onClick={async () => {
                                       setLoading(true);
                                       setStatusMessage('Generating tailored cover letter...');
                                       try {
                                         const res = await fetch(`${API_BASE}/generate_cover_letter_history`, {
                                           method: 'POST',
                                           headers: {
                                             'Content-Type': 'application/json',
                                             'Authorization': `Bearer ${getAuthHeader()}`
                                           },
                                           body: JSON.stringify({
                                             job_title: entry.job_title || 'Target Role',
                                             company: entry.company || 'Target Company',
                                             job_url: entry.job_url || null
                                           })
                                         });
                                         if (res.ok) {
                                           const data = await res.json();
                                            setCoverLetterText(data.cover_letter);
                                            setCoverLetterJobInfo({
                                              jobTitle: entry.job_title || 'Target Role',
                                              company: entry.company || 'Target Company'
                                            });
                                            setCoverLetterModalOpen(true);
                                            setStatusMessage('📝 Tailored cover letter generated!');
                                         } else {
                                           const err = await res.json();
                                           setStatusMessage(`❌ Error: ${err.detail}`);
                                         }
                                       } catch (e) {
                                         setStatusMessage(`❌ Error: ${e.message}`);
                                       } finally {
                                         setLoading(false);
                                       }
                                     }}
                                   >
                                     📝 Cover Letter
                                   </button>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ flex: 1, padding: '6px 8px', fontSize: '0.68rem', minHeight: '34px', borderColor: 'var(--accent-primary)', color: '#fff', whiteSpace: 'nowrap' }}
                                    onClick={async () => {
                                      setLoading(true);
                                      setStatusMessage('Generating outreach message...');
                                      try {
                                        const headers = {
                                          'Content-Type': 'application/json',
                                          'Authorization': `Bearer ${getAuthHeader()}`
                                        };
                                        if (geminiApiKey) {
                                          headers['X-Gemini-API-Key'] = geminiApiKey;
                                        }
                                        const res = await fetch(`${API_BASE}/generate_outreach`, {
                                          method: 'POST',
                                          headers: headers,
                                          body: JSON.stringify({
                                            job_url: entry.job_url || '',
                                            job_description: '', // Scraper extracts JD automatically if empty
                                            job_title: entry.job_title || 'Target Role',
                                            company_name: entry.company || 'Target Company',
                                            recruiter_name: null,
                                            platform: entry.job_url?.includes('linkedin') ? 'linkedin' : entry.job_url?.includes('indeed') ? 'indeed' : 'unknown'
                                          })
                                        });
                                        if (res.ok) {
                                          const data = await res.json();
                                          setOutreachRecruiterInfo(data.recruiter_info);
                                          setOutreachData(data.message);
                                          setOutreachModalOpen(true);
                                          setStatusMessage('Outreach message generated!');
                                          // showToast('Outreach message ready!', 'success');
                                        } else {
                                          const err = await res.json();
                                          // showToast(`Error: ${err.detail}`, 'error');
                                        }
                                      } catch (e) {
                                        // showToast(`Error: ${e.message}`, 'error');
                                      } finally {
                                        setLoading(false);
                                      }
                                    }}
                                  >
                                    ✉️ Outreach
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )
            ) : discovering ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                  <svg style={{ animation: 'spin 1s linear infinite', width: '18px', height: '18px', flexShrink: 0 }} viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" style={{ opacity: 0.25 }} />
                    <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Searching Platform Feeds… ({discoveredJobs.length} matches found so far)</span>
                </div>
                <div className="log-terminal">
                  <div className="log-terminal-header">
                    <div className="log-terminal-dots">
                      <div className="log-terminal-dot" style={{ background: '#FF5F57' }} />
                      <div className="log-terminal-dot" style={{ background: '#FFBD2E' }} />
                      <div className="log-terminal-dot" style={{ background: '#28CA41' }} />
                    </div>
                    📋 LIVE SEARCH PIPELINE LOGS
                  </div>
                  <div
                    className="log-terminal-body"
                    ref={consoleBodyRef}
                    onScroll={(e) => {
                      const el = e.currentTarget;
                      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                      consoleUserScrolled.current = !atBottom;
                    }}
                    style={{ maxHeight: '160px' }}
                  >
                    {statusLogs.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', padding: '12px', fontStyle: 'italic' }}>
                        Initializing search...
                      </div>
                    ) : (
                      statusLogs.map((entry, index) => {
                        const msg = typeof entry === 'string' ? entry : entry.message;
                        const ts = typeof entry === 'object' ? entry.ts : '';
                        let cls = 'log-entry-msg log-default';
                        if (msg.includes('🏁') || msg.includes('✅') || msg.includes('✓')) cls = 'log-entry-msg log-ok';
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

                {/* Render live streaming job cards immediately as they arrive */}
                {discoveredJobs.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '10px' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--accent-green)', fontWeight: 700 }}>
                      ⚡ Live Matches Arriving ({discoveredJobs.length}):
                    </div>
                    {discoveredJobs.map((job, idx) => {
                      const score = job.score || 0;
                      const scoreColor = getScoreColor(score);
                      return (
                        <div key={idx} className="card job-card" style={{ padding: '14px 16px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(16,185,129,0.3)', animation: 'fadeIn 0.3s ease-out' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#fff' }}>{job.title}</div>
                              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>{job.company} • {job.location}</div>
                            </div>
                            <div style={{ padding: '4px 10px', borderRadius: '20px', background: `${scoreColor}22`, color: scoreColor, fontWeight: 800, fontSize: '0.85rem' }}>
                              {score}% Match
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
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
                      <div className="empty-state">
                        <div className="empty-state-icon">🔍</div>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: '6px' }}>No matching listings found</div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem', maxWidth: '340px', margin: '0 auto' }}>Enter search keywords or location and scan matches.</div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '500px', overflowY: 'auto', paddingRight: '4px' }}>
                          {paginated.map((job, idx) => {
                            const isExpanded = expandedCards.has(idx);
                            const score = job.score || 0;
                            const scoreColor = getScoreColor(score);
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
                                          background: job.platform === 'LinkedIn' ? 'rgba(10,102,194,0.15)'
                                                    : job.platform === 'Reed' ? 'rgba(236,72,153,0.15)'
                                                    : job.platform === 'Greenhouse' ? 'rgba(34,197,94,0.15)'
                                                    : job.platform === 'Ashby' ? 'rgba(168,85,247,0.15)'
                                                    : job.platform === 'Lever' ? 'rgba(56,189,248,0.15)'
                                                    : 'rgba(255,111,0,0.12)',
                                          color: job.platform === 'LinkedIn' ? '#0a66c2'
                                               : job.platform === 'Reed' ? '#ec4899'
                                               : job.platform === 'Greenhouse' ? '#22c55e'
                                               : job.platform === 'Ashby' ? '#c084fc'
                                               : job.platform === 'Lever' ? '#38bdf8'
                                               : '#ff6f00'
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
                                    {job.platform === 'LinkedIn' && !job.estimated && (
                                      job.recruiter_name ? (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px', fontSize: '0.72rem' }}>
                                          <span style={{ color: 'var(--text-muted)' }}>👤 Job poster: <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{job.recruiter_name}</span></span>
                                          {job.recruiter_profile_url && (
                                            <a
                                              href={job.recruiter_profile_url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              onClick={(e) => e.stopPropagation()}
                                              style={{ color: 'var(--accent-cyan)', fontWeight: 600, flexShrink: 0 }}
                                            >
                                              View Profile ↗
                                            </a>
                                          )}
                                        </div>
                                      ) : (
                                        !compactMode && (
                                          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', opacity: 0.6, marginTop: '4px' }}>
                                            👤 Job poster not available
                                          </div>
                                        )
                                      )
                                    )}
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
                                        <div style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>{job.skills_score || 50}%</div>
                                        <div style={{ fontSize: '0.58rem', opacity: 0.55 }}>
                                          {((job.matched_skills?.length || 0) + (job.missing_skills?.length || 0)) > 0
                                            ? `${job.matched_skills?.length || 0}/${(job.matched_skills?.length || 0) + (job.missing_skills?.length || 0)} key`
                                            : 'no keywords found'}
                                        </div>
                                      </div>
                                      <div>
                                        <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Experience</div>
                                        <div style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>{job.experience_score || 70}%</div>
                                        <div style={{ fontSize: '0.58rem', opacity: 0.55 }}>{job.candidate_years || 3}y / {job.required_years || 4}y req</div>
                                      </div>
                                      {!compactMode && (
                                        <>
                                          <div>
                                            <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Role Fit</div>
                                            <div style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>{job.role_fit_score || 65}%</div>
                                            <div style={{ fontSize: '0.58rem', opacity: 0.55 }}>Semantic</div>
                                          </div>
                                          <div>
                                            <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem', marginBottom: '2px' }}>Overall</div>
                                            <div style={{ fontWeight: 800, color: scoreColor }}>{score}%</div>
                                          </div>
                                        </>
                                      )}
                                    </div>
                                    <div style={{ display: 'flex', gap: '8px', marginTop: '4px', flexDirection: compactMode ? 'column' : 'row' }}>
                                      <button
                                        className="btn btn-primary"
                                        style={{ padding: '8px 12px', fontSize: '0.76rem', flex: 1, background: 'linear-gradient(135deg, #0284C7 0%, #2563EB 100%)', fontWeight: 700, border: 'none', color: '#fff', cursor: 'pointer' }}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setJobUrl(job.url || '');
                                          setJobTitle(job.title || '');
                                          setCompany(job.company || '');
                                          setJobDescription(job.raw_text || job.description || '');
                                          setIsDiscoveryView(false);
                                          setDashboardMode('tailor');
                                          window.scrollTo({ top: 0, behavior: 'smooth' });
                                        }}
                                      >
                                        ⚡ Analyze & Scrape
                                      </button>
                                      {job.url && (
                                        <a
                                          href={job.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          onClick={(e) => e.stopPropagation()}
                                          style={{
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            padding: '8px 14px', fontSize: '0.76rem', flex: compactMode ? 1 : 'none',
                                            background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)',
                                            borderRadius: '6px', color: '#94a3b8', fontWeight: 600,
                                            textDecoration: 'none', whiteSpace: 'nowrap',
                                            transition: 'background 0.2s, color 0.2s'
                                          }}
                                          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; e.currentTarget.style.color = '#fff'; }}
                                          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; e.currentTarget.style.color = '#94a3b8'; }}
                                        >
                                          🔗 View Post ↗
                                        </a>
                                      )}
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
                  Before tailoring, an AI reviewer compared your resume against{jobTitle ? <> the <strong>{jobTitle}</strong>{company ? <> role at <strong>{company}</strong></> : null} job description</> : ' this job\'s description'} and flagged potential mismatches after 3 checks. Review its feedback below before proceeding.
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
                    title="Keeps your original, untailored resume instead"
                  >
                    No, Keep Original Resume
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
                {analysisResult?.match_analysis && (
                  <>
                    <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start', flexWrap: 'wrap' }}>

                      {/* Overall ring */}
                      <div className="match-ring-container" style={{ flexShrink: 0 }}>
                        <div
                          className="match-ring"
                          style={{
                            '--percent': analysisResult.match_analysis.overall_score || 0,
                            '--color': getScoreColor(analysisResult.match_analysis.overall_score || 0),
                          }}
                        >
                          <span className="match-ring-text">
                            {analysisResult.match_analysis.overall_score || 0}%
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
                          { label: 'Skills Match', score: analysisResult.match_analysis.skills_score || 0, method: 'Deterministic', detail: analysisResult.match_analysis.keyword_stats?.required_matched ? `${analysisResult.match_analysis.keyword_stats.required_matched} keywords` : null },
                          { label: 'Experience', score: analysisResult.match_analysis.experience_score || 0, method: 'Deterministic', detail: analysisResult.match_analysis.keyword_stats?.candidate_years ? `${analysisResult.match_analysis.keyword_stats.candidate_years}y / ${analysisResult.match_analysis.keyword_stats.required_years || '?'}y req` : null },
                          { label: 'Role Fit', score: analysisResult.match_analysis.role_fit_score || 0, method: 'AI Semantic', detail: 'Domain · Seniority · Industry' },
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
                                  background: getScoreColor(score),
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
                      <h3>Missing Required Skills <span style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)', fontWeight: 500 }}>(Click to force-include in resume)</span></h3>
                      <div className="tag-list">
                        {(analysisResult.match_analysis.missing_skills || []).map((skill, i) => {
                          const isSelected = userSelectedSkills.has(skill);
                          return (
                            <span
                              key={i}
                              className={`tag tag-missing ${isSelected ? 'selected-skill-chip' : ''}`}
                              style={{
                                cursor: 'pointer', userSelect: 'none', transition: 'all 0.2s ease',
                                background: isSelected ? 'rgba(16, 185, 129, 0.25)' : undefined,
                                border: isSelected ? '1px solid #10B981' : undefined,
                                color: isSelected ? '#34D399' : undefined,
                                fontWeight: isSelected ? 700 : 500
                              }}
                              onClick={() => {
                                setUserSelectedSkills(prev => {
                                  const next = new Set(prev);
                                  if (next.has(skill)) next.delete(skill); else next.add(skill);
                                  
                                  // Dynamically recalculate ATS score preview using exact JD skill weights
                                  const skillWeights = analysisResult?.match_analysis?.score_breakdown?.skill_weights || {};
                                  const missingList = analysisResult?.match_analysis?.missing_skills || [];
                                  let totalBoost = 0;
                                  next.forEach(s => {
                                    const w = skillWeights[s] || (1 / (missingList.length || 5));
                                    totalBoost += (0.40 * 85.0 * w);
                                  });
                                  const baseScore = window.baseOriginalAtsScore || analysisResult?.match_analysis?.overall_score || 50;
                                  if (!window.baseOriginalAtsScore) window.baseOriginalAtsScore = baseScore;
                                  const newScore = Math.min(99, Math.round(window.baseOriginalAtsScore + totalBoost));
                                  setAnalysisResult(old => ({
                                    ...old,
                                    match_analysis: {
                                      ...old.match_analysis,
                                      overall_score: newScore,
                                      skills_score: Math.min(100, Math.round((old.match_analysis.skills_score || 50) + (totalBoost * 2.5)))
                                    }
                                  }));
                                  return next;
                                });
                              }}
                            >
                              {isSelected ? '✓ ' : '+ '}{skill}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </>
                )}


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
                        style={{ padding: '11px 20px', borderColor: 'var(--accent-cyan)', color: 'var(--accent-cyan)', fontWeight: 600 }}
                        onClick={async () => {
                          setLoading(true);
                          setStatusMessage('Generating standalone cover letter...');
                          try {
                            const res = await fetch(`${API_BASE}/generate_cover_letter_history`, {
                              method: 'POST',
                              headers: {
                                'Content-Type': 'application/json',
                                'Authorization': `Bearer ${getAuthHeader()}`
                              },
                              body: JSON.stringify({
                                job_title: jobTitle || 'Target Role',
                                company: company || 'Target Company',
                                job_url: jobUrl || null
                              })
                            });
                            if (res.ok) {
                              const data = await res.json();
                              setAnalysisResult(prev => ({
                                ...(prev || {}),
                                cover_letter: data.cover_letter
                              }));
                              setKeepOriginalMode(true);
                              setStatusMessage('📝 Tailored cover letter generated!');
                            } else {
                              const err = await res.json();
                              setStatusMessage(`❌ Error: ${err.detail || 'Failed to generate cover letter'}`);
                            }
                          } catch (e) {
                            setStatusMessage(`❌ Error: ${e.message}`);
                          } finally {
                            setLoading(false);
                          }
                        }}
                      >
                        📝 Cover Letter Only
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '11px 20px' }}
                        onClick={() => {
                          setKeepOriginalMode(true);
                          // showToast('📄 Keeping original resume — Overleaf export is ready.', 'info');
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

                    {analysisResult?.cover_letter && (
                      <div className="workspace-panel" style={{ width: '100%', maxWidth: '700px', marginTop: '16px' }}>
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
                        <div className="panel-content" style={{ whiteSpace: 'pre-wrap', textAlign: 'left' }}>
                          {analysisResult.cover_letter}
                        </div>
                      </div>
                    )}
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
                        {analysisResult && analysisResult.pdf_url && (
                          <a
                            href={`${API_BASE}${analysisResult.pdf_url}`}
                            download
                            className="btn btn-secondary"
                            style={{ padding: '5px 12px', fontSize: '0.76rem', gap: '5px', textDecoration: 'none' }}
                          >
                            ⬇️ Download PDF
                          </a>
                        )}
                        {analysisResult && analysisResult.latex_code && (
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '5px 12px', fontSize: '0.76rem', gap: '5px', color: 'var(--accent-green)', borderColor: 'rgba(16,185,129,0.3)' }}
                            disabled={loading}
                            onClick={async () => {
                              if (!window.confirm("Set this tailored resume as your new Master Resume profile?")) return;
                              setLoading(true);
                              setStatusMessage('Promoting tailored resume to Master Resume profile...');
                              try {
                                const res = await fetch(`${API_BASE}/user/update_master_from_tailored`, {
                                  method: 'POST',
                                  headers: {
                                    'Content-Type': 'application/json',
                                    'Authorization': `Bearer ${getAuthHeader()}`
                                  },
                                  body: JSON.stringify({ latex_code: analysisResult.latex_code })
                                });
                                if (res.ok) {
                                  const body = await res.json();
                                  setResumeData(body.data);
                                  setResumeEvaluation(body.evaluation);
                                  setStatusMessage('📌 Master Resume updated from tailored version!');
                                } else {
                                  throw new Error('Failed to promote resume');
                                }
                              } catch (err) {
                                setStatusMessage(`Error updating master: ${err.message}`);
                              } finally {
                                setLoading(false);
                              }
                            }}
                            title="Promote this tailored version as your new Master Resume baseline"
                          >
                            📌 Set as Master
                          </button>
                        )}
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
        }} onClick={closeKeyboardHelp}>
          <div
            ref={keyboardHelpModalRef}
            role="dialog"
            aria-modal="true"
            aria-label="Keyboard Shortcuts"
            tabIndex={-1}
            style={{
              background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
              borderRadius: '16px', padding: '32px', maxWidth: '500px', width: '90%',
              maxHeight: '85vh', overflowY: 'auto',
              boxShadow: '0 20px 60px rgba(0,0,0,0.5)', animation: 'slideDown 0.3s ease both'
            }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h2 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 700 }}>Keyboard Shortcuts</h2>
              <button
                className="btn btn-secondary"
                style={{ padding: '4px 8px', fontSize: '1.2rem', minWidth: '32px', minHeight: '32px' }}
                onClick={closeKeyboardHelp}
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
              onClick={closeKeyboardHelp}
            >
              Got it
            </button>
          </div>
        </div>
      )}

      {/* Dedicated Interview Prep Modal */}
      {prepModalOpen && (
        <div className="modal-overlay" onClick={closePrepModal} style={{ pointerEvents: 'auto', zIndex: 10000 }}>
          <div
            ref={prepModalRef}
            className="modal-content outreach-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Interview Preparation Guide"
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '800px', width: '100%', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}
          >
            {/* Header */}
            <div className="modal-header">
              <div>
                <h2>🎤 Interview Preparation Guide</h2>
                <p className="modal-subtitle">
                  {prepJobInfo.jobTitle} at {prepJobInfo.company}
                </p>
              </div>
              <button className="modal-close" onClick={closePrepModal}>✕</button>
            </div>

            {/* Role Info Chip */}
            <div className="recruiter-info-box">
              <div className="recruiter-name">AI-Generated Tailored Interview Pack</div>
              <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                Key technical questions, behavioral STAR responses, and role risks for {prepJobInfo.company}.
              </div>
            </div>

            {/* Content */}
            <div className="outreach-content" style={{ flex: 1, overflowY: 'auto' }}>
              <div className="message-text" style={{ whiteSpace: 'pre-wrap', textAlign: 'left', fontSize: '0.88rem', lineHeight: 1.65 }}>
                {prepMarkdown}
              </div>

              {/* Action Buttons */}
              <div className="action-buttons" style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                <button
                  className="btn"
                  style={{ flex: 1, fontWeight: 700 }}
                  onClick={() => {
                    navigator.clipboard.writeText(prepMarkdown);
                  }}
                >
                  📋 Copy Prep Guide
                </button>
                <button
                  className="btn btn-secondary"
                  style={{ flex: 1 }}
                  onClick={closePrepModal}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Dedicated Cover Letter Modal Popup */}
      {coverLetterModalOpen && (
        <div className="modal-overlay" onClick={() => setCoverLetterModalOpen(false)} style={{ pointerEvents: 'auto', zIndex: 10000 }}>
          <div
            className="modal-content outreach-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Tailored Cover Letter"
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '800px', width: '100%', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}
          >
            {/* Header */}
            <div className="modal-header">
              <div>
                <h2>📝 Tailored Cover Letter</h2>
                <p className="modal-subtitle">
                  {coverLetterJobInfo.jobTitle} at {coverLetterJobInfo.company}
                </p>
              </div>
              <button className="modal-close" onClick={() => setCoverLetterModalOpen(false)}>✕</button>
            </div>

            {/* Role Info Chip */}
            <div className="recruiter-info-box">
              <div className="recruiter-name">Custom Role-Matched Cover Letter</div>
              <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                Tailored for {coverLetterJobInfo.jobTitle} application at {coverLetterJobInfo.company}.
              </div>
            </div>

            {/* Content */}
            <div className="outreach-content" style={{ flex: 1, overflowY: 'auto' }}>
              <div className="message-text" style={{ whiteSpace: 'pre-wrap', textAlign: 'left', fontSize: '0.88rem', lineHeight: 1.65 }}>
                {coverLetterText}
              </div>

              {/* Action Buttons */}
              <div className="action-buttons" style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                <button
                  className="btn"
                  style={{ flex: 1, fontWeight: 700 }}
                  onClick={() => {
                    navigator.clipboard.writeText(coverLetterText);
                    setCoverLetterCopiedModal(true);
                    setTimeout(() => setCoverLetterCopiedModal(false), 2000);
                  }}
                >
                  {coverLetterCopiedModal ? '✓ Copied to Clipboard!' : '📋 Copy Cover Letter'}
                </button>
                <button
                  className="btn btn-secondary"
                  style={{ flex: 1 }}
                  onClick={() => setCoverLetterModalOpen(false)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>

      {/* Extension Installation Setup Guide Modal */}
      {showExtensionGuide && (
        <div className="modal-overlay" style={{ pointerEvents: 'auto' }}>
          <div className="card" style={{
            maxWidth: '540px', width: '100%', border: '1px solid rgba(56, 189, 248, 0.4)',
            padding: '28px', background: '#0F172A', boxShadow: '0 25px 60px rgba(0,0,0,0.85)',
            display: 'flex', flexDirection: 'column', gap: '18px', borderRadius: '20px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '12px' }}>
              <div style={{ fontWeight: 800, fontSize: '1.15rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>🎯 Chrome Extension Setup Guide</span>
              </div>
              <button
                className="btn btn-secondary"
                style={{ padding: '4px 10px', fontSize: '0.78rem' }}
                onClick={() => setShowExtensionGuide(false)}
              >
                ✕ Close
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', fontSize: '0.85rem', color: '#cbd5e1' }}>
              <div style={{ background: 'rgba(2, 132, 199, 0.12)', border: '1px solid rgba(56, 189, 248, 0.3)', borderRadius: '12px', padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: '0.72rem', fontWeight: 800, color: '#38bdf8', textTransform: 'uppercase' }}>Your Personal Sync Key</div>
                  <div style={{ fontFamily: 'monospace', fontSize: '1.1rem', fontWeight: 800, color: '#34d399', marginTop: '2px' }}>{user ? user.sync_code : "GABY48"}</div>
                </div>
                <button
                  className="btn"
                  style={{ padding: '6px 12px', fontSize: '0.76rem', background: '#0284c7', color: '#fff' }}
                  onClick={() => {
                    handleOneClickExtensionSync(user ? user.sync_code : "GABY48");
                  }}
                >
                  📥 Re-Download ZIP
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                  <span style={{ background: '#0284c7', color: '#fff', borderRadius: '50%', width: '22px', height: '22px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.75rem', flexShrink: 0, marginTop: '2px' }}>1</span>
                  <div>
                    <strong style={{ color: '#fff' }}>Download & Unzip</strong>
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '2px' }}>Click <strong>1-Click Auto-Sync & Download</strong> to download your pre-configured ZIP package (e.g. <code>Job_Finder_Extension_GABY48.zip</code>). Double-click to unzip the folder.</div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                  <span style={{ background: '#0284c7', color: '#fff', borderRadius: '50%', width: '22px', height: '22px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.75rem', flexShrink: 0, marginTop: '2px' }}>2</span>
                  <div>
                    <strong style={{ color: '#fff' }}>Open Extensions Page</strong>
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '2px' }}>In Google Chrome, open a new tab and go to <code style={{ color: '#38bdf8' }}>chrome://extensions</code></div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                  <span style={{ background: '#0284c7', color: '#fff', borderRadius: '50%', width: '22px', height: '22px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.75rem', flexShrink: 0, marginTop: '2px' }}>3</span>
                  <div>
                    <strong style={{ color: '#fff' }}>Enable Developer Mode</strong>
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '2px' }}>Toggle the <strong>Developer mode</strong> switch in the top-right corner of Chrome Extensions page.</div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                  <span style={{ background: '#0284c7', color: '#fff', borderRadius: '50%', width: '22px', height: '22px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.75rem', flexShrink: 0, marginTop: '2px' }}>4</span>
                  <div>
                    <strong style={{ color: '#fff' }}>Load Unpacked Extension</strong>
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '2px' }}>Click <strong>Load unpacked</strong> button at top-left and select the unzipped <code>extension</code> folder.</div>
                  </div>
                </div>
              </div>
            </div>

            <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '14px', textAlign: 'center' }}>
              <button
                className="btn"
                style={{ width: '100%', padding: '10px', fontSize: '0.86rem', fontWeight: 700, background: 'linear-gradient(135deg, #0284c7 0%, #10b981 100%)', color: '#fff' }}
                onClick={() => setShowExtensionGuide(false)}
              >
                ✓ Got it! Start Tailoring Jobs
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default App;
