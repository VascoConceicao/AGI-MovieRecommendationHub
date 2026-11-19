import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../shared/services/backend/auth/auth.service';

@Component({
  selector: 'app-credits',
  imports: [RouterLink],
  template: `
    <main class="credits-page">
      <a class="back-link" [routerLink]="auth.user() ? '/home/profile' : '/login'">← Back</a>
      <h1>Credits</h1>
      <section aria-label="Movie data and posters">
        <a href="https://www.themoviedb.org/" target="_blank" rel="noopener noreferrer" aria-label="The Movie Database (opens in a new tab)">
          <img src="/assets/credits/tmdb.svg" alt="TMDB" width="150" />
        </a>
        <h2>Movie data and posters</h2>
        <p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
      </section>
    </main>
  `,
  styles: `
    .credits-page { max-width: 760px; margin: 0 auto; padding: 48px 24px; }
    .back-link { color: var(--pearl-aqua); text-decoration: none; }
    h1 { margin: 36px 0 24px; font: 400 2.5rem/1.2 Georgia, serif; }
    section { padding: 28px; border: 1px solid var(--dark-cyan); border-radius: 14px; background: var(--dark-teal); }
    img { display: block; max-width: 100%; height: auto; }
    h2 { margin: 24px 0 12px; font-size: 1.1rem; }
    p { margin: 0; color: var(--pearl-aqua); line-height: 1.6; }
  `,
})
export class CreditsPage {
  readonly auth = inject(AuthService);
}
