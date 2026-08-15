import { CandidateProfile } from '../storage/schema';
import { fillNativeInput, selectDropdownOption } from './base-adapter';

export function autofillLever(profile: CandidateProfile): number {
  let filledCount = 0;
  const p = profile.personal;

  const fieldMappings: Array<{ selectors: string[]; value: string }> = [
    { selectors: ['input[name="name"]', 'input[name*="name"]'], value: `${p.firstName} ${p.lastName}`.trim() },
    { selectors: ['input[name="email"]', 'input[name*="email"]', 'input[type="email"]'], value: p.email },
    { selectors: ['input[name="phone"]', 'input[name*="phone"]', 'input[type="tel"]'], value: p.phone },
    { selectors: ['input[name="org"]', 'input[name*="org"]', 'input[name*="company"]'], value: profile.workExperience?.[0]?.company || '' },
    { selectors: ['input[name*="LinkedIn"]', 'input[name*="linkedin"]'], value: p.linkedin },
    { selectors: ['input[name*="GitHub"]', 'input[name*="github"]'], value: p.github },
    { selectors: ['input[name*="Portfolio"]', 'input[name*="portfolio"]', 'input[name*="website"]'], value: p.portfolio || p.github }
  ];

  for (const { selectors, value } of fieldMappings) {
    if (!value) continue;
    for (const selector of selectors) {
      const input = document.querySelector(selector) as HTMLInputElement | null;
      if (input && !input.value) {
        fillNativeInput(input, value);
        filledCount++;
        break;
      }
    }
  }

  // Lever custom application questions, dropdowns, and checkboxes
  const customQuestions = document.querySelectorAll('.application-question');
  customQuestions.forEach((qEl) => {
    const labelEl = qEl.querySelector('.application-label, label, legend, h4, h5');
    const label = (labelEl?.textContent || qEl.textContent || '').toLowerCase();

    // 1. Language Skill Checkboxes
    if (label.includes('language skill')) {
      const checkboxes = qEl.querySelectorAll('input[type="checkbox"]');
      checkboxes.forEach((cbEl) => {
        const cb = cbEl as HTMLInputElement;
        const cbLabel = cb.closest('label')?.textContent || '';
        if (cbLabel.toLowerCase().includes('english') && !cb.checked) {
          cb.click();
          cb.dispatchEvent(new Event('change', { bubbles: true }));
          filledCount++;
        }
      });
      return;
    }

    // 2. AI Notetaker / Privacy Consent Radios
    if (label.includes('ai notetaker') || label.includes('consent')) {
      const radioYes = qEl.querySelector('input[type="radio"][value*="Yes"], input[type="radio"][value*="consent"]') as HTMLInputElement | null;
      if (radioYes && !radioYes.checked) {
        radioYes.click();
        radioYes.dispatchEvent(new Event('change', { bubbles: true }));
        filledCount++;
      }
      return;
    }

    const input = qEl.querySelector('input[type="text"], input[type="url"], textarea') as HTMLInputElement | HTMLTextAreaElement | null;
    const select = qEl.querySelector('select') as HTMLSelectElement | null;

    // 3. Inputs & Textareas
    if (input && !input.value && input.getAttribute('data-zero-autofilled') !== 'true') {
      if (label.includes('preferred name') || label.includes('call you')) {
        fillNativeInput(input, p.firstName);
        filledCount++;
      } else if (label.includes('pronunciation')) {
        fillNativeInput(input, `${p.firstName} ${p.lastName}`);
        filledCount++;
      } else if (label.includes('linkedin')) {
        fillNativeInput(input, p.linkedin);
        filledCount++;
      } else if (label.includes('github')) {
        fillNativeInput(input, p.github);
        filledCount++;
      } else if (label.includes('portfolio') || label.includes('website')) {
        fillNativeInput(input, p.portfolio || p.github);
        filledCount++;
      } else if (label.includes('location') || label.includes('city') || label.includes('address')) {
        fillNativeInput(input, p.location);
        filledCount++;
      }
    }

    // 4. Select Dropdowns (University, Work Auth, How heard)
    if (select && select.getAttribute('data-zero-autofilled') !== 'true') {
      if (label.includes('university') || label.includes('school')) {
        // Try finding candidate's university from education profile or fallback to Other
        const candidateSchool = profile.education?.[0]?.school || '';
        if (candidateSchool && selectDropdownOption(select, candidateSchool)) {
          filledCount++;
        } else if (selectDropdownOption(select, 'Other')) {
          filledCount++;
        }
      } else if (label.includes('authorized') || label.includes('legally')) {
        if (selectDropdownOption(select, 'Yes')) filledCount++;
      } else if (label.includes('sponsorship') || label.includes('visa')) {
        if (selectDropdownOption(select, 'No')) filledCount++;
      } else if (label.includes('hear about') || label.includes('how did you hear')) {
        if (selectDropdownOption(select, 'LinkedIn') || selectDropdownOption(select, 'Website') || selectDropdownOption(select, 'Other')) {
          filledCount++;
        }
      }
    }
  });

  return filledCount;
}
