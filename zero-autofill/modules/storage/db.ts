import Dexie, { type Table } from 'dexie';

export interface CandidateProfile {
  id?: number;
  personal: {
    firstName: string;
    lastName: string;
    email: string;
    phone: string;
    location: string;
    linkedin: string;
    github: string;
    portfolio: string;
  };
  eeo?: {
    workAuth: string;
    sponsorship: string;
    gender?: string;
    race?: string;
    veteran?: string;
    disability?: string;
  };
  workExperience: Array<{
    company: string;
    title: string;
    startDate: string;
    endDate: string;
    description: string;
  }>;
  education: Array<{
    institution?: string;
    school?: string;
    degree: string;
    fieldOfStudy?: string;
    graduationYear?: string;
  }>;
  skills: string[];
  customQA: Array<{
    question: string;
    answer: string;
  }>;
  rawResumeText: string;
  pdfBase64?: string;
}

export interface JobApplication {
  id?: number;
  company: string;
  position: string;
  jobUrl: string;
  status: 'Saved' | 'Applied' | 'Interviewing' | 'Offer' | 'Rejected';
  appliedDate: string;
  jobDescriptionText: string;
  matchScore?: number;
  filledFieldsCount?: number;
}

export interface AISettings {
  provider: 'window.ai' | 'ollama' | 'gemini' | 'openai' | 'backend';
  apiKey?: string;
  localEndpoint?: string;
  localModel?: string;
  backendBaseUrl?: string;
  backendAuthToken?: string;
  maxYears?: number;
  blacklistKeywords?: string;
}

export class ZeroAutofillDB extends Dexie {
  profile!: Table<CandidateProfile, number>;
  applications!: Table<JobApplication, number>;
  settings!: Table<AISettings & { id: number }, number>;

  constructor() {
    super('ZeroAutofillDB');
    this.version(1).stores({
      profile: '++id',
      applications: '++id, company, position, status, appliedDate',
      settings: 'id'
    });
  }
}

export const db = new ZeroAutofillDB();

export async function getProfile(): Promise<CandidateProfile | undefined> {
  const profiles = await db.profile.toArray();
  if (profiles.length > 0) {
    return profiles[0];
  }

  try {
    const settings = await getSettings();
    const baseUrl = (settings.backendBaseUrl || 'http://127.0.0.1:8000').replace(/\/+$/, '');
    const headers: Record<string, string> = {};
    if (settings.backendAuthToken) {
      const token = settings.backendAuthToken.trim();
      headers['Authorization'] = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
    }
    const res = await fetch(`${baseUrl}/get_session_resume`, { headers });
    const contentType = res.headers.get('content-type') || '';
    if (res.ok && contentType.includes('application/json')) {
      const data = await res.json();
      if (data && data.data) {
        const d = data.data;
        const linksList = Array.isArray(d.links) ? d.links : [];
        const linkedinUrl = linksList.find((l: string) => l.toLowerCase().includes('linkedin')) || d.linkedin || '';
        const githubUrl = linksList.find((l: string) => l.toLowerCase().includes('github')) || d.github || '';
        const portfolioUrl = linksList.find((l: string) => !l.toLowerCase().includes('linkedin') && !l.toLowerCase().includes('github')) || d.portfolio || '';

        const workExperience = Array.isArray(d.experience) ? d.experience.map((exp: any) => ({
          company: exp.company || '',
          title: exp.role || exp.title || '',
          startDate: exp.start_date || exp.startDate || '',
          endDate: exp.end_date || exp.endDate || '',
          description: Array.isArray(exp.description) ? exp.description.join(' ') : (exp.description || '')
        })) : [];

        const education = Array.isArray(d.education) ? d.education.map((edu: any) => ({
          institution: edu.institution || edu.school || '',
          school: edu.institution || edu.school || '',
          degree: edu.degree || '',
          fieldOfStudy: edu.field_of_study || edu.fieldOfStudy || '',
          graduationYear: edu.graduation_date || edu.graduationYear || ''
        })) : [];

        const fetchedProfile: CandidateProfile = {
          personal: {
            firstName: d.name?.split(' ')[0] || '',
            lastName: d.name?.split(' ').slice(1).join(' ') || '',
            email: d.email || '',
            phone: d.phone || '',
            location: d.location || '',
            linkedin: linkedinUrl,
            github: githubUrl,
            portfolio: portfolioUrl
          },
          eeo: {
            workAuth: 'Yes',
            sponsorship: 'No',
            gender: 'Decline to self-identify',
            race: 'Decline to self-identify',
            veteran: 'No',
            disability: 'No'
          },
          workExperience,
          education,
          skills: Array.isArray(d.skills) ? d.skills : Object.values(d.skills || {}).flat() as string[],
          customQA: [],
          rawResumeText: JSON.stringify(d, null, 2),
          pdfBase64: d.pdf_base64 || ''
        };
        await saveProfile(fetchedProfile);
        return fetchedProfile;
      }
    }
  } catch (e) {
    console.log('Backend profile sync notice:', e);
  }

  return undefined;
}

export async function saveProfile(profileData: CandidateProfile): Promise<number> {
  const profiles = await db.profile.toArray();
  if (profiles.length > 0 && profiles[0].id) {
    await db.profile.update(profiles[0].id, profileData);
    return profiles[0].id;
  } else {
    return await db.profile.add(profileData);
  }
}

export async function getSettings(): Promise<AISettings> {
  const s = await db.settings.get(1);
  return s || {
    provider: 'backend',
    backendBaseUrl: 'http://127.0.0.1:8000',
    backendAuthToken: '',
    localEndpoint: 'http://localhost:11434',
    localModel: 'llama3.2',
    maxYears: 5,
    blacklistKeywords: 'Senior, Lead, Manager, Director'
  };
}

export async function saveSettings(settingsData: AISettings): Promise<void> {
  await db.settings.put({ ...settingsData, id: 1 });
}
