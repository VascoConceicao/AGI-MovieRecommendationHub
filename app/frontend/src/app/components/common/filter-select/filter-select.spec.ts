import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FilterSelect } from './filter-select';

const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');

function setup() {
  const fixture = TestBed.createComponent(FilterSelect);
  fixture.componentRef.setInput('label', 'Genres');
  fixture.componentRef.setInput('options', [{ value: 'drama', label: 'Drama' }, { value: 'comedy', label: 'Comedy' }]);
  fixture.detectChanges();
  const changed = vi.fn(); fixture.componentInstance.changed.subscribe(changed);
  return { fixture, select: fixture.componentInstance, changed };
}

describe('FilterSelect', () => {
  afterEach(() => {
    vi.useRealTimers();
    if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll);
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
  });
  it('filters choices and normalizes selection state', () => {
    const { fixture, select, changed } = setup();
    expect(select.placeholder()).toBe('Any');
    expect(select.labelFor('missing')).toBe('missing');
    fixture.componentRef.setInput('values', ['drama']);
    expect(select.matches().map(o => o.value)).toEqual(['comedy']);
    select.edit('COM');
    expect(select.matches().map(o => o.value)).toEqual(['comedy']);
    select.choose('comedy');
    expect(changed).toHaveBeenLastCalledWith(['drama', 'comedy']);
    expect(select.opened()).toBe(true);
    expect(select.query()).toBe('');
    select.choose('DRAMA');
    expect(changed).toHaveBeenCalledTimes(1);
    fixture.componentRef.setInput('max', 1); select.choose('other');
    fixture.componentRef.setInput('disabled', true); select.choose('other');
    expect(changed).toHaveBeenCalledTimes(1);
    select.remove('drama'); expect(changed).toHaveBeenLastCalledWith([]);
    fixture.componentRef.setInput('multiple', false);
    fixture.componentRef.setInput('disabled', false);
    expect(select.placeholder()).toBe('Drama');
    expect(select.matches().length).toBe(2);
    select.choose('comedy'); expect(changed).toHaveBeenLastCalledWith(['comedy']);
    expect(select.opened()).toBe(false);
  });
  it('closes the multiple selector when the selection limit is reached', () => {
    const { fixture, select, changed } = setup();
    fixture.componentRef.setInput('max', 2);
    fixture.componentRef.setInput('values', ['drama']);
    select.edit('com'); select.active.set(1); select.choose('comedy');
    expect(changed).toHaveBeenLastCalledWith(['drama', 'comedy']);
    expect(select.opened()).toBe(false);
    expect(select.active()).toBe(0);
  });
  it('commits only valid free text', () => {
    const { fixture, select, changed } = setup();
    select.edit('name'); select.commit(); expect(changed).not.toHaveBeenCalled();
    fixture.componentRef.setInput('freeText', true);
    expect(select.placeholder()).toBe('Type a name, press Enter');
    for (const value of ['', ' ', 'x'.repeat(201)]) { select.edit(value); select.commit(); }
    expect(changed).not.toHaveBeenCalled();
    select.edit(' Name '); select.key(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(changed).toHaveBeenLastCalledWith(['Name']);
    select.key(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    expect(select.opened()).toBe(false);
  });
  it('supports keyboard navigation, escape, and focus leaving the component', () => {
    vi.useFakeTimers();
    const { fixture, select, changed } = setup();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, writable: true, value: vi.fn() });
    const key = (value: string) => select.key(new KeyboardEvent('keydown', { key: value, cancelable: true }));
    key('Enter'); expect(changed).not.toHaveBeenCalled();
    key('Escape'); key('x');
    key('ArrowDown'); expect(select.active()).toBe(0);
    key('ArrowDown'); expect(select.active()).toBe(1);
    key('ArrowUp'); expect(select.active()).toBe(0);
    const active = document.createElement('div'); active.className = 'active';
    active.scrollIntoView = vi.fn(); fixture.nativeElement.append(active);
    vi.runAllTimers();
    expect(select.opened()).toBe(true);
    key('Enter'); expect(changed).toHaveBeenLastCalledWith(['drama']);
    key('ArrowUp'); key('Escape'); expect(select.opened()).toBe(false);
    fixture.componentRef.setInput('options', []);
    key('ArrowDown'); expect(select.active()).toBe(0); key('Enter');
    active.remove(); vi.runAllTimers();
    select.blur(new FocusEvent('focusout', { relatedTarget: fixture.nativeElement }));
    expect(select.opened()).toBe(true);
    select.blur(new FocusEvent('focusout', { relatedTarget: null }));
    expect(select.opened()).toBe(false);
    select.opened.set(true);
    fixture.nativeElement.dispatchEvent(new FocusEvent('focusout', { relatedTarget: null }));
    expect(select.opened()).toBe(false);
  });
});
