import { Component, input } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

@Component({
  selector: 'app-tab-navigation',
  imports: [RouterLink, RouterLinkActive],
  template: `
    <nav aria-label="Home tabs">
      @for (tab of tabs(); track tab.path) {
        <a [routerLink]="tab.path" routerLinkActive="active" ariaCurrentWhenActive="page">{{ tab.label }}</a>
      }
    </nav>
  `,
  styles: `
    nav { display: flex; gap: 8px; flex-wrap: wrap; }
    a { padding: 12px 18px; border-radius: 8px; text-decoration: none; color: var(--pearl-aqua); }
    a:hover { background: var(--dark-teal); }
    a.active { color: var(--golden-orange); background: var(--dark-teal); }
  `,
})
export class TabNavigation {
  readonly tabs = input.required<readonly { label: string; path: string }[]>();
}
