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
    workExperience: [
      { company: '', title: '', startDate: '', endDate: '', description: '' }
    ],
    education: [
      { institution: '', degree: '', fieldOfStudy: '', graduationYear: '' }
    ],
    skills: [],
    customQA: [],
    rawResumeText: ''
  });

  const [skillsInput, setSkillsInput] = useState('');
  const [savedStatus, setSavedStatus] = useState('');
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
    setSavedStatus('Connecting to App Backend...');
    try {
      const settings = await getSettings();
      const baseUrl = (settings.backendBaseUrl || 'https://www.job-finder.space').replace(/\/+$/, '');
      const headers: Record<string, string> = {};
      if (settings.backendAuthToken) {
        const token = settings.backendAuthToken.trim();
        headers['Authorization'] = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
      }
      const res = await fetch(`${baseUrl}/get_session_resume`, { headers });
      if (res.ok) {
        const data = await res.json();
        if (data && data.data) {
          const d = data.data;
          const nameParts = (d.name || '').trim().split(' ');
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
            personal: {
              firstName: fName,
              lastName: lName,
              email: d.email || '',
              phone: d.phone || '',
              location: d.location || '',
              linkedin: linkedinUrl,
              github: githubUrl,
              portfolio: portfolioUrl
            },
            workExperience: workExp,
            education: eduList,
            skills: fetchedSkills,
            customQA: [],
            rawResumeText: JSON.stringify(d, null, 2)
          };

          setProfileState(synced);
          setSkillsInput(fetchedSkills.join(', '));
          await saveProfile(synced);
          setSavedStatus('⚡ Successfully synced candidate profile from App Backend!');
        } else {
          setSavedStatus('⚠️ Backend returned no uploaded resume data. Upload resume on site first.');
        }
      } else {
        setSavedStatus(`⚠️ Backend request failed (${res.status}) for ${baseUrl}/get_session_resume.`);
      }
    } catch (err: any) {
      setSavedStatus(`❌ Could not connect to backend: ${err.message || err}`);
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSavedStatus(''), 4000);
    }
  };

  const handleSave = async () => {
    const updated = {
      ...profile,
      skills: skillsInput.split(',').map(s => s.trim()).filter(Boolean)
    };
    await saveProfile(updated);
    setSavedStatus('Profile saved successfully!');
    setTimeout(() => setSavedStatus(''), 3000);
  };

  return (
    <div className="p-4 space-y-4 text-xs text-slate-200">
      <div className="flex justify-between items-center border-b border-slate-800 pb-2 gap-2">
        <h2 className="text-sm font-bold text-sky-400">👤 Candidate Profile</h2>
        <div className="flex gap-2">
          <button
            onClick={syncFromBackend}
            disabled={isSyncing}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold px-2.5 py-1 rounded shadow transition text-[11px]"
          >
            {isSyncing ? 'Syncing...' : '⚡ Sync from Backend'}
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
        <div className="p-2 bg-emerald-950 border border-emerald-800 text-emerald-300 rounded text-center">
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
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Last Name</label>
            <input
              type="text"
              value={profile.personal.lastName}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, lastName: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
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
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Phone</label>
            <input
              type="tel"
              value={profile.personal.phone}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, phone: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
          </div>
        </div>

        <div>
          <label className="block text-[10px] text-slate-500">Location (City, Country)</label>
          <input
            type="text"
            value={profile.personal.location}
            onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, location: e.target.value } })}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
          />
        </div>

        <div>
          <label className="block text-[10px] text-slate-500">LinkedIn URL</label>
          <input
            type="url"
            value={profile.personal.linkedin}
            onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, linkedin: e.target.value } })}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] text-slate-500">GitHub URL</label>
            <input
              type="url"
              value={profile.personal.github}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, github: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500">Portfolio URL</label>
            <input
              type="url"
              value={profile.personal.portfolio}
              onChange={(e) => setProfileState({ ...profile, personal: { ...profile.personal, portfolio: e.target.value } })}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
            />
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
          placeholder="Python, React, TypeScript, Docker, SQL..."
          className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none"
        />
      </div>

      {/* Raw Resume Text */}
      <div className="bg-slate-900 p-3 rounded border border-slate-800 space-y-1">
        <h3 className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">Raw Resume Summary Text</h3>
        <textarea
          rows={4}
          value={profile.rawResumeText}
          onChange={(e) => setProfileState({ ...profile, rawResumeText: e.target.value })}
          placeholder="Paste plain text resume content for AI match scoring and answers..."
          className="w-full bg-slate-950 border border-slate-800 rounded px-2 py-1 focus:border-sky-500 outline-none resize-none"
        />
      </div>
    </div>
  );
}
