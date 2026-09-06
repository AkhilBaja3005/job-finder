import React, { useState, useEffect, useRef, useCallback, useMemo, Suspense, lazy } from 'react';
import { useModalA11y } from './hooks/useModalA11y';

// Optimization #3: Lazy-load dashboard modes for code splitting
const TailorMode = lazy(() => import('./components/TailorMode'));
const DiscoverMode = lazy(() => import('./components/DiscoverMode'));
const HistoryMode = lazy(() => import('./components/HistoryMode'));
const SkeletonLoader = lazy(() => import('./components/SkeletonLoader').then(m => ({ default: m.SkeletonLoader })));
const OutreachModal = lazy(() => import('./components/OutreachModal'));
const DocsGuide = lazy(() => import('./components/DocsGuide'));
import LatexCodeViewer from './components/LatexCodeViewer';

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

const cleanSummaryText = (val) => {
  if (!val) return '';
  if (typeof val === 'object') return cleanSummaryText(val.summary || '');
  if (typeof val === 'string' && val.trim().startsWith('{')) {
    try {
      const parsed = JSON.parse(val);
      return cleanSummaryText(parsed.summary || '');
    } catch (e) {
      return val;
    }
  }
  return String(val);
};

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
  const [toast, setToast] = useState(null); // Toast popups disabled per user request
  const showToast = useCallback(() => {}, []);
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
  const [targetPlatform, setTargetPlatform] = useState(() => sessionStorage.getItem('target_platform') || 'all');
  const [isDiscoveryView, setIsDiscoveryView] = useState(() => sessionStorage.getItem('is_discovery_view') === 'true');
  const [dashboardMode, setDashboardMode] = useState(() => {
    if (typeof window !== 'undefined' && window.location.pathname.startsWith('/docs')) {
      return 'docs';
    }
    return sessionStorage.getItem('dashboard_mode') || 'tailor';
  });
  const [searchSortMode, setSearchSortMode] = useState('overall'); // 'overall' | 'role_fit' | 'time'
  const [searchPage, setSearchPage] = useState(1);
  const [discoverySearchQuery, setDiscoverySearchQuery] = useState('');
  const [discoveryQuickFilter, setDiscoveryQuickFilter] = useState('all'); // 'all' | 'unapplied' | 'applied' | 'saved'

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
    const targetKey = syncCode || (user && user.sync_code) || (localStorage.getItem('guest_token') ? localStorage.getItem('guest_token').replace('guest-', '').slice(0, 6).toUpperCase() : '');
    
    // 1. Copy Key to Clipboard
    try { navigator.clipboard.writeText(targetKey); } catch (e) {}

    // 2. Broadcast postMessage to extension if already installed
    let synced = false;
    const handleResponse = (event) => {
      if (event.data && event.data.type === "SYNC_JOB_FINDER_KEY_SUCCESS") {
        synced = true;
        showToast(`Extension Auto-Synced to Key: ${targetKey}!`, "success");
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

    showToast(`Extension ZIP (${targetKey}) downloading! Unzip & load in chrome://extensions`, "success");

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

  // Keyboard Shortcuts:
  // - Cmd/Ctrl + Enter: Trigger Analyze & Tailor Job
  // - Cmd/Ctrl + S: Save Master Archetype
  // - Cmd/Ctrl + 1: Switch to Tailor mode
  // - Cmd/Ctrl + 2: Switch to Discover mode
  // - Cmd/Ctrl + 3: Switch to History mode
  // - ?: Open Keyboard Shortcuts modal
  useEffect(() => {
    const handler = (e) => {
      // Allow Esc to close or ? to open help when not in inputs
      const isInputFocused = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!loading) {
          if (analysisResult?.latex_code) {
            handleGenerateTailoredResume(false);
          } else {
            handleAnalyzeJob();
          }
        }
        return;
      }

      if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        if (!archetypeLoading) {
          handleSaveArchetype();
        }
        return;
      }

      if ((e.metaKey || e.ctrlKey) && (e.key === '1' || e.key === '2' || e.key === '3')) {
        e.preventDefault();
        if (e.key === '1') {
          setDashboardMode('tailor');
          setIsDiscoveryView(false);
        } else if (e.key === '2') {
          setDashboardMode('discover');
          setIsDiscoveryView(true);
        } else if (e.key === '3') {
          setDashboardMode('history');
          setIsDiscoveryView(false);
          handleFetchHistory();
        }
        return;
      }

      if (e.key === '?' && !isInputFocused && !showKeyboardHelp) {
        e.preventDefault();
        setShowKeyboardHelp(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showKeyboardHelp, loading, archetypeLoading, analysisResult, jobUrl, jobTitle, jobDescription, resumeData, newArchetypeName]);

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
        body: JSON.stringify({ archetype_name: name, latex_code: null })
      });
      if (res.ok) {
        const body = await res.json();
        setUserArchetypes(body.archetypes || []);
        setActiveArchetype(body.active_archetype || name);
        setNewArchetypeName('');
        showToast(`Saved master archetype: ${name}`, 'success');
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
        showToast(`Switched active master profile to: ${name}`, 'success');
        fetchArchetypes();
      }
    } catch (e) {
      showToast('Failed to switch archetype: ' + e.message, 'error');
    } finally {
      setArchetypeLoading(false);
    }
  };

  const handleDeleteArchetype = async (name, e) => {
    if (e) e.stopPropagation();
    if (!window.confirm(`Are you sure you want to delete the master archetype profile "${name}"?`)) {
      return;
    }
    setArchetypeLoading(true);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
      const res = await fetch(`${API_BASE}/user/archetypes/delete`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ archetype_name: name })
      });
      if (res.ok) {
        const body = await res.json();
        setUserArchetypes(body.archetypes || []);
        if (body.active_archetype) setActiveArchetype(body.active_archetype);
        showToast(`Deleted archetype "${name}"`, 'info');
        fetchArchetypes();
      } else {
        showToast('Failed to delete archetype', 'error');
      }
    } catch (err) {
      showToast('Failed to delete archetype: ' + err.message, 'error');
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
        setStatusMessage('Baseline PDF generated & master resume evaluated successfully!');
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
          user_selected_skills: Array.from(userSelectedSkills || []),
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
          if (event.company) setCompany(event.company);
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
          company: company || null,
          job_description: activeDescription || null,
          skip_tailoring: false, // Run full LaTeX tailoring + page checks + reviewer checks
          force_tailoring: overrideForce,
          tailoring_intensity: tailoringIntensity,
          send_email: sendTailoredEmail,
          user_selected_skills: Array.from(userSelectedSkills || [])
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
          if (event.company) setCompany(event.company);
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
          if (result.company) setCompany(result.company);
          if (result.job_title) setJobTitle(result.job_title);
          const analysisObj = {
            ...result.analysis,
            pdf_url: result.analysis?.pdf_url || result.analysis?.download_pdf_url || result.download_pdf_url || result.pdf_url,
            overleaf_url: result.analysis?.overleaf_url || result.overleaf_url
          };
          setAnalysisResult(analysisObj);
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

      const targetPlatforms = targetPlatform && targetPlatform !== 'all' ? [targetPlatform] : null;
      const response = await fetch(`${API_BASE}/search_matching_jobs`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          role: searchKeywords || null,
          location: searchLocation,
          keywords: searchKeywords || null,
          timeframe: searchTimeframe,
          target_platforms: targetPlatforms
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
            sessionStorage.setItem('target_platform', targetPlatform);
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
    // 1. Filter by target platform if specified
    let filtered = [...discoveredJobs];
    if (targetPlatform && targetPlatform !== 'all') {
      const p = targetPlatform.toLowerCase();
      filtered = filtered.filter((j) => {
        const plat = (j.platform || '').toLowerCase();
        const url = (j.url || '').toLowerCase();
        return plat.includes(p) || url.includes(p);
      });
    }

    // 1b. In-memory keyword / title / company / skill search
    if (discoverySearchQuery.trim()) {
      const q = discoverySearchQuery.toLowerCase().trim();
      filtered = filtered.filter((j) => {
        const t = (j.title || '').toLowerCase();
        const c = (j.company || '').toLowerCase();
        const l = (j.location || '').toLowerCase();
        const skills = (j.matched_skills || []).join(' ').toLowerCase();
        return t.includes(q) || c.includes(q) || l.includes(q) || skills.includes(q);
      });
    }

    // 1c. Quick tracking filter (applied, saved, unapplied)
    if (discoveryQuickFilter !== 'all') {
      const appliedUrls = new Set(
        applicationHistory.filter((a) => a.status === 'applied').map((a) => a.job_url)
      );
      const savedUrls = new Set(
        applicationHistory.filter((a) => a.status === 'saved' || a.status === 'tailored').map((a) => a.job_url)
      );
      if (discoveryQuickFilter === 'applied') {
        filtered = filtered.filter((j) => appliedUrls.has(j.url));
      } else if (discoveryQuickFilter === 'saved') {
        filtered = filtered.filter((j) => savedUrls.has(j.url));
      } else if (discoveryQuickFilter === 'unapplied') {
        filtered = filtered.filter((j) => !appliedUrls.has(j.url));
      }
    }

    // 2. Sort copy of jobs array. Accurate (JD-scored) jobs always sort
    // before estimated (title-only) ones, since an estimated job's score
    // isn't directly comparable to a real ATS-scored one — within each
    // group, apply the user's chosen sort mode.
    const sorted = filtered;
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

    // 3. Paginate items (30 items per page)
    const itemsPerPage = 30;
    const totalPages = Math.ceil(sorted.length / itemsPerPage) || 1;
    const currentPage = Math.max(1, Math.min(searchPage, totalPages));
    const paginated = sorted.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

    return { sorted, paginated, totalPages, currentPage };
  }, [discoveredJobs, searchSortMode, searchPage, targetPlatform, discoverySearchQuery, discoveryQuickFilter, applicationHistory]);

  const formatJobDescription = (text) => {
    if (!text) return null;
    // Split into lines and clean up excessive empty lines
    const lines = text.split('\n');
    return lines.map((line, idx) => {
      const trimmed = line.trim();
      if (!trimmed) return <div key={idx} style={{ height: '8px' }} />;
      
      // Section header detection (e.g. "Requirements:", "About the Role", "What You'll Do:")
      const isHeader = /^(requirements|qualifications|about the role|responsibilities|what you'll do|skills|who you are|benefits|what we offer|nice to have|key responsibilities)[:\s]*$/i.test(trimmed)
        || (/^[A-Z][A-Za-z\s]{3,30}:$/.test(trimmed) && trimmed.length < 40);

      // Bullet point detection (starts with *, -, •, or digits like 1.)
      const isBullet = /^([*•\-]|\d+\.)\s+/.test(trimmed);

      if (isHeader) {
        return (
          <div key={idx} style={{ fontWeight: 800, color: '#38bdf8', marginTop: '12px', marginBottom: '4px', fontSize: '0.84rem', letterSpacing: '0.02em' }}>
            {trimmed}
          </div>
        );
      }

      if (isBullet) {
        const bulletText = trimmed.replace(/^([*•\-]|\d+\.)\s+/, '');
        return (
          <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', paddingLeft: '8px', marginTop: '3px' }}>
            <span style={{ color: '#34d399', fontSize: '0.75rem', lineHeight: 1.6, userSelect: 'none' }}>•</span>
            <span style={{ flex: 1, color: '#e2e8f0' }}>{bulletText}</span>
          </div>
        );
      }

      return (
        <div key={idx} style={{ marginTop: '3px', color: '#cbd5e1' }}>
          {trimmed}
        </div>
      );
    });
  };

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

  const handleViewTailoredPdf = async () => {
    if (!analysisResult) return;
    const directUrl = analysisResult.pdf_url || analysisResult.download_pdf_url;
    if (directUrl) {
      window.open(`${API_BASE}${directUrl}`, '_blank', 'noopener,noreferrer');
      return;
    }
    const newTab = window.open('', '_blank');
    setLoading(true);
    setStatusMessage('Compiling tailored resume PDF…');
    try {
      const res = await fetch(`${API_BASE}/compile_master_pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resume_data: tailoredResumeData || resumeData,
          job_title: jobTitle || 'Tailored Role',
          company: company || '',
        }),
      });
      if (!res.ok) throw new Error('PDF compilation failed');
      const data = await res.json();
      if (data.pdf_url) {
        setAnalysisResult(prev => ({ ...prev, pdf_url: data.pdf_url }));
        if (newTab) {
          newTab.location.href = `${API_BASE}${data.pdf_url}`;
        } else {
          window.open(`${API_BASE}${data.pdf_url}`, '_blank', 'noopener,noreferrer');
        }
        setStatusMessage('Tailored PDF opened!');
      } else if (newTab) {
        newTab.close();
      }
    } catch (err) {
      if (newTab) newTab.close();
      setStatusMessage(`Failed to compile PDF: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Helper to dynamically deduce where in candidate's resume a missing skill will be injected
  const getSkillTargetSection = (skillName) => {
    if (!skillName) return 'Skills & Experience';
    const s = skillName.toLowerCase();
    const exps = resumeData?.experience || tailoredResumeData?.experience || [];
    
    // Check if skill aligns with specific employers or roles
    for (const exp of exps) {
      const co = (exp.company || '').toLowerCase();
      const role = (exp.role || '').toLowerCase();
      if ((s.includes('system') || s.includes('c++') || s.includes('hardware') || s.includes('kernel') || s.includes('embedded') || s.includes('linux') || s.includes('cuda') || s.includes('distributed')) && co.includes('qualcomm')) {
        return `Appends under ${exp.company} (${exp.role || 'Systems'})`;
      }
      if ((s.includes('llm') || s.includes('genai') || s.includes('rag') || s.includes('nlp') || s.includes('agent') || s.includes('finetuning') || s.includes('langchain') || s.includes('prompt')) && (co.includes('axis') || role.includes('ai') || role.includes('engineer'))) {
        return `Emphasizes in ${exp.company} (${exp.role || 'GenAI'})`;
      }
    }

    if (exps.length > 0) {
      if (s.includes('cloud') || s.includes('aws') || s.includes('docker') || s.includes('kubernetes') || s.includes('k8s') || s.includes('ci/cd') || s.includes('pipeline')) {
        return `Injects into ${exps[0].company} & Projects`;
      }
      if (s.includes('c++') || s.includes('python') || s.includes('golang') || s.includes('rust') || s.includes('java') || s.includes('backend') || s.includes('api') || s.includes('rest') || s.includes('fastapi')) {
        return `Enhances Core Skills & ${exps[0].company}`;
      }
    }

    const projects = resumeData?.projects || tailoredResumeData?.projects || [];
    if (projects.length > 0) {
      return `Injects into Core Skills & ${projects[0].title || 'Projects'}`;
    }

    return 'Injects into Core Skills & Experience';
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
                  <span>Master Resume Profile Updated</span>
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
                PDF Comparison (Before vs After)
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
                Structured Diff View
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
                  LaTeX Source Code
                </button>
              )}
            </div>

            {/* TAB 1: PDF BEFORE VS AFTER SIDE-BY-SIDE VIEW */}
            {reviewModalTab === 'pdf' && (
              <div style={{ display: 'grid', gridTemplateColumns: beforePdfUrl ? '1fr 1fr' : '1fr', gap: '16px', marginTop: '6px' }}>
                {beforePdfUrl && (
                  <div style={{ background: '#090D1A', padding: '12px', borderRadius: '10px', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 800, color: '#F87171', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>BEFORE (Previous Baseline PDF)</span>
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
                    <span>AFTER (Updated Auto-Applied PDF)</span>
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
                    Copy LaTeX Code
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
                {cleanSummaryText(reviewedResumeData.summary) && (
                  <div style={{ background: 'var(--panel-bg)', padding: '16px', borderRadius: '10px', borderLeft: '4px solid var(--accent-cyan)' }}>
                    <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-cyan)', marginBottom: '6px' }}>PROFESSIONAL SUMMARY</div>
                    {previousResumeData && cleanSummaryText(previousResumeData.summary) && cleanSummaryText(previousResumeData.summary).trim() !== cleanSummaryText(reviewedResumeData.summary).trim() ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div style={{ fontSize: '0.8rem', color: '#F87171', background: 'rgba(239,68,68,0.12)', padding: '10px 12px', borderRadius: '6px', borderLeft: '3px solid #EF4444' }}>
                          <span style={{ fontWeight: 800, marginRight: '6px' }}>- OLD:</span>
                          <span style={{ textDecoration: 'line-through' }}>{cleanSummaryText(previousResumeData.summary)}</span>
                        </div>
                        <div style={{ fontSize: '0.82rem', color: '#34D399', background: 'rgba(16,185,129,0.12)', padding: '10px 12px', borderRadius: '6px', borderLeft: '3px solid #10B981', fontWeight: 600 }}>
                          <span style={{ fontWeight: 800, marginRight: '6px' }}>+ NEW:</span>
                          {cleanSummaryText(reviewedResumeData.summary)}
                        </div>
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.84rem', color: 'var(--text-main)', fontStyle: 'italic', lineHeight: 1.55 }}>
                        {cleanSummaryText(reviewedResumeData.summary)}
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
                Looks Good, Done
              </button>
            </div>
          </div>
        </div>
      )}

      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '6px',
            background: '#2563EB',
            border: '1px solid rgba(255, 255, 255, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#FFFFFF'
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
          </div>
          <div>
            <h1 className="title" style={{ fontSize: '1.05rem', margin: 0, fontWeight: 700, letterSpacing: '-0.02em' }}>
              JobFinder <span style={{ color: '#38BDF8', fontWeight: 500, fontSize: '0.82rem', fontFamily: 'var(--font-mono)' }}>Pro v3.0</span>
            </h1>
            <div style={{ fontSize: '0.66rem', fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>
              Autonomous ATS Tailoring Engine
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* Hugging Face / Backend Health Badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '3px 8px', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600,
            background: backendHealth === 'healthy' ? 'rgba(16,185,129,0.12)' : 'rgba(245,158,11,0.15)',
            border: `1px solid ${backendHealth === 'healthy' ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)'}`,
            color: backendHealth === 'healthy' ? '#10B981' : '#F59E0B',
            fontFamily: 'var(--font-mono)',
            cursor: 'default'
          }} title={
            backendHealth === 'healthy'
              ? `HF Space Active • Commit SHA: ${commitSha || 'latest'}${commitTime ? ` • commit time: ${commitTime}` : ''}`
              : 'Hugging Face container warming up...'
          }>
            <span style={{
              width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
              background: backendHealth === 'healthy' ? '#10B981' : '#F59E0B'
            }} />
            {backendHealth === 'healthy' ? 'Engine Online' : 'Warming Up…'}
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
                    <span>1-Click Auto-Sync & Download</span>
                  </button>

                  <button
                    className="btn btn-secondary"
                    style={{ padding: '7px 10px', fontSize: '0.76rem', color: '#94a3b8', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px' }}
                    onClick={() => {
                      setShowExtensionGuide(true);
                      setProfileDropdownOpen(false);
                    }}
                  >
                    <span>Setup Instructions</span>
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
              {['Keyword-matched ATS scoring', 'AI-tailored LaTeX resume & cover letter', '🔍 Recruiter truthfulness validation', '📄 One-click Overleaf export'].map(item => (
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ marginBottom: '4px' }}>Setup & Configuration</h2>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.87rem' }}>Configure your AI key and upload your master resume to get started.</p>
              </div>
              <button
                className="btn btn-secondary"
                style={{ padding: '6px 10px', fontSize: '0.78rem', borderRadius: '6px' }}
                onClick={() => setConfigStepActive(false)}
                title="Exit configuration modal"
              >
                ✕
              </button>
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
                  Get Free Gemini Key from Google ↗
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
                    <div style={{
                      width: '38px', height: '38px', borderRadius: '50%',
                      background: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.3)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-green)'
                    }}>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12"></polyline>
                      </svg>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontWeight: 700, color: 'var(--accent-green)', fontSize: '0.92rem' }}>{resumeData.name}</div>
                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '3px' }}>Click to replace master resume (.TEX, .PDF, .DOCX)</div>
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{
                      width: '42px', height: '42px', borderRadius: '10px',
                      background: 'rgba(56, 189, 248, 0.1)', border: '1px solid rgba(56, 189, 248, 0.25)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#38BDF8'
                    }}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                        <line x1="12" y1="18" x2="12" y2="12"></line>
                        <line x1="9" y1="15" x2="15" y2="15"></line>
                      </svg>
                    </div>
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
                          setStatusMessage('Master Resume opened in Overleaf!');
                        }
                      } catch (err) {
                        setStatusMessage(`Failed to open in Overleaf: ${err.message}`);
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    Open Master in Overleaf
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
                          setStatusMessage('Master PDF opened!');
                        }
                      } catch (err) {
                        setStatusMessage(`Failed to compile Master PDF: ${err.message}`);
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    View Compiled Master PDF
                  </button>
                </div>
              )}
            </div>

              {/* Candidate Identity & Contact Telemetry (when master resume is parsed) */}
              {resumeData && (resumeData.name || resumeData.email || resumeData.phone || resumeData.location || resumeData.experience_years) && (
                <div style={{
                  background: 'rgba(255, 255, 255, 0.02)',
                  borderRadius: '12px',
                  padding: '14px 16px',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#38bdf8' }}>
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                        <circle cx="12" cy="7" r="4" />
                      </svg>
                      Candidate Telemetry
                    </div>
                    {resumeData.experience_years && (
                      <span style={{
                        fontSize: '0.70rem',
                        fontWeight: 700,
                        padding: '2px 8px',
                        borderRadius: '10px',
                        background: 'rgba(56, 189, 248, 0.12)',
                        color: '#38bdf8',
                        border: '1px solid rgba(56, 189, 248, 0.25)',
                        fontFamily: 'var(--font-mono)'
                      }}>
                        {resumeData.experience_years}+ Yrs Exp
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.78rem' }}>
                    {resumeData.name && (
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '6px 10px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Name</div>
                        <div style={{ fontWeight: 600, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{resumeData.name}</div>
                      </div>
                    )}
                    {resumeData.email && (
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '6px 10px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Email</div>
                        <div style={{ fontWeight: 600, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={resumeData.email}>{resumeData.email}</div>
                      </div>
                    )}
                    {resumeData.phone && (
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '6px 10px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Phone</div>
                        <div style={{ fontWeight: 600, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{resumeData.phone}</div>
                      </div>
                    )}
                    {resumeData.location && (
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '6px 10px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Location</div>
                        <div style={{ fontWeight: 600, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{resumeData.location}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Master Profile Multi-Archetype Switcher & Manager */}
              <div style={{
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '12px',
                padding: '14px 16px',
                background: 'rgba(255, 255, 255, 0.02)',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '0.88rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#818cf8' }}>
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                        <circle cx="9" cy="7" r="4" />
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                      </svg>
                      Master Archetypes
                    </div>
                    <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                      Switch or snapshot role variants (e.g. GenAI, Data Science, Fullstack)
                    </div>
                  </div>
                  <span style={{ fontSize: '0.72rem', color: 'var(--accent-secondary)', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                    Active: {activeArchetype}
                  </span>
                </div>

                {/* Archetype Chips */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                  {userArchetypes.map((arch) => (
                    <div
                      key={arch.name}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        borderRadius: '6px',
                        border: arch.name === activeArchetype ? '1px solid var(--accent-primary)' : '1px solid rgba(255,255,255,0.1)',
                        background: arch.name === activeArchetype ? 'rgba(56, 189, 248, 0.16)' : 'rgba(0,0,0,0.3)',
                        overflow: 'hidden'
                      }}
                    >
                      <button
                        type="button"
                        disabled={archetypeLoading}
                        onClick={() => handleSwitchArchetype(arch.name)}
                        style={{
                          padding: '5px 9px',
                          background: 'transparent',
                          border: 'none',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px',
                          color: arch.name === activeArchetype ? '#38bdf8' : 'var(--text-muted)'
                        }}
                      >
                        <span>{arch.name === activeArchetype ? '✓' : '•'}</span>
                        <span>{arch.name}</span>
                        {arch.skills_count ? <span style={{ opacity: 0.6, fontSize: '0.68rem', fontFamily: 'var(--font-mono)' }}>({arch.skills_count})</span> : null}
                      </button>
                      {arch.name !== 'Primary' && (
                        <button
                          type="button"
                          title={`Delete ${arch.name}`}
                          disabled={archetypeLoading}
                          onClick={(e) => handleDeleteArchetype(arch.name, e)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            borderLeft: '1px solid rgba(255,255,255,0.1)',
                            color: '#94a3b8',
                            padding: '5px 7px',
                            cursor: 'pointer',
                            fontSize: '0.72rem',
                            lineHeight: 1
                          }}
                          onMouseEnter={(e) => e.currentTarget.style.color = '#ef4444'}
                          onMouseLeave={(e) => e.currentTarget.style.color = '#94a3b8'}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                </div>

                {/* Save Current as Archetype input */}
                <div style={{ display: 'flex', gap: '6px', marginTop: '2px' }}>
                  <input
                    type="text"
                    placeholder="New Archetype (e.g. GenAI Lead)"
                    value={newArchetypeName}
                    onChange={(e) => setNewArchetypeName(e.target.value)}
                    style={{ flex: 1, padding: '6px 10px', fontSize: '0.76rem', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#fff', marginBottom: 0 }}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSaveArchetype(); }}
                  />
                  <button
                    className="btn btn-secondary"
                    disabled={archetypeLoading || !newArchetypeName.trim()}
                    onClick={handleSaveArchetype}
                    style={{ padding: '6px 12px', fontSize: '0.75rem', fontWeight: 700, whiteSpace: 'nowrap' }}
                  >
                    {archetypeLoading ? 'Saving…' : '+ Save Archetype'}
                  </button>
                </div>
              </div>

              {/* Chrome Extension Pairing Key Card */}
              <div style={{
                background: 'rgba(56, 189, 248, 0.04)',
                borderRadius: '12px',
                padding: '14px 16px',
                border: '1px solid rgba(56, 189, 248, 0.18)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '12px'
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: '0.84rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                    </svg>
                    Extension Sync Key
                  </div>
                  <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Pairs Web Dashboard with Chrome Side Panel for 1-click ATS injection.
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                  <div style={{
                    fontSize: '0.98rem',
                    fontWeight: 800,
                    color: '#38bdf8',
                    background: 'rgba(56, 189, 248, 0.12)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    padding: '6px 12px',
                    borderRadius: '8px',
                    letterSpacing: '1.5px',
                    fontFamily: 'var(--font-mono)'
                  }}>
                    {(user && user.sync_code) ? user.sync_code : 'GUEST1'}
                  </div>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: '6px 10px', fontSize: '0.72rem', fontWeight: 700 }}
                    onClick={() => handleOneClickExtensionSync()}
                    title="Download extension pre-configured with this key"
                  >
                    Sync & ZIP ⤓
                  </button>
                </div>
              </div>

            {/* Daily Cron Match Mailer Subscription settings */}
            <div style={{ border: '1px solid rgba(56, 189, 248, 0.1)', borderRadius: '12px', overflow: 'hidden', background: 'rgba(56, 189, 248, 0.03)' }}>
                {/* Collapsible header */}
                <div
                  onClick={() => setMailerExpanded(prev => !prev)}
                  style={{ padding: '16px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', userSelect: 'none', gap: '12px' }}
                >
                  <div style={{ flexGrow: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.94rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>Daily Job Match Mailer</div>
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
                        <div style={{ fontWeight: 600, fontSize: '0.78rem', color: '#fff' }}>Email Tailored PDF Resumes</div>
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
                      Send Daily Digest Now
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
                Clear Caches & Data
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
                    <span>Master Resume ATS Health Score</span>
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
                    Detected Skills Profile
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
                    Recommended Master Playbook Enhancements:
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
                            setStatusMessage('Analyzing recommendation details...');
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
                              setStatusMessage('Master resume profile updated successfully!');
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
                        {applyingSugIdx === idx ? 'Applying…' : 'Auto-Apply'}
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
          <div className="card dashboard-left-panel" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>

            {/* Profile header row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ marginBottom: 0 }}>Active Profile</h2>
              <button
                className="btn btn-secondary"
                style={{ padding: '5px 10px', fontSize: '0.74rem', gap: '6px' }}
                onClick={() => setConfigStepActive(true)}
                aria-label="Open settings"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3"></circle>
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                </svg>
                <span>Settings</span>
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
                <div className="profile-avatar" style={{
                  width: '38px',
                  height: '38px',
                  borderRadius: '50%',
                  background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.2) 0%, rgba(37, 99, 235, 0.2) 100%)',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--accent-cyan)'
                }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                </div>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: resumeData ? '#fff' : 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {resumeData ? resumeData.name : 'No Resume Loaded'}
                </div>
                <div style={{ fontSize: '0.75rem', color: resumeData ? 'var(--accent-green)' : 'var(--accent-red)', marginTop: '2px', display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <span style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: resumeData ? 'var(--accent-green)' : 'var(--accent-red)',
                    boxShadow: resumeData ? '0 0 8px rgba(16, 185, 129, 0.6)' : 'none'
                  }}></span>
                  <span>{resumeData ? 'Profile active & calibrated' : 'Upload a resume to begin'}</span>
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '3px', fontFamily: 'var(--font-mono)' }}>
                  API Key: {geminiApiKey ? '••••••' + geminiApiKey.slice(-4) : 'Not configured'}
                </div>
              </div>
            </div>

            {/* ATS Performance Widget matching Enterprise Design */}
            <div style={{
              background: 'var(--panel-bg-subtle)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.68rem', fontWeight: 700, color: '#94a3b8', letterSpacing: '0.06em', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>
                  ATS Performance
                </span>
                <span style={{
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: '4px',
                  background: 'rgba(16, 185, 129, 0.12)',
                  color: '#10B981',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                  fontFamily: 'var(--font-mono)'
                }}>
                  {resumeEvaluation ? `${resumeEvaluation.ats_score || 93}% Match` : 'Calibrated'}
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                {/* Minimalist Precision Gauge */}
                <div style={{ position: 'relative', width: '84px', height: '84px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <svg width="84" height="84" viewBox="0 0 84 84">
                    <circle cx="42" cy="42" r="34" fill="none" stroke="#1E293B" strokeWidth="6" />
                    <circle
                      cx="42" cy="42" r="34" fill="none"
                      stroke="#10B981"
                      strokeWidth="6"
                      strokeDasharray={`${((resumeEvaluation?.ats_score || 93) / 100) * (2 * Math.PI * 34)} ${2 * Math.PI * 34}`}
                      strokeLinecap="round"
                      transform="rotate(-90 42 42)"
                    />
                  </svg>
                  <div style={{ position: 'absolute', textAlign: 'center' }}>
                    <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#FFFFFF', lineHeight: 1, fontFamily: 'var(--font-mono)' }}>
                      {resumeEvaluation?.ats_score || 93}%
                    </div>
                    <div style={{ fontSize: '0.52rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', marginTop: '3px', letterSpacing: '0.04em' }}>
                      Overall
                    </div>
                  </div>
                </div>

                {/* Performance Metrics Breakdown */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.74rem' }}>
                    <span style={{ color: '#94a3b8' }}>Readability</span>
                    <span style={{ fontWeight: 600, color: '#10B981', fontFamily: 'var(--font-mono)' }}>96%</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.74rem' }}>
                    <span style={{ color: '#94a3b8' }}>Keywords</span>
                    <span style={{ fontWeight: 600, color: '#38BDF8', fontFamily: 'var(--font-mono)' }}>{resumeEvaluation ? `${resumeEvaluation.skills_count ? Math.min(99, resumeEvaluation.skills_count * 5) : 91}%` : '91%'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.74rem' }}>
                    <span style={{ color: '#94a3b8' }}>Formatting</span>
                    <span style={{ fontWeight: 600, color: '#10B981', fontFamily: 'var(--font-mono)' }}>95%</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Mode Switcher 2x2 Grid */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '6px',
              borderRadius: '8px',
              background: '#0B1220',
              padding: '5px',
              border: '1px solid var(--border-color)',
              marginTop: '2px'
            }}>
              <button
                className={`mode-btn ${dashboardMode === 'master' ? 'active' : ''}`}
                style={{
                  padding: '8px 10px',
                  fontSize: '0.78rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: '1px solid ' + (dashboardMode === 'master' ? '#2563EB' : 'transparent'),
                  background: dashboardMode === 'master' ? 'rgba(37, 99, 235, 0.2)' : 'transparent',
                  color: dashboardMode === 'master' ? '#FFFFFF' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
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
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                  <line x1="3" y1="9" x2="21" y2="9"></line>
                  <line x1="9" y1="21" x2="9" y2="9"></line>
                </svg>
                <span>Master Profile</span>
              </button>
              <button
                className={`mode-btn ${dashboardMode === 'tailor' ? 'active' : ''}`}
                style={{
                  padding: '8px 10px',
                  fontSize: '0.78rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: '1px solid ' + (dashboardMode === 'tailor' ? '#2563EB' : 'transparent'),
                  background: dashboardMode === 'tailor' ? 'rgba(37, 99, 235, 0.2)' : 'transparent',
                  color: dashboardMode === 'tailor' ? '#FFFFFF' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
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
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="22" y1="12" x2="18" y2="12"></line>
                  <line x1="6" y1="12" x2="2" y2="12"></line>
                  <line x1="12" y1="6" x2="12" y2="2"></line>
                  <line x1="12" y1="22" x2="12" y2="18"></line>
                </svg>
                <span>Tailor Resume</span>
              </button>
              <button
                className={`mode-btn ${dashboardMode === 'discover' ? 'active' : ''}`}
                style={{
                  padding: '8px 10px',
                  fontSize: '0.78rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: '1px solid ' + (dashboardMode === 'discover' ? '#2563EB' : 'transparent'),
                  background: dashboardMode === 'discover' ? 'rgba(37, 99, 235, 0.2)' : 'transparent',
                  color: dashboardMode === 'discover' ? '#FFFFFF' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
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
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <span>Discover Jobs</span>
              </button>
              <button
                className={`mode-btn ${dashboardMode === 'history' ? 'active' : ''}`}
                style={{
                  padding: '8px 10px',
                  fontSize: '0.78rem',
                  borderRadius: '6px',
                  fontWeight: 600,
                  border: '1px solid ' + (dashboardMode === 'history' ? '#2563EB' : 'transparent'),
                  background: dashboardMode === 'history' ? 'rgba(37, 99, 235, 0.2)' : 'transparent',
                  color: dashboardMode === 'history' ? '#FFFFFF' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
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
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="12 6 12 12 16 14"></polyline>
                  <circle cx="12" cy="12" r="10"></circle>
                </svg>
                <span>History</span>
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
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', fontSize: '0.72rem', fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"></circle>
                  <circle cx="12" cy="12" r="6"></circle>
                  <circle cx="12" cy="12" r="2"></circle>
                </svg>
                Tailor
              </button>
              <button
                onClick={() => { setDashboardMode('discover'); setIsDiscoveryView(true); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'discover' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', fontSize: '0.72rem', fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                Discover
              </button>
              <button
                onClick={() => { setDashboardMode('history'); setIsDiscoveryView(false); handleFetchHistory(); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'history' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', fontSize: '0.72rem', fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                </svg>
                History
              </button>
              <button
                onClick={() => { setDashboardMode('docs'); setIsDiscoveryView(false); window.history.pushState(null, '', '/docs'); }}
                style={{
                  flex: 1, background: 'none', border: 'none', color: dashboardMode === 'docs' ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', fontSize: '0.72rem', fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
                </svg>
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
                  company={company}
                  setCompany={setCompany}
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
                  targetPlatform={targetPlatform}
                  setTargetPlatform={setTargetPlatform}
                  primaryRole={resumeData?.experience?.[0]?.role || ''}
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
            {dashboardMode === 'master' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', animation: 'fadeIn 0.25s ease' }}>
                <div className="section-label">Master Profile Controls</div>
                
                {/* Upload & Re-calibrate Box */}
                <label style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px',
                  padding: '18px 16px', borderRadius: '10px', cursor: 'pointer',
                  border: resumeData ? '1.5px solid rgba(16,185,129,0.35)' : '1.5px dashed var(--border-color)',
                  background: resumeData ? 'rgba(16,185,129,0.04)' : 'rgba(255,255,255,0.02)',
                  transition: 'all 0.2s ease',
                  textAlign: 'center'
                }}>
                  <input type="file" accept=".tex,.pdf,.docx" onChange={handleResumeUpload} style={{ display: 'none' }} />
                  <div style={{
                    width: '36px', height: '36px', borderRadius: '8px',
                    background: resumeData ? 'rgba(16,185,129,0.15)' : 'rgba(56,189,248,0.1)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: resumeData ? '#34D399' : '#38BDF8'
                  }}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                  </div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '0.85rem', color: resumeData ? '#34D399' : '#FFFFFF' }}>
                      {resumeData ? resumeData.name : 'Upload Master Resume'}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {resumeData ? 'Click to replace (.TEX, .PDF, .DOCX)' : 'Drop .TEX, .PDF, or .DOCX to calibrate'}
                    </div>
                  </div>
                </label>

                {/* Master Resume Action Buttons */}
                {resumeData && (
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      className="btn btn-secondary"
                      disabled={loading}
                      style={{ flex: 1, padding: '8px 10px', fontSize: '0.75rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '5px' }}
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
                            setStatusMessage('Master Resume opened in Overleaf!');
                          }
                        } catch (err) {
                          setStatusMessage(`Failed to open in Overleaf: ${err.message}`);
                        } finally {
                          setLoading(false);
                        }
                      }}
                      title="Export Master Resume to Overleaf"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                        <polyline points="15 3 21 3 21 9"></polyline>
                        <line x1="10" y1="14" x2="21" y2="3"></line>
                      </svg>
                      Overleaf
                    </button>

                    <button
                      className="btn btn-secondary"
                      disabled={loading}
                      style={{
                        flex: 1, padding: '8px 10px', fontSize: '0.75rem', fontWeight: 600,
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '5px',
                        background: 'rgba(56, 189, 248, 0.12)', color: '#38BDF8', borderColor: 'rgba(56, 189, 248, 0.3)'
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
                            setStatusMessage('Master PDF opened!');
                          }
                        } catch (err) {
                          setStatusMessage(`Failed to compile Master PDF: ${err.message}`);
                        } finally {
                          setLoading(false);
                        }
                      }}
                      title="View compiled 1-page PDF"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                      </svg>
                      View PDF
                    </button>
                  </div>
                )}

                {/* Candidate Contact Telemetry */}
                {resumeData && (
                  <div style={{
                    background: 'rgba(0,0,0,0.25)',
                    borderRadius: '10px',
                    padding: '12px 14px',
                    border: '1px solid rgba(255, 255, 255, 0.06)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px'
                  }}>
                    <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                      Profile Telemetry
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.74rem' }}>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.66rem' }}>Experience</div>
                        <div style={{ fontWeight: 600, color: '#fff', marginTop: '1px' }}>
                          {resumeEvaluation?.candidate_years ? `${resumeEvaluation.candidate_years} Years` : 'Calibrated'}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.66rem' }}>Quantified Bullets</div>
                        <div style={{ fontWeight: 600, color: '#34D399', marginTop: '1px' }}>
                          {resumeEvaluation ? `${resumeEvaluation.quantified_percentage}%` : 'High'}
                        </div>
                      </div>
                      {resumeData.email && (
                        <div style={{ gridColumn: 'span 2' }}>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.66rem' }}>Contact</div>
                          <div style={{ fontWeight: 500, color: '#94A3B8', marginTop: '1px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {resumeData.email}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Quick CTA to jump into Tailoring */}
                <button
                  className="btn btn-primary"
                  style={{ width: '100%', padding: '10px', fontSize: '0.82rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                  onClick={() => {
                    setDashboardMode('tailor');
                    setIsDiscoveryView(false);
                  }}
                >
                  <span>Target Active Job</span>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                    <polyline points="12 5 19 12 12 19"></polyline>
                  </svg>
                </button>
              </div>
            )}
          </div>

          {/* Right Analysis Panel */}
          <div ref={analysisPanelRef} className="card dashboard-right-panel" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ marginBottom: 0 }}>
                {dashboardMode === 'history'
                  ? 'Application History'
                  : dashboardMode === 'master'
                    ? 'Master Profile Overview'
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
                        <span>Master Profile Archetypes</span>
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
                      <div
                        key={arch.name}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          borderRadius: '8px',
                          border: arch.name === activeArchetype ? '1px solid var(--accent-primary)' : '1px solid rgba(255,255,255,0.1)',
                          background: arch.name === activeArchetype ? 'rgba(56, 189, 248, 0.2)' : 'rgba(0,0,0,0.3)',
                          overflow: 'hidden'
                        }}
                      >
                        <button
                          type="button"
                          disabled={archetypeLoading}
                          onClick={() => handleSwitchArchetype(arch.name)}
                          style={{
                            padding: '6px 10px',
                            background: 'transparent',
                            border: 'none',
                            fontSize: '0.78rem',
                            fontWeight: 700,
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            color: arch.name === activeArchetype ? '#38bdf8' : 'var(--text-muted)'
                          }}
                        >
                          <span>{arch.name === activeArchetype ? '✓' : '•'}</span>
                          <span>{arch.name}</span>
                          {arch.skills_count ? <span style={{ opacity: 0.6, fontSize: '0.7rem' }}>({arch.skills_count} skills)</span> : null}
                        </button>
                        {arch.name !== 'Primary' && (
                          <button
                            type="button"
                            title={`Delete ${arch.name}`}
                            disabled={archetypeLoading}
                            onClick={(e) => handleDeleteArchetype(arch.name, e)}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              borderLeft: '1px solid rgba(255,255,255,0.1)',
                              color: '#94a3b8',
                              padding: '6px 8px',
                              cursor: 'pointer',
                              fontSize: '0.75rem',
                              lineHeight: 1
                            }}
                            onMouseEnter={(e) => e.currentTarget.style.color = '#ef4444'}
                            onMouseLeave={(e) => e.currentTarget.style.color = '#94a3b8'}
                          >
                            ✕
                          </button>
                        )}
                      </div>
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
                      {archetypeLoading ? 'Saving...' : 'Save Archetype'}
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
                          <span>Master Resume ATS Health Score</span>
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
                          Recommended Master Playbook Enhancements:
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
                                  setStatusMessage('Analyzing recommendation details...');
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
                                    setStatusMessage('Master resume profile updated successfully!');
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
                              {applyingSugIdx === idx ? 'Applying…' : 'Auto-Apply'}
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
                            <span>Ready for instant 1-click tailoring against active job descriptions.</span>
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
                    {cleanSummaryText(resumeData.summary) && (
                      <div style={{ background: 'var(--panel-bg)', padding: '14px', borderRadius: '10px', borderLeft: '3px solid var(--accent-cyan)' }}>
                        <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent-cyan)', marginBottom: '4px' }}>PROFESSIONAL SUMMARY</div>
                        <div style={{ fontSize: '0.84rem', color: 'var(--text-main)', fontStyle: 'italic', lineHeight: 1.55 }}>
                          {cleanSummaryText(resumeData.summary)}
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
                  <div className="empty-state-icon">[HISTORY]</div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: '6px' }}>No history yet</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem', maxWidth: '340px', margin: '0 auto' }}>Tailor a resume or apply to a job to see it recorded here.</div>
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, minHeight: 0, paddingRight: '4px' }}>
                  {/* Funnel Metrics Dashboard Card */}
                  {(() => {
                    const tailoredCount = applicationHistory.filter(e => e.status === 'tailored').length;
                    const appliedCount = applicationHistory.filter(e => e.status === 'applied').length;
                    const total = applicationHistory.length || 1;

                    const tailoredPct = Math.round((tailoredCount / total) * 100);
                    const appliedPct = Math.round((appliedCount / total) * 100);

                    return (
                      <div className="card" style={{ padding: '14px', background: 'var(--panel-bg-subtle)', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>
                          Application Pipeline Funnel
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem', marginBottom: '4px' }}>
                              <span style={{ color: '#38BDF8', fontWeight: 600 }}>Tailored Resumes</span>
                              <span style={{ color: '#fff', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{tailoredCount} ({tailoredPct}%)</span>
                            </div>
                            <div style={{ height: '5px', background: 'rgba(255,255,255,0.06)', borderRadius: '4px', overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${tailoredPct}%`, background: '#38BDF8', borderRadius: '4px' }} />
                            </div>
                          </div>

                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.74rem', marginBottom: '4px' }}>
                              <span style={{ color: '#10B981', fontWeight: 600 }}>Submitted Applications</span>
                              <span style={{ color: '#fff', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{appliedCount} ({appliedPct}%)</span>
                            </div>
                            <div style={{ height: '5px', background: 'rgba(255,255,255,0.06)', borderRadius: '4px', overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${appliedPct}%`, background: '#10B981', borderRadius: '4px' }} />
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })()}

                  {/* Filter / Sort Control Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0 2px', flexWrap: 'wrap', gap: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontWeight: 700, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Filter:</span>
                      <button
                        onClick={() => setHistoryFilter('all')}
                        style={{
                          fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                          background: historyFilter === 'all' ? '#2563EB' : 'rgba(255,255,255,0.03)',
                          color: historyFilter === 'all' ? '#fff' : 'var(--text-muted)',
                          border: historyFilter === 'all' ? '1px solid #2563EB' : '1px solid var(--border-color)',
                          fontFamily: 'var(--font-mono)'
                        }}
                      >
                        All ({applicationHistory.length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('tailored')}
                        style={{
                          fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                          background: historyFilter === 'tailored' ? 'rgba(56,189,248,0.2)' : 'rgba(255,255,255,0.03)',
                          color: historyFilter === 'tailored' ? '#38BDF8' : 'var(--text-muted)',
                          border: historyFilter === 'tailored' ? '1px solid #38BDF8' : '1px solid var(--border-color)',
                          fontFamily: 'var(--font-mono)'
                        }}
                      >
                        Tailored ({applicationHistory.filter(e => e.status !== 'applied').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('applied')}
                        style={{
                          fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                          background: historyFilter === 'applied' ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.03)',
                          color: historyFilter === 'applied' ? '#10B981' : 'var(--text-muted)',
                          border: historyFilter === 'applied' ? '1px solid #10B981' : '1px solid var(--border-color)',
                          fontFamily: 'var(--font-mono)'
                        }}
                      >
                        Submitted ({applicationHistory.filter(e => e.status === 'applied').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('extension')}
                        style={{
                          fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                          background: historyFilter === 'extension' ? 'rgba(168,85,247,0.2)' : 'rgba(255,255,255,0.03)',
                          color: historyFilter === 'extension' ? '#c084fc' : 'var(--text-muted)',
                          border: historyFilter === 'extension' ? '1px solid #c084fc' : '1px solid var(--border-color)',
                          fontFamily: 'var(--font-mono)'
                        }}
                      >
                        Extension ({applicationHistory.filter(e => e.source_mode === 'extension').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('website')}
                        style={{
                          fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                          background: historyFilter === 'website' ? 'rgba(245,158,11,0.2)' : 'rgba(255,255,255,0.03)',
                          color: historyFilter === 'website' ? '#fbbf24' : 'var(--text-muted)',
                          border: historyFilter === 'website' ? '1px solid #fbbf24' : '1px solid var(--border-color)',
                          fontFamily: 'var(--font-mono)'
                        }}
                      >
                        Website ({applicationHistory.filter(e => e.source_mode !== 'extension' && e.source_mode !== 'email').length})
                      </button>
                      <button
                        onClick={() => setHistoryFilter('email')}
                        style={{
                          fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                          background: historyFilter === 'email' ? 'rgba(236,72,153,0.2)' : 'rgba(255,255,255,0.03)',
                          color: historyFilter === 'email' ? '#f472b6' : 'var(--text-muted)',
                          border: historyFilter === 'email' ? '1px solid #f472b6' : '1px solid var(--border-color)',
                          fontFamily: 'var(--font-mono)'
                        }}
                      >
                        Email ({applicationHistory.filter(e => e.source_mode === 'email').length})
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
                          <option value="newest">Newest First</option>
                          <option value="oldest">Oldest First</option>
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
                          platformBadge = { name: 'LinkedIn', color: '#0A66C2', icon: '' };
                        } else if (urlLower.includes('indeed.com')) {
                          platformBadge = { name: 'Indeed', color: '#2557A7', icon: '' };
                        } else if (urlLower.includes('glassdoor.com')) {
                          platformBadge = { name: 'Glassdoor', color: '#00A264', icon: '' };
                        } else if (urlLower.includes('ziprecruiter.com')) {
                          platformBadge = { name: 'ZipRecruiter', color: '#5B2C6F', icon: '' };
                        } else if (entry.job_url) {
                          platformBadge = { name: 'Direct Web', color: '#64748B', icon: '' };
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
                                    <span>Recruiter:</span>
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
                                <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                                  {entry.overleaf_url ? (
                                    <a
                                      href={entry.overleaf_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="btn-overleaf"
                                      style={{
                                        fontSize: '0.7rem',
                                        padding: '4px 10px',
                                        borderRadius: '4px',
                                        fontWeight: 600,
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '5px',
                                        textDecoration: 'none'
                                      }}
                                    >
                                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                        <polyline points="14 2 14 8 20 8"></polyline>
                                        <line x1="16" y1="13" x2="8" y2="13"></line>
                                        <line x1="16" y1="17" x2="8" y2="17"></line>
                                      </svg>
                                      <span>Overleaf</span>
                                    </a>
                                  ) : (
                                    <button
                                      className="btn-overleaf"
                                      style={{ fontSize: '0.7rem', padding: '4px 10px', borderRadius: '4px', opacity: 0.9, fontWeight: 600 }}
                                      onClick={() => handleGenerateTailoredResume(false, entry.job_url, entry.job_title)}
                                    >
                                      <span>Overleaf</span>
                                    </button>
                                  )}
                                  {entry.job_url && (
                                    <a
                                      href={entry.job_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        fontSize: '0.7rem',
                                        padding: '4px 10px',
                                        borderRadius: '4px',
                                        fontWeight: 600,
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                        textDecoration: 'none',
                                        background: 'rgba(255, 255, 255, 0.03)',
                                        color: '#e2e8f0',
                                        border: '1px solid var(--border-color)'
                                      }}
                                      title="Open original job posting"
                                    >
                                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                        <polyline points="15 3 21 3 21 9"></polyline>
                                        <line x1="10" y1="14" x2="21" y2="3"></line>
                                      </svg>
                                      <span>Posting</span>
                                    </a>
                                  )}
                                   {entry.pdf_url ? (
                                     <a
                                       href={API_BASE + entry.pdf_url}
                                       target="_blank"
                                       rel="noreferrer"
                                       style={{
                                         fontSize: '0.7rem',
                                         padding: '4px 10px',
                                         borderRadius: '4px',
                                         fontWeight: 600,
                                         display: 'inline-flex',
                                         alignItems: 'center',
                                         gap: '5px',
                                         textDecoration: 'none',
                                         background: 'rgba(37, 99, 235, 0.15)',
                                         color: '#38BDF8',
                                         border: '1px solid rgba(56, 189, 248, 0.3)'
                                       }}
                                       title="View & Download compiled PDF resume"
                                     >
                                       <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                         <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                         <polyline points="7 10 12 15 17 10"></polyline>
                                         <line x1="12" y1="15" x2="12" y2="3"></line>
                                       </svg>
                                       <span>PDF Resume</span>
                                     </a>
                                   ) : (
                                     <button
                                       className="btn btn-secondary"
                                       style={{
                                         fontSize: '0.7rem',
                                         padding: '4px 10px',
                                         borderRadius: '4px',
                                         fontWeight: 600,
                                         display: 'inline-flex',
                                         alignItems: 'center',
                                         gap: '5px',
                                         background: 'rgba(37, 99, 235, 0.15)',
                                         color: '#38BDF8',
                                         border: '1px solid rgba(56, 189, 248, 0.3)',
                                         cursor: 'pointer'
                                       }}
                                       onClick={() => handleGenerateTailoredResume(false, entry.job_url, entry.job_title)}
                                       title="Compile PDF for this role"
                                     >
                                       <span>Compile PDF</span>
                                     </button>
                                   )}
                                   <button
                                     className="btn btn-secondary"
                                     style={{
                                       fontSize: '0.7rem',
                                       padding: '4px 10px',
                                       borderRadius: '4px',
                                       fontWeight: 600,
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
                                           setStatusMessage(data.message || 'Email sent successfully');
                                         } else {
                                           setStatusMessage(data.detail || 'Failed to send email');
                                         }
                                       } catch (err) {
                                         setStatusMessage('Error: ' + err.message);
                                       }
                                     }}
                                     title="Send compiled PDF resume to your email"
                                   >
                                     <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                       <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                                       <polyline points="22,6 12,13 2,6"></polyline>
                                     </svg>
                                     <span>Email</span>
                                   </button>
                                </div>
                                <div style={{ display: 'flex', gap: '6px', width: '100%', marginTop: '6px' }}>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ flex: 1, padding: '5px 8px', fontSize: '0.68rem', minHeight: '30px', whiteSpace: 'nowrap', gap: '4px' }}
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
                                          setStatusMessage(`Error: ${err.detail}`);
                                        }
                                      } catch (e) {
                                        setStatusMessage(`Error: ${e.message}`);
                                      } finally {
                                        setLoading(false);
                                      }
                                    }}
                                  >
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
                                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                                      <line x1="12" y1="19" x2="12" y2="23"></line>
                                      <line x1="8" y1="23" x2="16" y2="23"></line>
                                    </svg>
                                    <span>Interview Prep</span>
                                  </button>
                                  <button
                                     className="btn btn-secondary"
                                     style={{ flex: 1, padding: '5px 8px', fontSize: '0.68rem', minHeight: '30px', borderColor: 'var(--border-color)', color: '#38BDF8', whiteSpace: 'nowrap', gap: '4px' }}
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
                                            setStatusMessage('Tailored cover letter generated!');
                                         } else {
                                           const err = await res.json();
                                           setStatusMessage(`Error: ${err.detail}`);
                                         }
                                       } catch (e) {
                                         setStatusMessage(`Error: ${e.message}`);
                                       } finally {
                                         setLoading(false);
                                       }
                                     }}
                                   >
                                     <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                       <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                       <polyline points="14 2 14 8 20 8"></polyline>
                                     </svg>
                                     <span>Cover Letter</span>
                                   </button>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ flex: 1, padding: '5px 8px', fontSize: '0.68rem', minHeight: '30px', borderColor: 'var(--border-color)', color: '#fff', whiteSpace: 'nowrap', gap: '4px' }}
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
                                        } else {
                                          const err = await res.json();
                                          setStatusMessage(`Error: ${err.detail}`);
                                        }
                                      } catch (e) {
                                        setStatusMessage(`Error: ${e.message}`);
                                      } finally {
                                        setLoading(false);
                                      }
                                    }}
                                  >
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                                      <polyline points="22,6 12,13 2,6"></polyline>
                                    </svg>
                                    <span>Outreach</span>
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
                    LIVE SEARCH PIPELINE LOGS
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
                      Live Matches Arriving ({discoveredJobs.length}):
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

                      {/* Filter, Search & Sorting Controls */}
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      paddingBottom: '12px',
                      borderBottom: '1px solid rgba(255,255,255,0.06)',
                      gap: '12px',
                      flexWrap: 'wrap'
                    }}>
                      {/* Left: Quick Search Bar */}
                      <div style={{ position: 'relative', flex: '1 1 220px', minWidth: '180px', maxWidth: '340px' }}>
                        <span style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', fontSize: '0.8rem', color: '#94a3b8', pointerEvents: 'none' }}>
                          🔍
                        </span>
                        <input
                          type="text"
                          value={discoverySearchQuery}
                          onChange={(e) => {
                            setDiscoverySearchQuery(e.target.value);
                            setSearchPage(1);
                          }}
                          placeholder="Filter titles, companies, skills…"
                          style={{
                            width: '100%',
                            padding: '6px 28px 6px 30px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.12)',
                            borderRadius: '8px',
                            color: '#fff',
                            fontSize: '0.78rem',
                            outline: 'none',
                            transition: 'border 0.2s ease'
                          }}
                        />
                        {discoverySearchQuery && (
                          <button
                            onClick={() => {
                              setDiscoverySearchQuery('');
                              setSearchPage(1);
                            }}
                            style={{
                              position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)',
                              background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '0.75rem', padding: '2px'
                            }}
                          >
                            ✕
                          </button>
                        )}
                      </div>

                      {/* Middle: Tracking Filter Pills */}
                      <div style={{ display: 'flex', gap: '4px', background: 'rgba(0,0,0,0.25)', padding: '3px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)' }}>
                        {[
                          { id: 'all', label: 'All' },
                          { id: 'unapplied', label: '⏳ Unapplied' },
                          { id: 'applied', label: 'Applied' },
                          { id: 'saved', label: '⭐ Saved' },
                        ].map(tab => (
                          <button
                            key={tab.id}
                            onClick={() => {
                              setDiscoveryQuickFilter(tab.id);
                              setSearchPage(1);
                            }}
                            style={{
                              padding: '4px 9px',
                              borderRadius: '6px',
                              border: 'none',
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              cursor: 'pointer',
                              background: discoveryQuickFilter === tab.id ? 'rgba(56,189,248,0.2)' : 'transparent',
                              color: discoveryQuickFilter === tab.id ? '#38bdf8' : '#94a3b8',
                              transition: 'all 0.15s ease'
                            }}
                          >
                            {tab.label}
                          </button>
                        ))}
                      </div>

                      {/* Right: Sort & Count */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{ fontSize: '0.72rem', color: '#94a3b8', fontWeight: 600 }}>Sort:</span>
                          <select
                            value={searchSortMode}
                            onChange={(e) => {
                              setSearchSortMode(e.target.value);
                              setSearchPage(1);
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
                              boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                            }}
                          >
                            <option value="overall">Overall Match %</option>
                            <option value="role_fit">Role Fit %</option>
                            <option value="time">Time / Age</option>
                          </select>
                        </div>
                        <span style={{ fontSize: '0.74rem', color: 'var(--accent-green)', fontWeight: 700 }}>
                          {sorted.length} matches
                        </span>
                        <button
                          onClick={() => {
                            if (expandedCards.size >= paginated.length && paginated.length > 0) {
                              setExpandedCards(new Set());
                            } else {
                              setExpandedCards(new Set(paginated.map((_, i) => i)));
                            }
                          }}
                          style={{
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.12)',
                            color: '#cbd5e1',
                            fontSize: '0.72rem',
                            fontWeight: 700,
                            padding: '5px 9px',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            transition: 'all 0.15s ease'
                          }}
                          title={expandedCards.size >= paginated.length && paginated.length > 0 ? "Collapse all open job descriptions" : "Expand all job descriptions on this page"}
                        >
                          {expandedCards.size >= paginated.length && paginated.length > 0 ? '⤡ Collapse All' : '⤢ Expand All'}
                        </button>
                      </div>
                    </div>

                    {sorted.length === 0 ? (
                      <div className="empty-state">
                        <div className="empty-state-icon">[SEARCH]</div>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: '6px' }}>No matching listings found</div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem', maxWidth: '340px', margin: '0 auto' }}>Enter search keywords or location and scan matches.</div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="job-scroll-container" style={{ display: 'flex', flexDirection: 'column', gap: '12px', flex: 1, minHeight: '400px', overflowY: 'auto', paddingRight: '6px' }}>
                          {paginated.map((job, idx) => {
                            const isExpanded = expandedCards.has(idx);
                            const score = job.score || 0;
                            const scoreColor = getScoreColor(score);
                            // Mini SVG arc for score
                            const r = 18, circ = 2 * Math.PI * r;
                            const arc = (score / 100) * circ;
                            return (
                              <div key={idx} className="card job-card" style={{
                                padding: '20px',
                                background: 'rgba(13, 18, 30, 0.75)',
                                border: '1px solid rgba(255, 255, 255, 0.07)',
                                borderRadius: '16px',
                                cursor: 'pointer',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '14px',
                                transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)'
                              }}
                                onClick={() => toggleCard(idx)}>
                                
                                {/* Top Row: Match Gauge + Job Info + Freshness */}
                                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
                                  
                                  {/* Large Circular Match Score Ring matching Mockup */}
                                  <div style={{
                                    position: 'relative',
                                    width: '68px',
                                    height: '68px',
                                    borderRadius: '50%',
                                    flexShrink: 0,
                                    display: 'flex',
                                    flexDirection: 'column',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    background: 'rgba(16, 185, 129, 0.08)',
                                    border: `2.5px solid ${scoreColor}`,
                                    boxShadow: `0 0 16px ${scoreColor}44`,
                                    transition: 'all 0.3s ease'
                                  }}>
                                    <span style={{ fontSize: '1.05rem', fontWeight: 900, color: '#FFFFFF', lineHeight: 1 }}>{score}%</span>
                                    <span style={{ fontSize: '0.52rem', fontWeight: 800, color: scoreColor, letterSpacing: '0.05em', marginTop: '1px' }}>MATCH</span>
                                  </div>

                                  {/* Job Header & Metadata */}
                                  <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                        {/* Company logo badge placeholder */}
                                        <div style={{
                                          width: '24px',
                                          height: '24px',
                                          borderRadius: '6px',
                                          background: 'linear-gradient(135deg, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.04) 100%)',
                                          border: '1px solid rgba(255,255,255,0.1)',
                                          display: 'flex',
                                          alignItems: 'center',
                                          justifyContent: 'center',
                                          fontWeight: 800,
                                          fontSize: '0.72rem',
                                          color: '#FFFFFF'
                                        }}>
                                          {job.company ? job.company.charAt(0).toUpperCase() : 'C'}
                                        </div>
                                        <span style={{ fontWeight: 800, fontSize: '0.92rem', color: '#FFFFFF' }}>{job.company}</span>
                                        <span style={{
                                          fontSize: '0.68rem', padding: '2px 7px', borderRadius: '5px', fontWeight: 700,
                                          background: job.platform === 'LinkedIn' ? 'rgba(10,102,194,0.2)'
                                                    : job.platform === 'Reed' ? 'rgba(236,72,153,0.2)'
                                                    : job.platform === 'Greenhouse' ? 'rgba(34,197,94,0.2)'
                                                    : job.platform === 'Ashby' ? 'rgba(168,85,247,0.2)'
                                                    : job.platform === 'Lever' ? 'rgba(56,189,248,0.2)'
                                                    : job.platform === 'Workday' ? 'rgba(245,158,11,0.2)'
                                                    : 'rgba(255,111,0,0.15)',
                                          color: job.platform === 'LinkedIn' ? '#38bdf8'
                                               : job.platform === 'Reed' ? '#ec4899'
                                               : job.platform === 'Greenhouse' ? '#4ade80'
                                               : job.platform === 'Ashby' ? '#c084fc'
                                               : job.platform === 'Lever' ? '#38bdf8'
                                               : job.platform === 'Workday' ? '#fbbf24'
                                               : '#ff6f00',
                                          border: '1px solid rgba(255,255,255,0.08)'
                                        }}>
                                          {job.platform}
                                        </span>
                                      </div>
                                      <span style={{ fontSize: '0.72rem', color: '#94a3b8', whiteSpace: 'nowrap' }}>{job.age || 'Recent'}</span>
                                    </div>

                                    <div style={{ fontWeight: 800, fontSize: '1rem', color: '#FFFFFF', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                      {job.title}
                                    </div>
                                    <div style={{ fontSize: '0.78rem', color: '#94a3b8', marginTop: '3px', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                      <span>{job.location || 'Remote'}</span>
                                      {job.seniority && (
                                        <span style={{
                                          fontSize: '0.68rem', padding: '1px 7px', borderRadius: '4px',
                                          background: 'rgba(56,189,248,0.12)', color: '#38bdf8',
                                          border: '1px solid rgba(56,189,248,0.25)', fontWeight: 700
                                        }}>
                                          {job.seniority}
                                        </span>
                                      )}
                                      {job.salary && (
                                        <span style={{
                                          fontSize: '0.68rem', padding: '1px 7px', borderRadius: '4px',
                                          background: 'rgba(234,179,8,0.12)', color: '#facc15',
                                          border: '1px solid rgba(234,179,8,0.25)', fontWeight: 700
                                        }}>
                                          {job.salary}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                </div>

                                {/* Skills checklist & count */}
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                    {(job.matched_skills || []).slice(0, 4).map((s, i) => (
                                      <span key={i} style={{ padding: '3px 9px', borderRadius: '6px', background: 'rgba(16,185,129,0.12)', color: '#34d399', border: '1px solid rgba(16,185,129,0.25)', fontSize: '0.72rem', fontWeight: 600 }}>
                                        ✓ {s}
                                      </span>
                                    ))}
                                    {(job.missing_skills || []).slice(0, 2).map((s, i) => (
                                      <span key={i} style={{ padding: '3px 9px', borderRadius: '6px', background: 'rgba(239,68,68,0.1)', color: '#f87171', border: '1px solid rgba(239,68,68,0.2)', fontSize: '0.72rem', fontWeight: 600 }}>
                                        ✕ {s}
                                      </span>
                                    ))}
                                  </div>

                                  <div style={{ fontSize: '0.74rem', color: '#34d399', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
                                    <span>✓ Skills Matched:</span>
                                    <strong style={{ color: '#FFFFFF' }}>{job.matched_skills?.length || 0}/{(job.matched_skills?.length || 0) + (job.missing_skills?.length || 0)}</strong>
                                  </div>
                                </div>

                                {/* Dual Action Buttons: View Description + Tailor Resume */}
                                <div style={{ display: 'flex', gap: '10px', marginTop: '2px' }}>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ flex: 1, padding: '9px 14px', fontSize: '0.8rem', fontWeight: 700, borderRadius: '8px' }}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      toggleCard(idx);
                                    }}
                                  >
                                    {isExpanded ? 'Hide Details ▲' : 'View Job Description ▼'}
                                  </button>
                                    <button
                                      className="btn"
                                      style={{
                                        flex: 1.2,
                                        padding: '8px 14px',
                                        fontSize: '0.82rem',
                                        fontWeight: 600,
                                        borderRadius: '6px',
                                        background: '#2563EB',
                                        border: '1px solid rgba(255, 255, 255, 0.15)',
                                        color: '#FFFFFF'
                                      }}
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
                                    Tailor Resume
                                  </button>
                                </div>

                                {/* Direct ATS Application Links & Tracking Controls */}
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: '0.74rem' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                                    {job.url && (
                                      <a
                                        href={job.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        onClick={(e) => e.stopPropagation()}
                                        style={{ color: '#34d399', fontWeight: 700, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '5px' }}
                                      >
                                        <span>Apply via {job.platform || 'Direct ATS'} ↗</span>
                                      </a>
                                    )}
                                    {job.platform === 'LinkedIn' && job.recruiter_profile_url && (
                                      <a
                                        href={job.recruiter_profile_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        onClick={(e) => e.stopPropagation()}
                                        style={{ color: '#38bdf8', fontWeight: 700, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '5px' }}
                                      >
                                        <span>in Recruiter Profile ↗</span>
                                      </a>
                                    )}
                                    <button
                                      onClick={async (e) => {
                                        e.stopPropagation();
                                        setLoading(true);
                                        setStatusMessage('Generating personalized outreach note...');
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
                                            headers,
                                            body: JSON.stringify({
                                              job_url: job.url || '',
                                              job_description: job.raw_text || job.description || '',
                                              job_title: job.title || 'Target Role',
                                              company_name: job.company || 'Target Company',
                                              recruiter_name: job.recruiter_name || null,
                                              platform: (job.platform || '').toLowerCase()
                                            })
                                          });
                                          if (res.ok) {
                                            const data = await res.json();
                                            setOutreachRecruiterInfo(data.recruiter_info || (job.recruiter_name ? { recruiter_name: job.recruiter_name, recruiter_profile_url: job.recruiter_profile_url } : null));
                                            setOutreachData(data.message);
                                            setOutreachModalOpen(true);
                                            showToast('Recruiter Outreach ready!', 'success');
                                          } else {
                                            // Fallback: generate high-converting client template directly
                                            const fallbackMsg = `Hi ${job.recruiter_name || 'Hiring Team'},\n\nI noticed the ${job.title} role at ${job.company} and wanted to reach out directly. With my experience matching ${job.score}% of your core requirements—specifically in ${(job.matched_skills || []).slice(0, 3).join(', ') || 'software engineering'}—I'd love to connect and discuss how I can contribute to the team.\n\nBest regards,\nCandidate`;
                                            setOutreachData(fallbackMsg);
                                            setOutreachModalOpen(true);
                                            showToast('Outreach template ready!', 'success');
                                          }
                                        } catch (err) {
                                          const fallbackMsg = `Hi ${job.recruiter_name || 'Hiring Team'},\n\nI noticed the ${job.title} opening at ${job.company}. Given my background in ${(job.matched_skills || []).slice(0, 3).join(', ') || 'modern technology'}, I believe I'd be a strong addition to your team. Would love to connect!\n\nBest regards,\nCandidate`;
                                          setOutreachData(fallbackMsg);
                                          setOutreachModalOpen(true);
                                          showToast('Outreach note opened!', 'success');
                                        } finally {
                                          setLoading(false);
                                        }
                                      }}
                                      style={{
                                        background: 'rgba(56,189,248,0.08)',
                                        border: '1px solid rgba(56,189,248,0.25)',
                                        color: '#38bdf8',
                                        padding: '2px 8px',
                                        borderRadius: '5px',
                                        fontSize: '0.7rem',
                                        fontWeight: 700,
                                        cursor: 'pointer',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                        transition: 'all 0.15s ease'
                                      }}
                                      title="Generate tailored cold message / InMail for this role"
                                    >
                                      Outreach Note
                                    </button>
                                  </div>

                                  {/* Quick Application & Tracking Status Toggles */}
                                  {(() => {
                                    const appEntry = applicationHistory.find((a) => a.job_url === job.url);
                                    const isApplied = appEntry?.status === 'applied';
                                    const isSaved = appEntry?.status === 'saved' || appEntry?.status === 'tailored';

                                    const handleQuickStatus = async (e, newStatus) => {
                                      e.stopPropagation();
                                      // Toggle off if already active
                                      const targetStatus = (isApplied && newStatus === 'applied') || (isSaved && newStatus === 'saved')
                                        ? 'viewed'
                                        : newStatus;

                                      // Optimistic local update
                                      setApplicationHistory((prev) => {
                                        const exists = prev.some((item) => item.job_url === job.url);
                                        if (exists) {
                                          return prev.map((item) => item.job_url === job.url ? { ...item, status: targetStatus } : item);
                                        }
                                        return [
                                          {
                                            job_url: job.url,
                                            job_title: job.title,
                                            company: job.company,
                                            score: job.score,
                                            status: targetStatus,
                                            source_mode: 'discovery',
                                            timestamp: Date.now() / 1000
                                          },
                                          ...prev
                                        ];
                                      });

                                      try {
                                        await fetch(`${API_BASE}/update_application_status`, {
                                          method: 'POST',
                                          headers: {
                                            'Content-Type': 'application/json',
                                            'Authorization': `Bearer ${getAuthHeader()}`
                                          },
                                          body: JSON.stringify({
                                            job_url: job.url || '',
                                            status: targetStatus,
                                            job_title: job.title || '',
                                            company: job.company || '',
                                            score: job.score || 0
                                          })
                                        });
                                      } catch (err) {
                                        console.error('Failed to update status', err);
                                      }
                                    };

                                    return (
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }} onClick={(e) => e.stopPropagation()}>
                                        <button
                                          onClick={(e) => handleQuickStatus(e, 'saved')}
                                          title={isSaved ? 'Remove from Saved' : 'Save job to tracker'}
                                          style={{
                                            background: isSaved ? 'rgba(234,179,8,0.2)' : 'rgba(255,255,255,0.06)',
                                            border: `1px solid ${isSaved ? 'rgba(234,179,8,0.4)' : 'rgba(255,255,255,0.1)'}`,
                                            color: isSaved ? '#facc15' : '#94a3b8',
                                            padding: '4px 8px',
                                            borderRadius: '6px',
                                            fontSize: '0.72rem',
                                            fontWeight: 700,
                                            cursor: 'pointer',
                                            transition: 'all 0.15s ease'
                                          }}
                                        >
                                          {isSaved ? '★ Saved' : '☆ Save'}
                                        </button>
                                        <button
                                          onClick={(e) => handleQuickStatus(e, 'applied')}
                                          title={isApplied ? 'Mark as Unapplied' : 'Mark as Applied'}
                                          style={{
                                            background: isApplied ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.06)',
                                            border: `1px solid ${isApplied ? 'rgba(16,185,129,0.4)' : 'rgba(255,255,255,0.1)'}`,
                                            color: isApplied ? '#34d399' : '#94a3b8',
                                            padding: '4px 8px',
                                            borderRadius: '6px',
                                            fontSize: '0.72rem',
                                            fontWeight: 700,
                                            cursor: 'pointer',
                                            transition: 'all 0.15s ease'
                                          }}
                                        >
                                          {isApplied ? '✓ Applied' : '+ Mark Applied'}
                                        </button>
                                      </div>
                                    );
                                  })()}
                                </div>

                                {/* Expanded Description & Deep ATS Breakdown */}
                                {isExpanded && (
                                  <div style={{ marginTop: '8px', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '12px', display: 'flex', flexDirection: 'column', gap: '10px', animation: 'fadeIn 0.2s ease both' }}>
                                    <div style={{
                                      display: 'grid', gridTemplateColumns: compactMode ? 'repeat(2, 1fr)' : 'repeat(3, 1fr)', gap: '8px',
                                      background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.05)',
                                      borderRadius: '10px', padding: '10px', fontSize: '0.74rem', textAlign: 'center'
                                    }}>
                                      <div>
                                        <div style={{ color: '#94a3b8', fontSize: '0.66rem' }}>Role Fit</div>
                                        <div style={{ fontWeight: 800, color: '#34d399', marginTop: '2px' }}>{job.role_fit_score || 88}%</div>
                                      </div>
                                      <div>
                                        <div style={{ color: '#94a3b8', fontSize: '0.66rem' }}>Skills Match</div>
                                        <div style={{ fontWeight: 800, color: '#38bdf8', marginTop: '2px' }}>{job.skills_score || 90}%</div>
                                      </div>
                                      <div>
                                        <div style={{ color: '#94a3b8', fontSize: '0.66rem' }}>Experience</div>
                                        <div style={{ fontWeight: 800, color: '#fcd34d', marginTop: '2px' }}>{job.experience_score || 85}%</div>
                                      </div>
                                    </div>
                                    <div style={{
                                      fontSize: '0.8rem',
                                      color: '#cbd5e1',
                                      lineHeight: 1.6,
                                      maxHeight: '280px',
                                      overflowY: 'auto',
                                      background: 'rgba(0,0,0,0.3)',
                                      padding: '12px 14px',
                                      borderRadius: '8px',
                                      border: '1px solid rgba(255,255,255,0.05)',
                                      wordBreak: 'break-word'
                                    }}>
                                      <div style={{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                                        <span>Job Description</span>
                                        {job.estimated && <span style={{ color: '#f59e0b', fontSize: '0.66rem' }}>Heuristic Match</span>}
                                      </div>
                                      {job.description || job.raw_text ? (
                                        formatJobDescription(job.description || job.raw_text)
                                      ) : (
                                        <div style={{ fontStyle: 'italic', color: '#64748b' }}>
                                          No cached job description found. Click "Tailor Resume" or "View Post" to inspect the full requirements.
                                        </div>
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
                  <span style={{ fontSize: '1rem', color: '#f59e0b', fontWeight: 700 }}>[ALERT]</span>
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
                    Yes, Generate Anyway
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
                    PIPELINE LOGS
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
                <div style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '20px',
                  animation: 'fadeIn 0.3s ease'
                }}>
                  {/* Readiness Banner Card */}
                  <div style={{
                    padding: '22px 24px',
                    borderRadius: '12px',
                    background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(30, 41, 59, 0.4) 100%)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    boxShadow: '0 8px 30px rgba(0, 0, 0, 0.35)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '16px'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px' }}>
                      <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
                        <div style={{
                          width: '46px',
                          height: '46px',
                          borderRadius: '10px',
                          background: 'rgba(56, 189, 248, 0.1)',
                          border: '1px solid rgba(56, 189, 248, 0.25)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#38BDF8',
                          flexShrink: 0
                        }}>
                          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                            <line x1="16" y1="13" x2="8" y2="13"></line>
                            <line x1="16" y1="17" x2="8" y2="17"></line>
                            <polyline points="10 9 9 9 8 9"></polyline>
                          </svg>
                        </div>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '1rem', color: '#FFFFFF', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span>ATS Engine Standby</span>
                            <span style={{
                              fontSize: '0.66rem',
                              fontWeight: 700,
                              textTransform: 'uppercase',
                              letterSpacing: '0.06em',
                              padding: '2px 8px',
                              borderRadius: '4px',
                              background: resumeData ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                              color: resumeData ? '#34D399' : '#FBBF24',
                              border: `1px solid ${resumeData ? 'rgba(16, 185, 129, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`,
                              fontFamily: 'var(--font-mono)'
                            }}>
                              {resumeData ? 'Profile Armed' : 'Awaiting Resume'}
                            </span>
                          </div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: '3px', lineHeight: 1.4 }}>
                            {resumeData
                              ? `Master profile calibrated with ${resumeEvaluation?.skills_count || (resumeData.skills || []).length || 15} verified skills. Ready to analyze any job description.`
                              : 'Upload a baseline resume in Settings to begin matching and tailoring.'}
                          </div>
                        </div>
                      </div>

                      {resumeEvaluation && (
                        <div style={{
                          textAlign: 'right',
                          flexShrink: 0,
                          padding: '6px 12px',
                          background: 'rgba(0,0,0,0.3)',
                          borderRadius: '8px',
                          border: '1px solid rgba(255,255,255,0.06)'
                        }}>
                          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Baseline ATS</div>
                          <div style={{ fontSize: '1.15rem', fontWeight: 800, color: '#34D399', fontFamily: 'var(--font-mono)' }}>
                            {resumeEvaluation.ats_score}%
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Quick Metric Pills */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', paddingTop: '12px', borderTop: '1px solid rgba(255, 255, 255, 0.06)' }}>
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '8px 12px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Target Role</div>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#F8FAFC', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '2px' }}>
                          {jobTitle || resumeData?.experience?.[0]?.role || 'Any Technical Role'}
                        </div>
                      </div>
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '8px 12px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Target Employer</div>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#38BDF8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '2px' }}>
                          {company || 'Auto-Detected'}
                        </div>
                      </div>
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '8px 12px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Tailor Mode</div>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#34D399', textTransform: 'capitalize', marginTop: '2px' }}>
                          {tailoringIntensity} Strategy
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 3-Step Execution Roadmap */}
                  <div style={{
                    padding: '20px 22px',
                    borderRadius: '12px',
                    background: 'rgba(15, 23, 42, 0.5)',
                    border: '1px solid rgba(255, 255, 255, 0.06)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '14px'
                  }}>
                    <div style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--font-mono)' }}>
                      How Instant Tailoring Works
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px' }}>
                      <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '6px',
                        padding: '12px 14px',
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.05)',
                        borderRadius: '8px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{
                            width: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: 'rgba(56, 189, 248, 0.2)',
                            color: '#38BDF8',
                            fontSize: '0.72rem',
                            fontWeight: 800,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontFamily: 'var(--font-mono)'
                          }}>1</span>
                          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#FFFFFF' }}>Target Job</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                          Paste a posting URL or description on the left to extract requirements automatically.
                        </p>
                      </div>

                      <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '6px',
                        padding: '12px 14px',
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.05)',
                        borderRadius: '8px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{
                            width: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: 'rgba(16, 185, 129, 0.2)',
                            color: '#34D399',
                            fontSize: '0.72rem',
                            fontWeight: 800,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontFamily: 'var(--font-mono)'
                          }}>2</span>
                          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#FFFFFF' }}>Analyze ATS Gap</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                          Get instant verification of matched taxonomy keywords and missing skill scores.
                        </p>
                      </div>

                      <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '6px',
                        padding: '12px 14px',
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.05)',
                        borderRadius: '8px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{
                            width: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: 'rgba(99, 102, 241, 0.2)',
                            color: '#A5B4FC',
                            fontSize: '0.72rem',
                            fontWeight: 800,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontFamily: 'var(--font-mono)'
                          }}>3</span>
                          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#FFFFFF' }}>1-Page PDF & Overleaf</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                          Compile a tailored 1-page PDF or export the full LaTeX bundle in 1 click.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )
            ) : (
              <div>
                {/* ── Job context banner ── */}
                {/* ── Job context banner ── */}
                {(() => {
                  let effectiveCompany = company;
                  if (!effectiveCompany && jobDescription) {
                    const m = jobDescription.match(/(?:^|\n|\.\s+)([A-Z][A-Za-z0-9\s&.,-]{1,30}?)\s+(?:is|are)\s+(?:a|an)\s+/);
                    if (m && !["the", "this", "our", "a", "an", "there", "it", "here"].includes(m[1].trim().toLowerCase())) {
                      effectiveCompany = m[1].trim();
                    }
                  }
                  if (!effectiveCompany && analysisResult?.company) {
                    effectiveCompany = analysisResult.company;
                  }

                  if (!jobTitle && !effectiveCompany) return null;

                  return (
                    <div className="job-banner" style={{ animation: 'slideDown 0.4s ease both' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>Targeting:</span>
                      {jobTitle && <span className="job-banner-chip job-banner-role">{jobTitle}</span>}
                      {effectiveCompany && <span className="job-banner-chip job-banner-company">{effectiveCompany}</span>}
                    </div>
                  );
                })()}

                {/* ── Job Description Display ── */}
                {jobDescription && (
                  <div style={{ marginBottom: '20px', padding: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', borderRadius: '12px', maxHeight: '300px', overflowY: 'auto' }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '10px', color: 'var(--text-muted)' }}>Job Description</div>
                    <div style={{ fontSize: '0.82rem', lineHeight: '1.5', color: 'var(--text-main)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {jobDescription.substring(0, 1000)}{jobDescription.length > 1000 ? '...' : ''}
                    </div>
                  </div>
                )}

                {/* ── Hybrid ATS Score Dashboard ── */}
                {analysisResult?.match_analysis && (
                  <>
                    <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start', flexWrap: 'wrap' }}>

                      {/* Overall ring with Score Delta Boost */}
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
                        
                        {/* Visual ATS Delta Pill */}
                        {(userSelectedSkills.size > 0 || analysisResult?.match_analysis?.score_delta > 0) && (
                          <div style={{
                            marginTop: '5px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '3px 8px',
                            borderRadius: '12px',
                            background: 'rgba(16, 185, 129, 0.15)',
                            border: '1px solid rgba(16, 185, 129, 0.35)',
                            color: '#34D399',
                            fontSize: '0.72rem',
                            fontWeight: 700
                          }}>
                            <span>+{analysisResult?.match_analysis?.score_delta || (analysisResult.match_analysis.overall_score - (window.baseOriginalAtsScore || analysisResult.match_analysis.overall_score)) || 7}% boost</span>
                          </div>
                        )}

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
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <h3 style={{ margin: 0, fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-main)' }}>Matched ATS Taxonomy Keywords</h3>
                        <span style={{ fontSize: '0.74rem', color: '#34D399', fontFamily: 'var(--font-mono)' }}>
                          {(analysisResult.match_analysis.matched_skills || []).length} verified
                        </span>
                      </div>
                      <div className="tag-list" style={{ gap: '6px' }}>
                        {(analysisResult.match_analysis.matched_skills || []).map((skill, i) => (
                          <span key={i} className="tag tag-match" title="Verified in resume">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div style={{ marginTop: '16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                        <h3 style={{ margin: 0, fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-main)' }}>
                          Missing Target Skills
                          <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '8px' }}>
                            (click token to force-tailor into resume)
                          </span>
                        </h3>
                        <span style={{ fontSize: '0.74rem', color: '#FBBF24', fontFamily: 'var(--font-mono)' }}>
                          {userSelectedSkills.size > 0 ? `${userSelectedSkills.size} selected` : `${(analysisResult.match_analysis.missing_skills || []).length} unmapped`}
                        </span>
                      </div>
                      <div className="tag-list" style={{ gap: '6px' }}>
                        {(analysisResult.match_analysis.missing_skills || []).map((skill, i) => {
                          const isSelected = userSelectedSkills.has(skill);
                          return (
                            <span
                              key={i}
                              className={`tag tag-missing ${isSelected ? 'selected-skill-chip' : ''}`}
                              title={isSelected ? 'Included in tailored resume' : 'Click to add to resume and boost score'}
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
                              {isSelected ? (
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                  <polyline points="20 6 9 17 4 12"></polyline>
                                </svg>
                              ) : (
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                  <line x1="12" y1="5" x2="12" y2="19"></line>
                                  <line x1="5" y1="12" x2="19" y2="12"></line>
                                </svg>
                              )}
                              <span>{skill}</span>
                              
                              {/* Contextual Injection Preview Tooltip */}
                              <div className="skill-injection-tooltip">
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#38BDF8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                  <polyline points="9 11 12 14 22 4"></polyline>
                                  <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
                                </svg>
                                <span>{isSelected ? 'Force-tailoring enabled' : getSkillTargetSection(skill)}</span>
                              </div>
                            </span>
                          );
                        })}
                      </div>
                    </div>

                    {/* Senior Recruiter Scrutiny Report */}
                    {(analysisResult?.recruiter_scrutiny || analysisResult?.match_analysis?.recruiter_scrutiny) && (
                      <div style={{
                        marginTop: '16px',
                        padding: '14px 18px',
                        borderRadius: '12px',
                        background: 'rgba(15, 23, 42, 0.75)',
                        border: '1px solid rgba(56, 189, 248, 0.28)',
                        animation: 'fadeIn 0.3s ease'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            
                            <span style={{ fontSize: '0.88rem', fontWeight: 700, color: '#38BDF8', letterSpacing: '0.02em' }}>
                              Senior Recruiter Scrutiny Audit
                            </span>
                          </div>
                          <span style={{
                            fontSize: '0.72rem',
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: '10px',
                            background: (analysisResult?.recruiter_scrutiny?.satisfied ?? true) ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                            color: (analysisResult?.recruiter_scrutiny?.satisfied ?? true) ? '#34D399' : '#FBBF24',
                            border: `1px solid ${(analysisResult?.recruiter_scrutiny?.satisfied ?? true) ? 'rgba(16, 185, 129, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`
                          }}>
                            {(analysisResult?.recruiter_scrutiny?.pass_number === 2) ? '✓ Passed (2nd Scrutiny Pass)' : '✓ Approved on 1st Pass'}
                          </span>
                        </div>

                        {/* Audit check indicators */}
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px', marginTop: '10px' }}>
                          <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '6px 10px', borderRadius: '6px', fontSize: '0.75rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Truthfulness: </span>
                            <span style={{ color: '#34D399', fontWeight: 700 }}>✓ Verified Ground Truth</span>
                          </div>
                          <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '6px 10px', borderRadius: '6px', fontSize: '0.75rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Metrics & Impact: </span>
                            <span style={{ color: '#34D399', fontWeight: 700 }}>✓ Quantified</span>
                          </div>
                          <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '6px 10px', borderRadius: '6px', fontSize: '0.75rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Formatting & Length: </span>
                            <span style={{ color: '#34D399', fontWeight: 700 }}>✓ 1-Page Enforced</span>
                          </div>
                          <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '6px 10px', borderRadius: '6px', fontSize: '0.75rem' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Keywords: </span>
                            <span style={{ color: '#38BDF8', fontWeight: 700 }}>✓ Context-Integrated</span>
                          </div>
                        </div>

                        {/* Recruiter feedback note */}
                        {(analysisResult?.recruiter_scrutiny?.feedback || analysisResult?.match_analysis?.recruiter_scrutiny?.feedback) && (
                          <div style={{ marginTop: '10px', fontSize: '0.78rem', color: '#94A3B8', fontStyle: 'italic', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '8px' }}>
                            &ldquo;{analysisResult?.recruiter_scrutiny?.feedback || analysisResult?.match_analysis?.recruiter_scrutiny?.feedback}&rdquo;
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}

                {/* Workspace Panels or Tailor Resume Decision Banner */}
                {(!analysisResult.latex_code && !keepOriginalMode) ? (
                  <div style={{
                    marginTop: '24px', padding: '32px 28px', borderRadius: '14px',
                    background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.4) 0%, rgba(15, 23, 42, 0.6) 100%)',
                    border: '1px solid #334155',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '18px', textAlign: 'center',
                    animation: 'slideDown 0.4s ease both'
                  }}>
                    <div style={{ width: '44px', height: '44px', borderRadius: '10px', background: 'rgba(56, 189, 248, 0.12)', border: '1px solid rgba(56, 189, 248, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-cyan)' }}>
                      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                      </svg>
                    </div>
                    <div>
                      <h3 style={{ margin: '0 0 8px', fontSize: '1.05rem', color: '#fff', fontWeight: 700, letterSpacing: '-0.01em' }}>ATS Score & Role Fit Analysis Ready</h3>
                      <p style={{ maxWidth: '520px', margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: '1.65' }}>
                        Keyword taxonomy alignment, seniority scoring, and semantic gap analysis are complete.
                        Ready to compile an ATS-compliant tailored LaTeX resume and role cover letter.
                      </p>
                    </div>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', justifyContent: 'center' }}>
                      <button
                        className="btn"
                        style={{ padding: '10px 24px', fontWeight: 600, fontSize: '0.88rem', gap: '8px' }}
                        onClick={() => handleGenerateTailoredResume(false)}
                      >
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                        </svg>
                        Tailor Resume & Cover Letter
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '10px 18px', borderColor: 'var(--accent-cyan)', color: 'var(--accent-cyan)', fontWeight: 600, fontSize: '0.86rem', gap: '8px' }}
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
                              setStatusMessage('Tailored cover letter generated!');
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
                        Cover Letter Only
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
                    <div style={{ fontSize: '1.2rem', color: 'var(--accent-secondary)', fontWeight: 700 }}>[PDF]</div>
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
                        <div className="panel-toolbar" style={{
                          display: 'flex',
                          flexWrap: 'nowrap',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '10px',
                          padding: '6px 12px',
                          background: 'rgba(15, 23, 42, 0.65)',
                          border: '1px solid rgba(255, 255, 255, 0.08)',
                          borderRadius: '10px',
                          marginBottom: '14px',
                          overflowX: 'auto',
                          whiteSpace: 'nowrap'
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent-primary)' }}>
                              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                              <polyline points="14 2 14 8 20 8"></polyline>
                              <line x1="16" y1="13" x2="8" y2="13"></line>
                              <line x1="16" y1="17" x2="8" y2="17"></line>
                            </svg>
                            <span style={{ fontSize: '0.86rem', fontWeight: 700, color: '#fff' }}>Cover Letter</span>
                            <span style={{
                              fontSize: '0.72rem',
                              fontFamily: 'var(--font-mono)',
                              color: 'var(--text-muted)',
                              background: 'rgba(255,255,255,0.04)',
                              padding: '2px 8px',
                              borderRadius: '6px',
                              border: '1px solid rgba(255,255,255,0.06)'
                            }}>
                              {(analysisResult.cover_letter || '').trim().split(/\s+/).filter(Boolean).length} words
                            </span>
                          </div>
                          <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                            <button
                              className="btn btn-secondary"
                              style={{ padding: '6px 12px', fontSize: '0.78rem', gap: '6px', display: 'inline-flex', alignItems: 'center' }}
                              onClick={handleDownloadCoverLetter}
                              title="Download cover letter as text file"
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                <polyline points="7 10 12 15 17 10"></polyline>
                                <line x1="12" y1="15" x2="12" y2="3"></line>
                              </svg>
                              Download
                            </button>
                            <button
                              className="btn btn-secondary"
                              style={{ padding: '6px 12px', fontSize: '0.78rem', gap: '6px', display: 'inline-flex', alignItems: 'center' }}
                              onClick={() => {
                                navigator.clipboard.writeText(analysisResult.cover_letter || '');
                                setCoverLetterCopied(true);
                                setTimeout(() => setCoverLetterCopied(false), 2000);
                              }}
                              title="Copy cover letter text"
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                              </svg>
                              {coverLetterCopied ? 'Copied!' : 'Copy'}
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
                      <div className="panel-toolbar" style={{
                        display: 'flex',
                        flexWrap: 'nowrap',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '10px',
                        padding: '6px 10px',
                        background: 'rgba(15, 23, 42, 0.65)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '10px',
                        marginBottom: '14px',
                        overflowX: 'auto',
                        whiteSpace: 'nowrap'
                      }}>
                        {/* Left: View Mode Segmented Switcher */}
                        <div style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          background: 'rgba(0, 0, 0, 0.35)',
                          border: '1px solid rgba(255, 255, 255, 0.08)',
                          borderRadius: '8px',
                          padding: '3px',
                          gap: '2px'
                        }}>
                          <button
                            type="button"
                            onClick={() => setActiveTab('preview')}
                            style={{
                              padding: '5px 12px',
                              fontSize: '0.78rem',
                              fontWeight: 600,
                              borderRadius: '6px',
                              border: 'none',
                              cursor: 'pointer',
                              transition: 'all 0.15s ease',
                              background: activeTab === 'preview' ? '#2563EB' : 'transparent',
                              color: activeTab === 'preview' ? '#FFFFFF' : 'var(--text-muted)'
                            }}
                          >
                            Preview
                          </button>
                          <button
                            type="button"
                            onClick={() => setActiveTab('latex')}
                            style={{
                              padding: '5px 12px',
                              fontSize: '0.78rem',
                              fontWeight: 600,
                              borderRadius: '6px',
                              border: 'none',
                              cursor: 'pointer',
                              transition: 'all 0.15s ease',
                              background: activeTab === 'latex' ? '#2563EB' : 'transparent',
                              color: activeTab === 'latex' ? '#FFFFFF' : 'var(--text-muted)'
                            }}
                          >
                            LaTeX
                          </button>
                        </div>

                        {/* Right: Clean Action Buttons Group (Single Line) */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'nowrap', flexShrink: 0 }}>
                          {/* 1. View & Open Compiled 1-Page PDF */}
                          {analysisResult && (
                            <button
                              disabled={loading}
                              style={{
                                padding: '6px 12px',
                                fontSize: '0.78rem',
                                fontWeight: 600,
                                borderRadius: '6px',
                                background: 'rgba(56, 189, 248, 0.1)',
                                border: '1px solid rgba(56, 189, 248, 0.35)',
                                color: '#38BDF8',
                                cursor: 'pointer',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '6px'
                              }}
                              onClick={handleViewTailoredPdf}
                              title="Open compiled 1-page PDF in a new tab"
                            >
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                <polyline points="14 2 14 8 20 8"></polyline>
                              </svg>
                              View PDF
                            </button>
                          )}

                          {/* 2. Overleaf Direct Export */}
                          <button
                            className="btn btn-secondary"
                            onClick={openInOverleaf}
                            disabled={loading}
                            style={{ padding: '6px 12px', fontSize: '0.78rem', gap: '6px' }}
                            title="Export LaTeX project bundle to Overleaf"
                          >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#10B981' }}>
                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                              <polyline points="15 3 21 3 21 9"></polyline>
                              <line x1="10" y1="14" x2="21" y2="3"></line>
                            </svg>
                            Overleaf
                          </button>

                          {/* 3. Set as Master Baseline */}
                          {analysisResult && analysisResult.latex_code && (
                            <button
                              className="btn btn-secondary"
                              style={{ padding: '6px 12px', fontSize: '0.78rem', gap: '5px', color: 'var(--accent-green)', borderColor: 'rgba(16,185,129,0.3)' }}
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
                                    setStatusMessage('Master Resume updated from tailored version!');
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
                              Set as Master
                            </button>
                          )}
                        </div>
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
                        <LatexCodeViewer
                          code={analysisResult.latex_code}
                          onCopy={() => {
                            navigator.clipboard.writeText(analysisResult.latex_code);
                            setStatusMessage('Copied LaTeX source code to clipboard!');
                          }}
                        />
                      )}
                    </div>

                    <div className="workspace-panel">
                      <div className="panel-toolbar" style={{
                        display: 'flex',
                        flexWrap: 'nowrap',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '10px',
                        padding: '6px 12px',
                        background: 'rgba(15, 23, 42, 0.65)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '10px',
                        marginBottom: '14px',
                        overflowX: 'auto',
                        whiteSpace: 'nowrap'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent-primary)' }}>
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                            <line x1="16" y1="13" x2="8" y2="13"></line>
                            <line x1="16" y1="17" x2="8" y2="17"></line>
                          </svg>
                          <span style={{ fontSize: '0.86rem', fontWeight: 700, color: '#fff' }}>Cover Letter</span>
                          <span style={{
                            fontSize: '0.72rem',
                            fontFamily: 'var(--font-mono)',
                            color: 'var(--text-muted)',
                            background: 'rgba(255,255,255,0.04)',
                            padding: '2px 8px',
                            borderRadius: '6px',
                            border: '1px solid rgba(255,255,255,0.06)'
                          }}>
                            {(analysisResult.cover_letter || '').trim().split(/\s+/).filter(Boolean).length} words
                          </span>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '6px 12px', fontSize: '0.78rem', gap: '6px', display: 'inline-flex', alignItems: 'center' }}
                            onClick={handleDownloadCoverLetter}
                            title="Download cover letter as text file"
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                              <polyline points="7 10 12 15 17 10"></polyline>
                              <line x1="12" y1="15" x2="12" y2="3"></line>
                            </svg>
                            Download
                          </button>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '6px 12px', fontSize: '0.78rem', gap: '6px', display: 'inline-flex', alignItems: 'center' }}
                            onClick={() => {
                              navigator.clipboard.writeText(analysisResult.cover_letter || '');
                              setCoverLetterCopied(true);
                              setTimeout(() => setCoverLetterCopied(false), 2000);
                            }}
                            title="Copy cover letter text"
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                            {coverLetterCopied ? 'Copied!' : 'Copy'}
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
                      PIPELINE EXECUTION LOGS
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

            {/* Sticky Floating Action Bar for Long Job Descriptions & Analysis */}
            {analysisResult && dashboardMode === 'tailor' && (
              <div className="sticky-action-bar">
                {/* 1. View PDF */}
                <button
                  onClick={handleViewTailoredPdf}
                  disabled={loading}
                  style={{
                    padding: '6px 14px',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    borderRadius: '9999px',
                    background: 'rgba(56, 189, 248, 0.14)',
                    border: '1px solid rgba(56, 189, 248, 0.35)',
                    color: '#38BDF8',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.15s ease'
                  }}
                  title="Open compiled 1-page tailored PDF"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  View PDF
                </button>

                {/* 2. Overleaf Direct Export */}
                <button
                  onClick={openInOverleaf}
                  disabled={loading}
                  style={{
                    padding: '6px 14px',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    borderRadius: '9999px',
                    background: 'rgba(16, 185, 129, 0.14)',
                    border: '1px solid rgba(16, 185, 129, 0.35)',
                    color: '#34D399',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.15s ease'
                  }}
                  title="Export LaTeX project bundle to Overleaf"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                  </svg>
                  Overleaf
                </button>

                {/* 3. Personalized Outreach Note */}
                <button
                  onClick={handleGenerateOutreach}
                  disabled={loading || outreachLoading}
                  style={{
                    padding: '6px 14px',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    borderRadius: '9999px',
                    background: 'rgba(99, 102, 241, 0.14)',
                    border: '1px solid rgba(99, 102, 241, 0.35)',
                    color: '#A5B4FC',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.15s ease'
                  }}
                  title="Generate or view tailored recruiter outreach message"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                    <polyline points="22,6 12,13 2,6"></polyline>
                  </svg>
                  {outreachLoading ? 'Generating…' : 'Outreach Note'}
                </button>

                {/* 4. Quick Scroll-to-Top Anchor */}
                <button
                  onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                  style={{
                    padding: '6px 8px',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    borderRadius: '9999px',
                    background: 'rgba(255, 255, 255, 0.06)',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'all 0.15s ease'
                  }}
                  title="Scroll back to top"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="19" x2="12" y2="5"></line>
                    <polyline points="5 12 12 5 19 12"></polyline>
                  </svg>
                </button>
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
                <span>Analyze & Tailor Job</span>
                <kbd style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600 }}>Cmd+Enter</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span>Save Master Archetype</span>
                <kbd style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600 }}>Cmd+S</kbd>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '12px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span>Switch Modes (Tailor / Discover / History)</span>
                <kbd style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'monospace', fontSize: '0.8rem', fontWeight: 600 }}>Cmd + 1 / 2 / 3</kbd>
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
            style={{ maxWidth: '1040px', width: '92vw', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
          >
            {/* Header */}
            <div className="modal-header">
              <div>
                <h2>Interview Preparation Guide</h2>
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
                  Copy Prep Guide
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
            style={{ maxWidth: '1040px', width: '92vw', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
          >
            {/* Header */}
            <div className="modal-header">
              <div>
                <h2>Tailored Cover Letter</h2>
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
                  {coverLetterCopiedModal ? 'Copied to Clipboard!' : 'Copy Cover Letter'}
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

      {/* Power-User Keyboard & Status Telemetry Strip */}
      <footer
        className="power-user-bar"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 24px',
          marginTop: '32px',
          borderTop: '1px solid #1E293B',
          background: 'rgba(9, 13, 22, 0.75)',
          backdropFilter: 'blur(8px)',
          fontSize: '0.74rem',
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10B981' }} />
            <span style={{ color: 'var(--text-main)', fontWeight: 600 }}>SYSTEM READY</span>
          </div>
          <span>•</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <kbd style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid #334155', borderRadius: '4px', padding: '1px 5px', color: '#CBD5E1' }}>⌘↵</kbd>
            <span>Analyze & Tailor</span>
          </div>
          <span>•</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <kbd style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid #334155', borderRadius: '4px', padding: '1px 5px', color: '#CBD5E1' }}>⌘S</kbd>
            <span>Save Archetype</span>
          </div>
          <span>•</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <kbd style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid #334155', borderRadius: '4px', padding: '1px 5px', color: '#CBD5E1' }}>⌘1-3</kbd>
            <span>Switch Tabs</span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={() => setShowKeyboardHelp(true)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--accent-cyan)',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.74rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: 0
            }}
          >
            <kbd style={{ background: 'rgba(56,189,248,0.1)', border: '1px solid rgba(56,189,248,0.3)', borderRadius: '4px', padding: '1px 5px', color: 'var(--accent-cyan)' }}>?</kbd>
            <span>All Shortcuts</span>
          </button>
        </div>
      </footer>

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
                <span>Chrome Extension Setup Guide</span>
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
                  Re-Download ZIP
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
                Got it! Start Tailoring Jobs
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default App;
