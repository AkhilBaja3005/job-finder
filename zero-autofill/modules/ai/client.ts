import { CandidateProfile, AISettings } from '../storage/db';

export async function generateFieldAnswer(
  question: string,
  profile: CandidateProfile,
  settings: AISettings
): Promise<string> {
  const systemPrompt = `You are an AI assistant answering job application screening questions.
Use the candidate profile below:
${JSON.stringify(profile, null, 2)}

Question: "${question}"
Instructions: Provide a direct, concise, and professional answer tailored to the question. Do not include conversational filler or quotes.`;

  // 1. App Backend Integration
  if (settings.provider === 'backend' || (!settings.provider && settings.backendBaseUrl)) {
    try {
      const baseUrl = settings.backendBaseUrl || 'http://localhost:8000';
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (settings.backendAuthToken) {
        headers['Authorization'] = `Bearer ${settings.backendAuthToken}`;
      }
      const res = await fetch(`${baseUrl}/generate_outreach`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          job_url: window.location.href,
          job_title: 'Target Role',
          company_name: 'Target Company',
          job_description: question
        })
      });
      if (res.ok) {
        const data = await res.json();
        let ans = data.message || data.answer || '';
        if (typeof ans === 'object' && ans !== null) {
          ans = ans.body || ans.message || ans.text || JSON.stringify(ans);
        }
        return String(ans);
      }
    } catch (e) {
      console.warn('Backend LLM fetch failed, falling back to client models:', e);
    }
  }

  // 2. Chrome Built-in Prompt API (window.ai)
  if (settings.provider === 'window.ai' && 'ai' in window && 'languageModel' in (window as any).ai) {
    try {
      const session = await (window as any).ai.languageModel.create();
      return await session.prompt(systemPrompt);
    } catch (e) {
      console.warn('window.ai error, falling back:', e);
    }
  }

  // 3. Local Ollama / LM Studio
  if (settings.provider === 'ollama') {
    const endpoint = settings.localEndpoint || 'http://localhost:11434';
    const model = settings.localModel || 'llama3.2';
    const res = await fetch(`${endpoint}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, prompt: systemPrompt, stream: false })
    });
    const data = await res.json();
    return data.response.trim();
  }

  // 4. Cloud BYOK (Gemini Flash)
  if (settings.provider === 'gemini' && settings.apiKey) {
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key=${settings.apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ role: 'user', parts: [{ text: systemPrompt }] }]
      })
    });
    const data = await res.json();
    return data.candidates[0].content.parts[0].text.trim();
  }

  // Generic Rule-Based Smart Fallback if no LLM configured
  const qLower = question.toLowerCase();
  if (qLower.includes('authorized') || qLower.includes('legally')) return 'Yes';
  if (qLower.includes('sponsorship') || qLower.includes('visa')) return 'No';
  if (qLower.includes('years of experience') || qLower.includes('how many years')) return '5';

  return 'Available upon request.';
}
