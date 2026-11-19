import { Component, computed, ElementRef, inject, input, output, signal } from '@angular/core';

export interface SelectOption { value: string; label: string; }
let nextId = 0;

@Component({
  selector: 'app-filter-select',
  templateUrl: './filter-select.html',
  styleUrl: './filter-select.scss',
  host: { '(focusout)': 'blur($event)' },
})
export class FilterSelect {
  private readonly element = inject(ElementRef<HTMLElement>);
  readonly label = input.required<string>();
  readonly options = input<SelectOption[]>([]);
  readonly values = input<string[]>([]);
  readonly freeText = input(false);
  readonly multiple = input(true);
  readonly disabled = input(false);
  readonly max = input(10);
  readonly changed = output<string[]>();
  readonly id = `filter-select-${++nextId}`;
  readonly query = signal('');
  readonly opened = signal(false);
  readonly active = signal(0);
  readonly matches = computed(() => this.options().filter(option =>
    (!this.multiple() || !this.values().includes(option.value)) &&
    option.label.toLocaleLowerCase().includes(this.query().toLocaleLowerCase())).slice(0, 100));

  labelFor(value: string): string { return this.options().find(option => option.value === value)?.label ?? value; }
  placeholder(): string {
    return !this.multiple() && this.values().length ? this.labelFor(this.values()[0]) : this.freeText() ? 'Type a name, press Enter' : 'Any';
  }
  edit(value: string): void { this.query.set(value); this.active.set(0); this.opened.set(!this.freeText()); }
  choose(value: string): void {
    if (this.disabled()) return;
    const values = this.values();
    if (this.multiple() && (values.length >= this.max() || values.some(item => item.toLocaleLowerCase() === value.toLocaleLowerCase()))) return;
    this.changed.emit(this.multiple() ? [...values, value] : [value]);
    this.query.set('');
    this.active.set(0);
    this.opened.set(this.multiple() && !this.freeText() && values.length + 1 < this.max());
  }
  commit(): void {
    const name = this.query().trim();
    if (this.freeText() && name && name.length <= 200) this.choose(name);
  }
  remove(value: string): void { this.changed.emit(this.values().filter(item => item !== value)); }
  blur(event: FocusEvent): void {
    if (!this.element.nativeElement.contains(event.relatedTarget as Node)) {
      this.opened.set(false);
    }
  }
  key(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.opened()) {
      event.preventDefault(); event.stopPropagation(); this.opened.set(false); return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (this.freeText()) this.commit();
      else if (this.opened() && this.matches()[this.active()]) this.choose(this.matches()[this.active()].value);
      return;
    }
    if (!this.freeText() && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      const count = this.matches().length;
      const index = this.opened() ? (this.active() + (event.key === 'ArrowDown' ? 1 : -1) + count) % count : 0;
      this.opened.set(true); this.active.set(count ? index : 0);
      setTimeout(() => this.element.nativeElement.querySelector('.active')?.scrollIntoView({ block: 'nearest' }));
    }
  }
}
