import { CandidateProfile, AISettings, getSettings } from '../storage/db';
import { fillNativeInput, selectDropdownOption } from '../adapters/base-adapter';

export interface FormFieldSchema {
  fieldId: string;
  label: string;
  fieldType: 'text' | 'textarea' | 'select' | 'checkbox' | 'radio';
  options?: string[];
  placeholder?: string;
}

/**
 * Extract all interactive form fields and questions from the active page DOM
 */
export function extractPageFormSchema(): FormFieldSchema[] {
  const fields: FormFieldSchema[] = [];
  const elements = document.querySelectorAll('input, textarea, select');

  elements.forEach((el, index) => {
    const element = el as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

    // Skip hidden or submit/button inputs
    if ((element as HTMLElement).offsetParent === null) return;
    const type = (element.getAttribute('type') || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'file', 'image'].includes(type)) return;

    const id = element.getAttribute('id') || element.getAttribute('name') || `ai_field_${index}`;
    element.setAttribute('data-zero-field-id', id);

    const placeholder = element.getAttribute('placeholder') || '';
    const ariaLabel = element.getAttribute('aria-label') || '';
    
    // Find closest field wrapper/question block
    const fieldBlock = element.closest('[class*="field"], [class*="formField"], [class*="question"], .application-question, .form-group, label') || element.parentElement;

    // Search for explicit label/legend/heading elements within the block
    let labelTextEl = fieldBlock?.querySelector('label, [class*="label"], legend, h3, h4, h5, [class*="title"], [class*="heading"]') as HTMLElement | null;

    // If label element encompasses entire block or contains input itself, look for preceding text/header sibling
    if (!labelTextEl || labelTextEl.contains(element)) {
      labelTextEl = (element.previousElementSibling as HTMLElement) || fieldBlock;
    }

    // Extract text content and filter out input/button text
    let labelText = '';
    if (labelTextEl && labelTextEl !== element) {
      // Clone element to remove script/style tags or input text
      const clone = labelTextEl.cloneNode(true) as HTMLElement;
      clone.querySelectorAll('input, textarea, select, button, script, style').forEach(child => child.remove());
      labelText = (clone.textContent || '').replace(/\s+/g, ' ').trim();
    }

    if (!labelText || labelText.length < 2) {
      labelText = ariaLabel || placeholder || id;
    }

    // Clean up label text to remove excessive raw text
    const cleanLabel = labelText.length > 250 ? labelText.substring(0, 250) + '...' : labelText;

    if (element.tagName === 'SELECT') {
      const select = element as HTMLSelectElement;
      const options = Array.from(select.options)
        .map(opt => opt.text.trim())
        .filter(t => t && !t.toLowerCase().includes('select'));

      fields.push({
        fieldId: id,
        label: cleanLabel,
        fieldType: 'select',
        options
      });
    } else if (element.tagName === 'TEXTAREA') {
      fields.push({
        fieldId: id,
        label: cleanLabel,
        fieldType: 'textarea',
        placeholder
      });
    } else if (type === 'checkbox' || type === 'radio') {
      const optionText = element.closest('label')?.textContent?.trim() || element.value || 'Yes';
      fields.push({
        fieldId: id,
        label: `${cleanLabel} (Option: ${optionText})`,
        fieldType: type as 'checkbox' | 'radio',
        options: [optionText]
      });
    } else if (element.tagName === 'INPUT') {
      fields.push({
        fieldId: id,
        label: cleanLabel,
        fieldType: 'text',
        placeholder
      });
    }
  });

  return fields;
}

/**
 * Batch analyze extracted form questions with LLM and auto-fill answers
 */
