import { CandidateProfile } from '../storage/schema';
import { fillNativeInput, selectDropdownOption } from './base-adapter';

export function autofillUniversal(profile: CandidateProfile): number {
  let filledCount = 0;
  const p = profile.personal;

  const inputs = document.querySelectorAll('input, textarea, select');

  inputs.forEach((element) => {
    // Skip hidden or already filled inputs
    if ((element as HTMLElement).offsetParent === null) return;
    if (element.getAttribute('data-zero-autofilled') === 'true') return;

    const name = element.getAttribute('name') || '';
    const id = element.getAttribute('id') || '';
    const placeholder = element.getAttribute('placeholder') || '';
    const ariaLabel = element.getAttribute('aria-label') || '';
    const label = element.closest('label')?.textContent || 
                  document.querySelector(`label[for="${id}"]`)?.textContent || 
                  element.parentElement?.textContent || '';
    const textContext = `${name} ${id} ${placeholder} ${ariaLabel} ${label}`.toLowerCase();

    if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
      const input = element as HTMLInputElement | HTMLTextAreaElement;
      if (input.value) return;

      const type = input.getAttribute('type')?.toLowerCase() || 'text';

      if (type === 'email' || textContext.includes('email')) {
        fillNativeInput(input, p.email);
        filledCount++;
      } else if (type === 'tel' || textContext.includes('phone') || textContext.includes('mobile')) {
        fillNativeInput(input, p.phone);
        filledCount++;
      } else if (textContext.includes('first name') || textContext.includes('firstname') || textContext.includes('given name')) {
        fillNativeInput(input, p.firstName);
        filledCount++;
      } else if (textContext.includes('last name') || textContext.includes('lastname') || textContext.includes('family name') || textContext.includes('surname')) {
        fillNativeInput(input, p.lastName);
        filledCount++;
      } else if (textContext.includes('full name') || textContext.includes('name')) {
        fillNativeInput(input, `${p.firstName} ${p.lastName}`.trim());
        filledCount++;
      } else if (textContext.includes('linkedin')) {
        fillNativeInput(input, p.linkedin);
        filledCount++;
      } else if (textContext.includes('github')) {
        fillNativeInput(input, p.github);
        filledCount++;
      } else if (textContext.includes('website') || textContext.includes('portfolio')) {
        fillNativeInput(input, p.portfolio || p.github);
        filledCount++;
      } else if (textContext.includes('city') || textContext.includes('location') || textContext.includes('address')) {
        fillNativeInput(input, p.location);
        filledCount++;
      } else if (textContext.includes('company') || textContext.includes('current employer')) {
        const currentCompany = profile.workExperience?.[0]?.company || '';
        if (currentCompany) { fillNativeInput(input, currentCompany); filledCount++; }
      } else if (textContext.includes('title') || textContext.includes('current role')) {
        const currentTitle = profile.workExperience?.[0]?.title || '';
        if (currentTitle) { fillNativeInput(input, currentTitle); filledCount++; }
      }
    } else if (element.tagName === 'SELECT') {
      const select = element as HTMLSelectElement;
      if (textContext.includes('authorized') || textContext.includes('legally') || textContext.includes('work authorization')) {
        if (selectDropdownOption(select, 'Yes')) filledCount++;
      } else if (textContext.includes('sponsorship') || textContext.includes('visa')) {
        if (selectDropdownOption(select, 'No')) filledCount++;
      } else if (textContext.includes('gender') || textContext.includes('sex')) {
        if (selectDropdownOption(select, 'Decline') || selectDropdownOption(select, 'Prefer not to say') || selectDropdownOption(select, 'Male')) filledCount++;
      } else if (textContext.includes('race') || textContext.includes('ethnicity')) {
        if (selectDropdownOption(select, 'Decline') || selectDropdownOption(select, 'Prefer not to say') || selectDropdownOption(select, 'Asian')) filledCount++;
      } else if (textContext.includes('veteran')) {
        if (selectDropdownOption(select, 'No') || selectDropdownOption(select, 'Not a veteran') || selectDropdownOption(select, 'Decline')) filledCount++;
      } else if (textContext.includes('disability')) {
        if (selectDropdownOption(select, 'No') || selectDropdownOption(select, 'Do not have') || selectDropdownOption(select, 'Decline')) filledCount++;
      } else if (element.hasAttribute('required') && select.selectedIndex <= 0) {
        // Fallback for any required unselected dropdown: select first valid option
        const validOption = Array.from(select.options).find(opt => opt.value && !opt.text.toLowerCase().includes('select'));
        if (validOption) {
          selectDropdownOption(select, validOption.text);
          filledCount++;
        }
      }
    } else if (element.tagName === 'INPUT' && (element as HTMLInputElement).type === 'checkbox') {
      const cb = element as HTMLInputElement;
      if (cb.hasAttribute('required') && !cb.checked) {
        cb.click();
        cb.dispatchEvent(new Event('change', { bubbles: true }));
        filledCount++;
      }
    }
  });

  return filledCount;
}
