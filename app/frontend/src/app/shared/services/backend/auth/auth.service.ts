import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of, tap } from 'rxjs';
import { BackendService } from '../backend.service';

export interface User { id: string; email: string; username: string; display_name: string; avatar_id: number; }

export function authError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) return 'We couldn’t reach the account service. Please try again.';
    if (typeof error.error?.error === 'string') return error.error.error;
  }
  return 'Something went wrong. Please try again.';
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly backend = inject(BackendService);
  readonly user = signal<User | null>(null);
  private readonly base = '/api/user/auth';
  private readonly mutationOptions = { headers: { 'X-G15-Request': '1' } };

  session() {
    return this.backend.get<{ user: User }>(`${this.base}/me`).pipe(
      tap(result => this.user.set(result.user)),
    );
  }

  submit(register: boolean, data: Record<string, string>) {
    return this.backend.post<{ user: User }>(`${this.base}/${register ? 'register' : 'login'}`, data, {
      ...this.mutationOptions, timeoutMs: 15000,
    }).pipe(tap(result => this.user.set(result.user)));
  }

  logout() {
    return this.backend.post(`${this.base}/logout`, {}, this.mutationOptions).pipe(
      tap(() => this.user.set(null)),
    );
  }
}

export const signedInGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return auth.session().pipe(
    map(() => true),
    catchError(() => {
      auth.user.set(null);
      return of(router.createUrlTree(['/login']));
    }),
  );
};

// Your own account has one interface (/home/profile); other users keep the public page.
export const publicProfileGuard: CanActivateFn = route => {
  const router = inject(Router);
  return inject(AuthService).user()?.id === route.paramMap.get('id') ? router.createUrlTree(['/home/profile']) : true;
};
