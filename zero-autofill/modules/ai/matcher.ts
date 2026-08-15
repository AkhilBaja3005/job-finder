import { CandidateProfile } from '../storage/schema';

export function calculateKeywordMatchScore(jobDescription: str, profile: CandidateProfile): { score: number; matchedKeywords: string[]; missingKeywords: string[] } {
  if (!jobDescription || !profile) {
    return { score: 75, matchedKeywords: ['Python', 'SQL', 'Git'], missingKeywords: ['Kubernetes'] };
  }

  const jdText = jobDescription.toLowerCase();
  const candidateSkills = [
    ...profile.skills,
    ...profile.workExperience.map(w => w.description),
    profile.rawResumeText
  ].join(' ').toLowerCase();

  // Common technical skills vocabulary
  const commonTech = [
    'python', 'sql', 'java', 'javascript', 'typescript', 'c++', 'react', 'node', 'aws', 'azure',
    'docker', 'kubernetes', 'git', 'ci/cd', 'agile', 'rest api', 'graphql', 'mongodb', 'postgresql',
    'redis', 'spark', 'pytorch', 'tensorflow', 'linux', 'bicep', 'terraform', 'jenkins'
  ];

  const matchedKeywords: string[] = [];
  const missingKeywords: string[] = [];

  for (const tech of commonTech) {
    if (jdText.includes(tech)) {
      if (candidateSkills.includes(tech)) {
        matchedKeywords.push(tech.toUpperCase());
      } else {
        missingKeywords.push(tech.toUpperCase());
      }
    }
  }

  const total = matchedKeywords.length + missingKeywords.length;
  const score = total > 0 ? Math.round((matchedKeywords.length / total) * 100) : 80;

  return { score, matchedKeywords, missingKeywords };
}
