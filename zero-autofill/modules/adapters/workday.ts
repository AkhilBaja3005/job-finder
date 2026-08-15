import { CandidateProfile } from '../storage/schema';
import { fillNativeInput, selectDropdownOption } from './base-adapter';

export function autofillWorkday(profile: CandidateProfile): number {
  let filledCount = 0;
  const p = profile.personal;

  // Workday uses data-automation-id attributes for key fields
  const fieldMap: Record<string, string> = {
    'legalNameSection_firstName': p.firstName,
    'legalNameSection_lastName': p.lastName,
    'addressSection_addressLine1': p.location,
    'email': p.email,
    'phone-number': p.phone
  };

  for (const [automationId, value] of Object.entries(fieldMap)) {
    if (!value) continue;
    const input = document.querySelector(`[data-automation-id="${automationId}"]`) as HTMLInputElement | null;
    if (input && !input.value) {
      fillNativeInput(input, value);
      filledCount++;
    }
  }

  // Workday Shadow DOM and Custom Search-Select handling
  const allInputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"]');
  allInputs.forEach((el) => {
    const input = el as HTMLInputElement;
    const automationId = input.getAttribute('data-automation-id') || '';
    const labelText = input.closest('[data-automation-id]')?.querySelector('label')?.textContent?.toLowerCase() || '';

    if (!input.value) {
      if (automationId.includes('firstName') || labelText.includes('first name')) {
        fillNativeInput(input, p.firstName);
        filledCount++;
      } else if (automationId.includes('lastName') || labelText.includes('last name')) {
        fillNativeInput(input, p.lastName);
        filledCount++;
      } else if (labelText.includes('linkedin')) {
        fillNativeInput(input, p.linkedin);
        filledCount++;
      }
    }
  });

  return filledCount;
}
