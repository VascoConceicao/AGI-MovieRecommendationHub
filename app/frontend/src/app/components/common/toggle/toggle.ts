import { Component, input, output } from '@angular/core';

@Component({
  selector: 'app-toggle',
  template: `
    <button type="button" role="switch" [attr.aria-checked]="checked()" [disabled]="disabled()" (click)="changed.emit(!checked())">
      <span class="track" aria-hidden="true"><span class="thumb"></span></span>
      <span>{{ label() }}</span>
    </button>
  `,
  styles: `
    :host { display: inline-block; }
    button { display: inline-flex; align-items: center; gap: 10px; padding: 4px 0; background: transparent; color: inherit; font: inherit; font-size: .9rem; border: 0; cursor: pointer; }
    .track { display: inline-flex; align-items: center; width: 42px; height: 24px; padding: 3px; border-radius: 999px; background: var(--ink-black); border: 1px solid var(--pearl-aqua); transition: background .15s; }
    .thumb { width: 16px; height: 16px; border-radius: 50%; background: var(--wheat); box-shadow: 0 1px 3px #0004; transition: transform .15s; }
    [aria-checked='true'] .track { background: var(--pearl-aqua); }
    [aria-checked='true'] .thumb { transform: translateX(18px); }
    button:focus-visible { outline: 2px solid var(--golden-orange); outline-offset: 4px; border-radius: 4px; }
    button:disabled { opacity: .6; cursor: wait; }
    @media (prefers-reduced-motion: reduce) { .track, .thumb { transition: none; } }
  `,
})
export class Toggle {
  readonly label = input.required<string>();
  readonly checked = input(false);
  readonly disabled = input(false);
  readonly changed = output<boolean>();
}
