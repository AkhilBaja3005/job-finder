/**
 * Prototype Value Setter Override & Reactive Event Dispatcher
 * Prevents React, Vue, Angular, and Svelte from overriding filled input values.
 */
export function fillNativeInput(element: HTMLInputElement | HTMLTextAreaElement, value: any) {
  if (!element || value === undefined || value === null) return;

  let stringVal = '';
  if (typeof value === 'object') {
    stringVal = value.message || value.answer || value.response || value.text || JSON.stringify(value);
  } else {
    stringVal = String(value);
  }

  if (!stringVal || stringVal === '[object Object]') return;

  const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
  const prototype = Object.getPrototypeOf(element);
  const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

  if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
    prototypeValueSetter.call(element, stringVal);
  } else if (valueSetter) {
    valueSetter.call(element, stringVal);
  } else {
    element.value = stringVal;
  }

  // Dispatch bubbling events so reactive framework state updates automatically
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new Event('blur', { bubbles: true }));
  element.setAttribute('data-zero-autofilled', 'true');
}

export function selectDropdownOption(select: HTMLSelectElement, valueOrText: string): boolean {
  if (!select || !valueOrText) return false;
  const options = Array.from(select.options);
  const lowerTarget = valueOrText.toLowerCase();

  const target = options.find(
    opt => opt.value.toLowerCase() === lowerTarget || 
           opt.text.toLowerCase().includes(lowerTarget) ||
           lowerTarget.includes(opt.text.toLowerCase())
  );

  if (target) {
    select.value = target.value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    select.dispatchEvent(new Event('blur', { bubbles: true }));
    select.setAttribute('data-zero-autofilled', 'true');
    return true;
  }
  return false;
}

export function checkNativeCheckbox(checkbox: HTMLInputElement, shouldCheck: boolean) {
  if (!checkbox) return;
  if (checkbox.checked !== shouldCheck) {
    checkbox.click();
    checkbox.dispatchEvent(new Event('change', { bubbles: true }));
    checkbox.setAttribute('data-zero-autofilled', 'true');
  }
}
