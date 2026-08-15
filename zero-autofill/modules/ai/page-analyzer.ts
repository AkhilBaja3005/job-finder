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
  
  // Include standard inputs AND custom framework elements (div comboboxes, ARIA controls, custom buttons)
  const elements = document.querySelectorAll(
    'input, textarea, select, [role="combobox"], [role="listbox"], [role="radiogroup"], [role="checkbox"], [contenteditable="true"], button[class*="select"], div[class*="select"], div[class*="option"], div[role="button"]'
  );

  elements.forEach((el, index) => {
    const element = el as HTMLElement;

    // Skip hidden elements or form submission buttons
    if (element.offsetParent === null) return;
    const type = (element.getAttribute('type') || '').toLowerCase();
    if (['hidden', 'submit', 'file', 'image'].includes(type)) return;
    if (element.tagName === 'BUTTON' && (type === 'submit' || (element.textContent || '').toLowerCase().includes('submit'))) return;

    const id = element.getAttribute('id') || element.getAttribute('name') || `ai_field_${index}`;
    element.setAttribute('data-zero-field-id', id);

    const placeholder = element.getAttribute('placeholder') || element.getAttribute('aria-placeholder') || '';
    const ariaLabel = element.getAttribute('aria-label') || '';
    
    // Find tight parent label or preceding heading
    const fieldBlock = element.closest('[class*="field"], [class*="formField"], [class*="question"], .application-question, .form-group, label') || element.parentElement;
    let labelTextEl = fieldBlock?.querySelector('label, [class*="label"], legend, h3, h4, h5, [class*="title"], [class*="heading"]') as HTMLElement | null;

    if (!labelTextEl || labelTextEl.contains(element)) {
      labelTextEl = (element.previousElementSibling as HTMLElement) || fieldBlock;
    }

    let labelText = '';
    if (labelTextEl && labelTextEl !== element) {
      const clone = labelTextEl.cloneNode(true) as HTMLElement;
      clone.querySelectorAll('input, textarea, select, button, script, style').forEach(child => child.remove());
      labelText = (clone.textContent || '').replace(/\s+/g, ' ').trim();
    }

    if (!labelText || labelText.length < 2) {
      labelText = ariaLabel || placeholder || id;
    }

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
    } else if (element.tagName === 'TEXTAREA' || element.getAttribute('contenteditable') === 'true') {
      fields.push({
        fieldId: id,
        label: cleanLabel,
        fieldType: 'textarea',
        placeholder
      });
    } else if (type === 'checkbox' || type === 'radio' || element.getAttribute('role') === 'checkbox' || element.getAttribute('role') === 'radio') {
      const optionText = element.closest('label')?.textContent?.trim() || (element as HTMLInputElement).value || element.textContent?.trim() || 'Yes';
      fields.push({
        fieldId: id,
        label: `${cleanLabel} (Option: ${optionText})`,
        fieldType: (type || 'checkbox') as 'checkbox' | 'radio',
        options: [optionText]
      });
    } else {
      // Standard input or custom div combobox / button card
      const isCombobox = element.getAttribute('role') === 'combobox' || element.classList.toString().toLowerCase().includes('select');
      fields.push({
        fieldId: id,
        label: cleanLabel,
        fieldType: isCombobox ? 'select' : 'text',
        placeholder
      });
    }
  });

  return fields;
}

/**
 * Extract sanitized raw HTML form source (removing scripts/styles) for LLM structural analysis
 */
export function extractSanitizedFormHTML(): string {
  const forms = document.querySelectorAll('form, [class*="form"], [class*="application"], main');
  const target = forms.length > 0 ? forms[0] : document.body;
  const clone = target.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('script, style, svg, path, link, meta').forEach(el => el.remove());
  const html = clone.outerHTML.replace(/\s+/g, ' ').trim();
  return html.length > 15000 ? html.substring(0, 15000) + '...' : html;
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

  const rawFormHTML = extractSanitizedFormHTML();

  const promptPayload = {
    candidateProfile: {
      ...profile,
      fullName: `${profile.personal.firstName} ${profile.personal.lastName}`.trim()
    },
    pageTitle: document.title,
    rawFormHTMLSnippet: rawFormHTML,
    questionsToSolve: fields
  };

  const systemPrompt = `You are a high-caliber AI Career Coach and Multimodal Resume Assistant.
You have been provided with:
1. A visual screenshot of the job application page.
2. The raw HTML form source code ("rawFormHTMLSnippet").
3. The interactive DOM question schema ("questionsToSolve").

Analyze the candidate's complete profile and resume below, inspect the raw HTML form structure and screenshot to pick which element/field to fill, and answer each question.

CRITICAL INSTRUCTIONS:
1. Every answer MUST be personalized, specific, and directly synthesized from the Candidate Profile and Work Experience.
2. DO NOT output generic filler. Cite actual skills, projects, technologies, and achievements.
3. For dropdown/select questions or custom ARIA comboboxes, choose the EXACT string from the provided options or raw HTML option list.
4. For short inputs (LinkedIn, GitHub, Name, City), output the exact profile value.

Candidate Profile:
${JSON.stringify(promptPayload.candidateProfile, null, 2)}

Raw Form HTML Snippet:
${promptPayload.rawFormHTMLSnippet}

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
    } else if (type === 'checkbox' || type === 'radio' || element.getAttribute('role') === 'checkbox' || element.getAttribute('role') === 'radio') {
      const input = element as HTMLInputElement;
      const lowerAns = String(answer).toLowerCase();
      if (lowerAns === 'true' || lowerAns === 'yes' || lowerAns === 'checked' || lowerAns.includes('select')) {
        element.click();
        if (input.type === 'checkbox' || input.type === 'radio') {
          input.checked = true;
        }
        element.dispatchEvent(new Event('change', { bubbles: true }));
        solvedCount++;
        fieldDetails.push({ fieldId, label, answer: 'Checked / Selected' });
        highlightAIField(element);
      }
    } else if (element.getAttribute('contenteditable') === 'true' || element.tagName === 'DIV' || element.tagName === 'BUTTON') {
      if (element.getAttribute('contenteditable') === 'true') {
        element.textContent = answer;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        solvedCount++;
        fieldDetails.push({ fieldId, label, answer });
        highlightAIField(element);
      } else {
        // Custom button card or div option click
        element.click();
        solvedCount++;
        fieldDetails.push({ fieldId, label, answer: 'Clicked Card' });
        highlightAIField(element);
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