export async function batchSolvePageQuestions(
  profile: CandidateProfile,
  imageBase64?: string
): Promise<{ solvedCount: number; answers: Record<string, string>; fieldDetails?: Array<{ fieldId: string; label: string; answer: string }> }> {
  const settings = await getSettings();
  const fields = extractPageFormSchema();
  if (fields.length === 0) return { solvedCount: 0, answers: {} };

  const promptPayload = {
    candidateProfile: {
      ...profile,
      fullName: `${profile.personal.firstName} ${profile.personal.lastName}`.trim()
    },
    pageTitle: document.title,
    questionsToSolve: fields
  };

  const systemPrompt = `You are a high-caliber AI Career Coach and Multimodal Resume Assistant.
You have been provided with both a visual screenshot of the job application page and the DOM question schema.
Analyze the candidate's complete profile and resume below, match visual layout cues from the screenshot to "questionsToSolve", and answer each question.

CRITICAL INSTRUCTIONS:
1. Every answer MUST be personalized, specific, and directly synthesized from the Candidate Profile and Work Experience.
2. DO NOT output generic or template filler (e.g. "I am eager to contribute..."). Cite actual skills, projects, technologies, and achievements from the candidate's background.
3. For dropdown/select questions, choose the EXACT string from the provided "options" list.
4. For short inputs (e.g. LinkedIn, GitHub, Name, City), output the candidate's exact profile value.

Candidate Profile:
${JSON.stringify(promptPayload.candidateProfile, null, 2)}

Questions to Solve:
${JSON.stringify(promptPayload.questionsToSolve, null, 2)}

RETURN STRICT JSON ONLY in the following format:
{
  "answers": {
    "fieldId": "Unique, detailed, tailored answer string based on resume"
  }
}`;

  let answersMap: Record<string, string> = {};

  // Build multimodal parts payload
  const partsPayload: any[] = [];
  if (imageBase64) {
    const cleanBase64 = imageBase64.replace(/^data:image\/(jpeg|jpg|png);base64,/, '');
    partsPayload.push({
      inline_data: {
        mime_type: 'image/jpeg',
        data: cleanBase64
      }
    });
  }
  partsPayload.push({ text: systemPrompt });

  try {
    if (settings.apiKey) {
      const models = ['gemini-3.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-pro'];
      for (const model of models) {
        try {
          const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${settings.apiKey}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              contents: [
                {
                  role: 'user',
                  parts: partsPayload
                }
              ],
              generationConfig: {
                temperature: 0.2
              }
            })
          });
          const data = await res.json();
          if (data.error) {
            console.warn(`[Zero-Autofill AI] Model ${model} returned API error:`, data.error.message || data.error);
            continue;
          }
          const textCandidate = data.candidates?.[0]?.content?.parts?.[0]?.text;
          if (textCandidate) {
            const cleanJson = textCandidate.replace(/```json/gi, '').replace(/```/g, '').trim();
            const parsed = JSON.parse(cleanJson);
            answersMap = parsed.answers || parsed;
            break;
          } else {
            console.warn(`[Zero-Autofill AI] Model ${model} returned empty candidates:`, JSON.stringify(data));
          }
        } catch (err) {
          console.warn(`[Zero-Autofill AI] Model ${model} fetch exception:`, err);
        }
      }
    }
  } catch (e) {
    console.warn('[Zero-Autofill AI] Error processing batch answers:', e);
  }

  let solvedCount = 0;
  const fieldDetails: Array<{ fieldId: string; label: string; answer: string }> = [];

  // Apply answers back to DOM elements and highlight with AI badge
  for (const [fieldId, answer] of Object.entries(answersMap)) {
    if (!answer) continue;
    const element = document.querySelector(`[data-zero-field-id="${fieldId}"]`) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
    if (!element) continue;

    const schemaItem = fields.find(f => f.fieldId === fieldId);
    const label = schemaItem?.label || fieldId;
    const type = (element.getAttribute('type') || '').toLowerCase();

    if (element.tagName === 'SELECT') {
      if (selectDropdownOption(element as HTMLSelectElement, answer)) {
        solvedCount++;
        fieldDetails.push({ fieldId, label, answer });
        highlightAIField(element);
      }
    } else if (type === 'checkbox' || type === 'radio') {
      const input = element as HTMLInputElement;
      const lowerAns = String(answer).toLowerCase();
      if (lowerAns === 'true' || lowerAns === 'yes' || lowerAns === 'checked' || lowerAns.includes('select')) {
        if (!input.checked) {
          input.click();
          input.dispatchEvent(new Event('change', { bubbles: true }));
          solvedCount++;
          fieldDetails.push({ fieldId, label, answer: 'Checked / Selected' });
          highlightAIField(input);
        }
      }
    } else {
      fillNativeInput(element as HTMLInputElement | HTMLTextAreaElement, answer);
      solvedCount++;
      fieldDetails.push({ fieldId, label, answer });
      highlightAIField(element);
    }
  }

  return { solvedCount, answers: answersMap, fieldDetails };
}

function highlightAIField(element: HTMLElement) {
  element.style.transition = 'box-shadow 0.3s, border-color 0.3s';
  element.style.borderColor = '#10b981';
  element.style.boxShadow = '0 0 0 3px rgba(16, 185, 129, 0.2)';
}
