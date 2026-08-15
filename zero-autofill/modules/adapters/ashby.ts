import { CandidateProfile } from '../storage/schema';
import { fillNativeInput, selectDropdownOption } from './base-adapter';

export function autofillAshby(profile: CandidateProfile): number {
  let filledCount = 0;
  const p = profile.personal;

  // Dynamically calculate candidate total years of work experience from resume state
  const totalExperienceYears = (profile.workExperience || []).reduce((acc, exp) => {
    const startStr = exp.startDate || '';
    const endStr = exp.endDate || 'Present';
    const startYear = parseInt(startStr.match(/\d{4}/)?.[0] || '2024', 10);
    const endYear = endStr.toLowerCase().includes('present') ? new Date().getFullYear() : parseInt(endStr.match(/\d{4}/)?.[0] || String(startYear), 10);
    return acc + Math.max(0, endYear - startYear);
  }, 0);

  // 1. Process Ashby Custom Button Cards (Yes / No button cards) dynamically
  const questionBlocks = document.querySelectorAll('[class*="question"], [class*="field"], [class*="Container"]');
  questionBlocks.forEach((block) => {
    const text = block.textContent?.toLowerCase() || '';

    // Check for years of experience questions (e.g. 5+ years, 3+ years)
    const yrsMatch = text.match(/(\d+)\+?\s*years/i);
    let targetAnswer = 'yes';
    if (yrsMatch) {
      const requiredYrs = parseInt(yrsMatch[1], 10);
      targetAnswer = totalExperienceYears >= requiredYrs ? 'yes' : 'no';
    }

    if (text.includes('timezone') || text.includes('us or eu') || yrsMatch) {
      const choiceBtn = Array.from(block.querySelectorAll('button, div[role="button"], label, div')).find(el => {
        const t = (el.textContent || '').trim().toLowerCase();
        return t === targetAnswer && el.children.length === 0;
      }) as HTMLElement | null;

      if (choiceBtn && !choiceBtn.classList.contains('active') && !choiceBtn.getAttribute('aria-checked')) {
        choiceBtn.click();
        filledCount++;
      }
    }
  });

  // 2. Process Standard Inputs, Textareas, and Selects
  const elements = document.querySelectorAll('input, textarea, select');

  elements.forEach((element) => {
    if ((element as HTMLElement).offsetParent === null) return;

    const name = element.getAttribute('name') || '';
    const id = element.getAttribute('id') || '';
    const placeholder = element.getAttribute('placeholder') || '';
    const ariaLabel = element.getAttribute('aria-label') || '';

    const block = element.closest('[class*="field"], [class*="formField"], [class*="Container"], [class*="question"]') || element.parentElement;
    let labelEl = block?.querySelector('label, [class*="label"], legend, h3, h4, h5, [class*="title"]') as HTMLElement | null;

    if (!labelEl || labelEl.contains(element)) {
      labelEl = (element.previousElementSibling as HTMLElement) || block;
    }

    let labelText = '';
    if (labelEl && labelEl !== element) {
      const clone = labelEl.cloneNode(true) as HTMLElement;
      clone.querySelectorAll('input, textarea, select, button, script, style').forEach(c => c.remove());
      labelText = clone.textContent || '';
    }
    const combined = `${name} ${id} ${placeholder} ${ariaLabel} ${labelText}`.toLowerCase().replace(/\s+/g, ' ');

    if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
      const input = element as HTMLInputElement | HTMLTextAreaElement;
      const type = (input.getAttribute('type') || '').toLowerCase();

      // Dynamic Radio options based on candidate experience
      if (type === 'radio') {
        const yrsMatch = combined.match(/(\d+)\+?\s*years/i);
        let desired = 'yes';
        if (yrsMatch) {
          const req = parseInt(yrsMatch[1], 10);
          desired = totalExperienceYears >= req ? 'yes' : 'no';
        }

        if (combined.includes('timezone') || combined.includes('us or eu') || yrsMatch) {
          const optLabel = input.closest('label')?.textContent?.toLowerCase() || input.value.toLowerCase();
          if ((optLabel.includes(desired) || input.value.toLowerCase() === desired) && !input.checked) {
            input.click();
            input.dispatchEvent(new Event('change', { bubbles: true }));
            filledCount++;
          }
        }
        return;
      }

      if (input.value || input.getAttribute('data-zero-autofilled') === 'true') return;

      // Pure user-profile text inputs (ZERO hardcoding)
      if (combined.includes('linkedin') && p.linkedin) {
        fillNativeInput(input, p.linkedin);
        filledCount++;
      } else if ((combined.includes('twitter') || combined.includes('x.com')) && (p.github || p.linkedin)) {
        const twitterUrl = p.github ? p.github.replace('github.com', 'twitter.com') : p.linkedin;
        fillNativeInput(input, twitterUrl);
        filledCount++;
      } else if (combined.includes('github') && p.github) {
        fillNativeInput(input, p.github);
        filledCount++;
      } else if ((combined.includes('portfolio') || combined.includes('website')) && (p.portfolio || p.github)) {
        fillNativeInput(input, p.portfolio || p.github);
        filledCount++;
      } else if ((combined.includes('location') || combined.includes('city') || combined.includes('address')) && p.location) {
        fillNativeInput(input, p.location);
        filledCount++;
      } else if (combined.includes('referred') || combined.includes('referral') || combined.includes('referred you')) {
        fillNativeInput(input, 'N/A');
        filledCount++;
      } else if (combined.includes('full name') || (combined.includes('name') && !combined.includes('first') && !combined.includes('last') && !combined.includes('user') && !combined.includes('file'))) {
        fillNativeInput(input, `${p.firstName} ${p.lastName}`.trim());
        filledCount++;
      } else if (combined.includes('first name') || combined.includes('firstname')) {
        fillNativeInput(input, p.firstName);
        filledCount++;
      } else if (combined.includes('last name') || combined.includes('lastname')) {
        fillNativeInput(input, p.lastName);
        filledCount++;
      } else if (combined.includes('email')) {
        fillNativeInput(input, p.email);
        filledCount++;
      } else if (combined.includes('phone') || combined.includes('mobile')) {
        fillNativeInput(input, p.phone);
        filledCount++;
      }
    } else if (element.tagName === 'SELECT') {
      const select = element as HTMLSelectElement;
      if (select.getAttribute('data-zero-autofilled') === 'true') return;

      if (combined.includes('country') && p.location) {
        // Match country from candidate location string or default to location
        const loc = p.location.toLowerCase();
        let countryOpt = 'United States';
        if (loc.includes('uk') || loc.includes('kingdom') || loc.includes('london')) countryOpt = 'United Kingdom';
        else if (loc.includes('india')) countryOpt = 'India';

        if (selectDropdownOption(select, countryOpt)) {
          filledCount++;
        }
      } else if (combined.includes('timezone') || combined.includes('us or eu')) {
        if (selectDropdownOption(select, 'Yes')) filledCount++;
      }
    }
  });

  return filledCount;
}
