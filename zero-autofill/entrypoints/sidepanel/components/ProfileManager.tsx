import React, { useState, useEffect } from 'react';
import { getProfile, saveProfile, getSettings, CandidateProfile } from '../../../modules/storage/db';

export function ProfileManager() {
  const [profile, setProfileState] = useState<CandidateProfile>({
    personal: {
      firstName: '',
      lastName: '',
      email: '',
      phone: '',
      location: '',
      linkedin: '',
      github: '',
      portfolio: ''
    },
    eeo: {
      workAuth: 'Yes',
      sponsorship: 'No',
      gender: 'Decline to self-identify',
      race: 'Decline to self-identify',
      veteran: 'No',
      disability: 'No'
    },
    workExperience: [
      { company: '', title: '', startDate: '', endDate: '', description: '' }
    ],
    education: [
      { institution: '', degree: '', fieldOfStudy: '', graduationYear: '' }
    ],
    skills: [],
    customQA: [],
    rawResumeText: '',
    pdfBase64: ''
  });

  const [skillsInput, setSkillsInput] = useState('');
  const [savedStatus, setSavedStatus] = useState('');
  const [statusType, setStatusType] = useState<'success' | 'error' | 'info'>('info');
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    getProfile().then((p) => {
      if (p) {
        setProfileState(p);
        setSkillsInput(p.skills?.join(', ') || '');
      }
    });
  }, []);

  const syncFromBackend = async () => {
    setIsSyncing(true);
    setStatusType('info');
    setSavedStatus('Connecting to App Backend...');
    try {
      const settings = await getSettings();
      const baseUrl = (settings.backendBaseUrl || 'http://127.0.0.1:8000').replace(/\/+$/, '');
      const headers: Record<string, string> = { 'Accept': 'application/json' };
      if (settings.backendAuthToken) {
        const token = settings.backendAuthToken.trim();
        headers['Authorization'] = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
      }

      // Try /get_session_resume first, then fallback to /user/me
      let res = await fetch(`${baseUrl}/get_session_resume`, { headers });
      let contentType = res.headers.get('content-type') || '';

      if (!contentType.includes('application/json')) {
        // Test /user/me
        const userRes = await fetch(`${baseUrl}/user/me`, { headers });
        const userContentType = userRes.headers.get('content-type') || '';
        if (userRes.ok && userContentType.includes('application/json')) {
          res = userRes;
          contentType = userContentType;
        }
      }

      if (!contentType.includes('application/json')) {
        setStatusType('error');
        setSavedStatus(
          `⚠️ Backend at "${baseUrl}" returned an HTML page (SPA / 404) instead of JSON API. Please check Backend Base URL in Settings.`
        );
        return;
      }

      if (!res.ok) {
        setStatusType('error');
        setSavedStatus(`⚠️ Backend request failed with HTTP ${res.status}. Check token or server logs.`);
        return;
      }

      const data = await res.json();
      const resumePayload = data.data || data.resume_data || data;

      if (resumePayload && (resumePayload.name || resumePayload.email || resumePayload.experience || resumePayload.skills)) {
        const d = resumePayload;
        const nameParts = (d.name || '').trim().split(/\s+/);
        const fName = nameParts[0] || '';
        const lName = nameParts.slice(1).join(' ') || '';
        const fetchedSkills = Array.isArray(d.skills)
          ? d.skills
          : Object.values(d.skills || {}).flat() as string[];

        const linksList = Array.isArray(d.links) ? d.links : [];
        const linkedinUrl = linksList.find((l: string) => l.toLowerCase().includes('linkedin')) || d.linkedin || '';
        const githubUrl = linksList.find((l: string) => l.toLowerCase().includes('github')) || d.github || '';
        const portfolioUrl = linksList.find((l: string) => !l.toLowerCase().includes('linkedin') && !l.toLowerCase().includes('github')) || d.portfolio || '';

        const workExp = Array.isArray(d.experience) ? d.experience.map((exp: any) => ({
          company: exp.company || '',
          title: exp.role || exp.title || '',
          startDate: exp.start_date || exp.startDate || '',
          endDate: exp.end_date || exp.endDate || '',
          description: Array.isArray(exp.description) ? exp.description.join(' ') : (exp.description || '')
        })) : [];

        const eduList = Array.isArray(d.education) ? d.education.map((edu: any) => ({
          institution: edu.institution || edu.school || '',
          degree: edu.degree || '',
          fieldOfStudy: edu.field_of_study || edu.fieldOfStudy || '',
          graduationYear: edu.graduation_date || edu.graduationYear || ''
        })) : [];

        const synced: CandidateProfile = {
          ...profile,
          personal: {
            firstName: fName || profile.personal.firstName,
            lastName: lName || profile.personal.lastName,
            email: d.email || profile.personal.email,
            phone: d.phone || profile.personal.phone,
            location: d.location || profile.personal.location,
            linkedin: linkedinUrl || profile.personal.linkedin,
            github: githubUrl || profile.personal.github,
            portfolio: portfolioUrl || profile.personal.portfolio
          },
          workExperience: workExp.length ? workExp : profile.workExperience,
          education: eduList.length ? eduList : profile.education,
          skills: fetchedSkills.length ? fetchedSkills : profile.skills,
          rawResumeText: typeof d === 'string' ? d : JSON.stringify(d, null, 2),
          pdfBase64: d.pdf_base64 || profile.pdfBase64 || ''
        };

        setProfileState(synced);
        setSkillsInput(synced.skills.join(', '));
        await saveProfile(synced);

        // Also save to chrome.storage for content scripts
        try {
          chrome.storage.local.set({
            resumeData: d,
            userToken: settings.backendAuthToken || ''
          });
        } catch (e) {}

        setStatusType('success');
        setSavedStatus(`⚡ Successfully synced candidate profile for "${synced.personal.firstName || 'Candidate'}"!`);
      } else {
        setStatusType('error');
        setSavedStatus('⚠️ Backend returned no uploaded resume data. Upload resume on site or fill form manually.');
      }
    } catch (err: any) {
      setStatusType('error');
      setSavedStatus(`❌ Connection error: ${err.message || err}`);
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSavedStatus(''), 6000);
    }
  };

  const handleSave = async () => {
    const updated = {
      ...profile,
      skills: skillsInput.split(',').map((s) => s.trim()).filter(Boolean)
    };
    await saveProfile(updated);
    try {
      chrome.storage.local.set({
        eeoProfile: updated.eeo,
        resumeData: {
          name: `${updated.personal.firstName} ${updated.personal.lastName}`.trim(),
          email: updated.personal.email,
          phone: updated.personal.phone,
          location: updated.personal.location,
          links: [updated.personal.linkedin, updated.personal.github, updated.personal.portfolio].filter(Boolean),
          skills: updated.skills,
          pdf_base64: updated.pdfBase64
        }
      });
    } catch (e) {}
    setStatusType('success');
    setSavedStatus('✅ Profile saved successfully!');
    setTimeout(() => setSavedStatus(''), 3000);
  };

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2 gap-2">
        <h2 className="text-sm font-bold text-sky-400">👤 Candidate Profile & EEO</h2>
        <div className="flex gap-2">
          <button
            onClick={syncFromBackend}
            disabled={isSyncing}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold px-2.5 py-1 rounded shadow transition text-[11px]"
          >
            {isSyncing ? 'Syncing...' : '⚡ Sync Backend'}
          </button>
          <button
            onClick={handleSave}
            className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-3 py-1 rounded shadow transition text-[11px]"
          >
            Save Profile
          </button>
        </div>
      </div>

      {savedStatus && (
        <div
          className={`p-2.5 rounded text-xs leading-tight ${
            statusType === 'success'
              ? 'bg-emerald-950 border border-emerald-800 text-emerald-300'
              : statusType === 'error'
              ? 'bg-rose-950 border border-rose-800 text-rose-300'
              : 'bg-sky-950 border border-sky-800 text-sky-300'
          }`}
        >
          {savedStatus}
        </div>
      )}

      {/* Personal Info */}
      <div className="space-y-2 bg-slate-900 p-3 rounded border border-slate-800">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">Personal Information</h3>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] text-slate-500">First Name</label>
            <input
              type="text"
              value={profile.personal.firstName}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, firstName: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Last Name</label>
            <input
              type="text"
              value={profile.personal.lastName}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, lastName: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] text-slate-500">Email</label>
            <input
              type="email"
              value={profile.personal.email}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, email: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Phone</label>
            <input
              type="tel"
              value={profile.personal.phone}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, phone: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
        </div>

        <div>
          <label className="block text-[10px] text-slate-500">Location (City, Country)</label>
          <input
            type="text"
            value={profile.personal.location}
            onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, location: e.target.value } })}
            placeholder="e.g. San Francisco, CA"
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
          />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="block text-[10px] text-slate-500">LinkedIn URL</label>
            <input
              type="url"
              value={profile.personal.linkedin}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, linkedin: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">GitHub URL</label>
            <input
              type="url"
              value={profile.personal.github}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, github: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Portfolio</label>
            <input
              type="url"
              value={profile.personal.portfolio}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, portfolio: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            />
          </div>
        </div>
      </div>

      {/* EEO & Work Authorization */}
      <div className="space-y-2 bg-slate-900 p-3 rounded border border-slate-800">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">⚖️ Work Auth & EEO Preferences</h3>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] text-slate-500">US Work Authorized</label>
            <select
              value={profile.eeo?.workAuth || 'Yes'}
              onChange={(e) => setProfileState({ ...profile, eeo: { ...(profile.eeo || { workAuth: 'Yes', sponsorship: 'No' }), workAuth: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            >
              <option value="Yes">Yes</option>
              <option value="No">No</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Visa Sponsorship Needed</label>
            <select
              value={profile.eeo?.sponsorship || 'No'}
              onChange={(e) => setProfileState({ ...profile, eeo: { ...(profile.eeo || { workAuth: 'Yes', sponsorship: 'No' }), sponsorship: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
            >
              <option value="No">No</option>
              <option value="Yes">Yes</option>
            </select>
          </div>
        </div>
      </div>

      {/* Skills */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-1">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">Skills (Comma Separated)</h3>
        <input
          type="text"
          value={skillsInput}
          onChange={(e) => setSkillsInput(e.target.value)}
          placeholder="Python, React, TypeScript, Docker, SQL, AWS..."
          className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none text-slate-200"
        />
      </div>

      {/* Raw Resume Text */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-1">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">Raw Resume Summary Text</h3>
        <textarea
          rows={3}
          value={profile.rawResumeText}
          onChange={(e) => setProfileState({ ...profile, rawResumeText: e.target.value })}
          placeholder="Paste plain text resume content for AI match scoring and answers..."
          className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none resize-none text-slate-200"
        />
      </div>
    </div>
  );
}
