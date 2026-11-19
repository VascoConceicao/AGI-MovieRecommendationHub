import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, finalize, map } from 'rxjs';
import { tabNavigation } from './tabs.routes';
import { TabNavigation } from '../../components/common/tab-navigation/tab-navigation';
import { AuthService, authError } from '../../shared/services/backend/auth/auth.service';

@Component({
  selector: 'app-home',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, TabNavigation],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class HomePage {
  readonly tabs = tabNavigation.filter(tab => tab.path !== '/home/profile');
  readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly currentUrl = toSignal(this.router.events.pipe(
    filter((event): event is NavigationEnd => event instanceof NavigationEnd),
    map(event => event.urlAfterRedirects),
  ), { initialValue: this.router.url });
  readonly onProfile = computed(() => this.currentUrl().split(/[?#]/)[0] === '/home/profile');
  private readonly destroyRef = inject(DestroyRef);
  readonly error = signal('');
  readonly pending = signal(false);

  logout(): void {
    if (this.pending()) return;
    this.pending.set(true);
    this.error.set('');
    this.auth.logout().pipe(
      takeUntilDestroyed(this.destroyRef), finalize(() => this.pending.set(false)),
    ).subscribe({
      next: () => void this.router.navigateByUrl('/login'),
      error: error => this.error.set(authError(error)),
    });
  }
}
