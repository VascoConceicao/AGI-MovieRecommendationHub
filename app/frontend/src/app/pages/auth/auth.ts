import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService, authError } from '../../shared/services/backend/auth/auth.service';

@Component({
  selector: 'app-auth', imports: [RouterLink],
  templateUrl: './auth.html', styleUrl: './auth.scss',
})
export class AuthPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  readonly register = signal(false);
  readonly pending = signal(false);
  readonly error = signal('');
  readonly showPassword = signal(false);

  constructor() {
    this.route.data.pipe(takeUntilDestroyed()).subscribe(data => {
      this.register.set(data['register'] === true);
      this.error.set('');
      this.showPassword.set(false);
    });
    this.auth.session().pipe(takeUntilDestroyed()).subscribe({
      next: () => void this.router.navigateByUrl('/home'),
      error: () => this.auth.user.set(null),
    });
  }

  submit(event: Event, form: HTMLFormElement): void {
    event.preventDefault();
    if (this.pending()) return;
    const data = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
    if (this.register() && data['password'] !== data['password_confirmation']) {
      this.error.set('Your passwords do not match. Please try again.');
      return;
    }
    this.pending.set(true);
    this.error.set('');
    this.auth.submit(this.register(), data).pipe(
      takeUntilDestroyed(this.destroyRef), finalize(() => this.pending.set(false)),
    ).subscribe({
      next: () => { form.reset(); void this.router.navigateByUrl('/home'); },
      error: error => this.error.set(authError(error)),
    });
  }
}
