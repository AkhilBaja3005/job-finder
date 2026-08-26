import { CandidateProfile } from '../storage/db';
import { fillNativeInput, selectDropdownOption, checkNativeCheckbox } from './base-adapter';

/**
 * Convert base64 resume string to a native File object for automatic attachment
 */
export function base64ToFile(base64String: string, filename: string, mimeType = 'application/pdf'): File | null {
  try {
    const base64Data = base64String.includes(',') ? base64String.split(',')[1] : base64String;
    const binaryString = atob(base64Data);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return new File([bytes], filename, { type: mimeType });
  } catch (error) {
    console.warn('[LinkedIn Adapter] Error converting base64 to file:', error);
    return null;
  }
}

/**
 * Fill file inputs with a generated File object
 */
export async function fillFileInput(fileInput: HTMLInputElement, file: File): Promise<boolean> {
  try {
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    fileInput.files = dataTransfer.files;
    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  } catch (error) {
    console.warn('[LinkedIn Adapter] Error attaching file:', error);
    return false;
  }
}

/**
 * Check if the LinkedIn Daily Application limit has been reached
 */
export function checkLinkedInDailyLimit(): boolean {
  const limitPatterns = [
    "You've reached today's Easy Apply limit",
    "reached today's Easy Apply limit",
    "Great effort applying today",
    "continue applying tomorrow",
    "exceeded the daily application limit"
  ];
  const bodyText = document.body.innerText || '';
  for (const pattern of limitPatterns) {
    if (bodyText.toLowerCase().includes(pattern.toLowerCase())) {
      return true;
    }
  }
  return false;
}

/**
 * Discard / Dismiss the LinkedIn Easy Apply modal if stuck
 */
export async function discardLinkedInModal(): Promise<boolean> {
  const closeButtons = document.querySelectorAll<HTMLButtonElement>(
    'button[aria-label*="Dismiss"], button[aria-label*="Close"], button.artdeco-modal__dismiss'
  );
  for (const btn of Array.from(closeButtons)) {
    if (btn.offsetParent) {
      btn.click();
      await new Promise((r) => setTimeout(r, 600));
      const discardConfirm = Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find((b) =>
        b.offsetParent && ['discard', 'cancel', 'annuler'].some((t) => b.textContent?.trim().toLowerCase().includes(t))
      );
      if (discardConfirm) {
        discardConfirm.click();
        await new Promise((r) => setTimeout(r, 800));
      }
      return true;
    }
  }
  return false;
}

/**
 * Autofill an active LinkedIn Easy Apply modal
 */
export async function autofillLinkedIn(profile: CandidateProfile): Promise<number> {
  let filledCount = 0;
  const p = profile.personal;
  const eeo = profile.eeo || { workAuth: 'Yes', sponsorship: 'No' };

  // Calculate total years of experience
  const totalYears = (profile.workExperience || []).reduce((acc, exp) => {
    const startStr = exp.startDate || '';
    const endStr = exp.endDate || 'Present';
    const startYear = parseInt(startStr.match(/\d{4}/)?.[0] || '2023', 10);
    const endYear = endStr.toLowerCase().includes('present')
      ? new Date().getFullYear()
      : parseInt(endStr.match(/\d{4}/)?.[0] || String(startYear), 10);
    return acc + Math.max(0, endYear - startYear);
  }, 0);

  const modal = document.querySelector(
    '.jobs-easy-apply-modal, .artdeco-modal, [data-test-modal], [role="dialog"]'
  ) || document;

  // 1. Auto-attach PDF resume if available
  if (profile.pdfBase64) {
    const fileInputs = modal.querySelectorAll<HTMLInputElement>('input[type="file"]');
    const pdfFile = base64ToFile(profile.pdfBase64, `${p.firstName || 'Candidate'}_Resume.pdf`);
    if (pdfFile) {
      for (const fi of Array.from(fileInputs)) {
        if (!fi.getAttribute('data-zero-autofilled')) {
          await fillFileInput(fi, pdfFile);
          fi.setAttribute('data-zero-autofilled', 'true');
          filledCount++;
        }
      }
    }
  }

  // 2. Scan and fill inputs, selects, textareas, and radio buttons
  const elements = modal.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
    'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="file"]), textarea, select'
  );

  elements.forEach((el) => {
    if (el.offsetParent === null || el.getAttribute('data-zero-autofilled') === 'true' || el.disabled || el.readOnly) {
      return;
    }

    const id = (el.id || '').toLowerCase();
    const name = (el.name || '').toLowerCase();
    const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
    const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
    const labelText = (el.closest('div, li, fieldset, .fb-form-element, .jobs-easy-apply-form-section')?.textContent || '')
      .slice(0, 200)
      .toLowerCase();
    const key = `${id} ${name} ${placeholder} ${ariaLabel} ${labelText}`;

    // Handle Radio groups
    if (el.tagName === 'INPUT' && (el as HTMLInputElement).type === 'radio') {
      const radio = el as HTMLInputElement;
      const radioText = (radio.closest('label')?.textContent || radio.value || '').toLowerCase();

      if (key.includes('authorized') || key.includes('legally') || key.includes('work in the us')) {
        const targetVal = (eeo.workAuth || 'yes').toLowerCase();
        if (radioText.includes(targetVal) && !radio.checked) {
          radio.click();
          radio.dispatchEvent(new Event('change', { bubbles: true }));
          radio.setAttribute('data-zero-autofilled', 'true');
          filledCount++;
        }
      } else if (key.includes('sponsor') || key.includes('visa')) {
        const targetVal = (eeo.sponsorship || 'no').toLowerCase();
        if (radioText.includes(targetVal) && !radio.checked) {
          radio.click();
          radio.dispatchEvent(new Event('change', { bubbles: true }));
          radio.setAttribute('data-zero-autofilled', 'true');
          filledCount++;
        }
      }
      return;
    }

    // Handle Dropdowns
    if (el.tagName === 'SELECT') {
      const select = el as HTMLSelectElement;
      if (key.includes('authorized') || key.includes('work in the us') || key.includes('legally')) {
        if (selectDropdownOption(select, eeo.workAuth || 'Yes')) filledCount++;
      } else if (key.includes('sponsor') || key.includes('visa')) {
        if (selectDropdownOption(select, eeo.sponsorship || 'No')) filledCount++;
      } else if (key.includes('years') || key.includes('experience')) {
        if (selectDropdownOption(select, String(Math.max(1, totalYears)))) filledCount++;
      }
      return;
    }

    // Handle Text Inputs & Textareas
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      const input = el as HTMLInputElement | HTMLTextAreaElement;
      if (input.value) return;

      let val: string | null = null;
      if (/first.?name|given.?name|firstname|fname/.test(key)) val = p.firstName;
      else if (/last.?name|family.?name|lastname|lname|surname/.test(key)) val = p.lastName;
      else if (/email|e-mail|emailaddress/.test(key)) val = p.email;
      else if (/phone|mobile|cell|tel|phonenumber/.test(key)) val = p.phone;
      else if (/city|location|address/.test(key)) val = p.location;
      else if (/linkedin/.test(key)) val = p.linkedin;
      else if (/github/.test(key)) val = p.github;
      else if (/website|portfolio/.test(key)) val = p.portfolio || p.github;
      else if (/years of experience|how many years/.test(key)) val = String(Math.max(1, totalYears));
      else if (/summary|cover.?letter|additional info|about you/.test(key)) val = profile.rawResumeText.slice(0, 800);

      if (val) {
        fillNativeInput(input, val);
        input.style.outline = '2px solid #38bdf8';
        filledCount++;
      }
    }
  });

  return filledCount;
}
