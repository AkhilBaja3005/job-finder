import { CandidateProfile } from '../storage/schema';
import { fillNativeInput, selectDropdownOption, checkNativeCheckbox } from './base-adapter';

export function autofillGreenhouse(profile: CandidateProfile): number {
  let filledCount = 0;
  const p = profile.personal;

  // Standard Greenhouse selectors
  const selectors: Record<string, string> = {
    '#first_name': p.firstName,
    '#last_name': p.lastName,
    '#email': p.email,
    '#phone': p.phone,
    'input[name*="[first_name]"]': p.firstName,
    'input[name*="[last_name]"]': p.lastName,
    'input[name*="[email]"]': p.email,
    'input[name*="[phone]"]': p.phone,
    '#job_application_location': p.location,
    'input[autocomplete="custom-question-linkedin"]': p.linkedin,
    'input[autocomplete="custom-question-website"]': p.portfolio || p.github,
  };

  for (const [selector, value] of Object.entries(selectors)) {
    if (!value) continue;
    const el = document.querySelector(selector) as HTMLInputElement | null;
    if (el && !el.value) {
      fillNativeInput(el, value);
      filledCount++;
    }
  }

  // Greenhouse Custom Question matching by label text
  const fieldWrappers = document.querySelectorAll('.field, .custom-question');
  fieldWrappers.forEach((wrapper) => {
    const label = wrapper.querySelector('label')?.textContent?.toLowerCase() || '';
    const input = wrapper.querySelector('input[type="text"], input[type="url"], textarea') as HTMLInputElement | HTMLTextAreaElement | null;
    const select = wrapper.querySelector('select') as HTMLSelectElement | null;

    if (input && !input.value) {
      if (label.includes('linkedin')) { fillNativeInput(input, p.linkedin); filledCount++; }
      else if (label.includes('github')) { fillNativeInput(input, p.github); filledCount++; }
      else if (label.includes('website') || label.includes('portfolio')) { fillNativeInput(input, p.portfolio || p.github); filledCount++; }
    } else if (select) {
      if (label.includes('authorized') || label.includes('legally')) {
        selectDropdownOption(select, 'Yes');
        filledCount++;
      } else if (label.includes('sponsorship') || label.includes('require visa')) {
        selectDropdownOption(select, 'No');
        filledCount++;
      }
    }
  });

  return filledCount;
}
