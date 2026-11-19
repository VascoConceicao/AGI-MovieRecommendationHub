import { TestBed } from '@angular/core/testing';
import { expect, it, vi } from 'vitest';
import { Toggle } from './toggle';
it('emits the next switch value and respects disabled state', () => {
  const fixture = TestBed.createComponent(Toggle);
  fixture.componentRef.setInput('label', 'Public profile'); fixture.detectChanges();
  const changed = vi.fn(); fixture.componentInstance.changed.subscribe(changed);
  const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
  expect(button.textContent).toContain('Public profile'); expect(button.getAttribute('aria-checked')).toBe('false');
  button.click(); expect(changed).toHaveBeenLastCalledWith(true);
  fixture.componentRef.setInput('checked', true); fixture.detectChanges(); button.click(); expect(changed).toHaveBeenLastCalledWith(false);
  fixture.componentRef.setInput('disabled', true); fixture.detectChanges(); button.click(); expect(changed).toHaveBeenCalledTimes(2);
});
