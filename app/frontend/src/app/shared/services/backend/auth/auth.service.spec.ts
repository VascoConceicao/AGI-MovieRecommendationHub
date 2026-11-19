import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { convertToParamMap, provideRouter, UrlTree } from '@angular/router';
import { firstValueFrom, Observable } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AuthService, authError, publicProfileGuard, signedInGuard, User } from './auth.service';

const user: User = { id: '1', username: 'ana', email: 'ana@example.test', display_name: 'Ana Silva', avatar_id: 7 };

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('loads the current user', () => {
    service.session().subscribe();
    http.expectOne('/api/user/auth/me').flush({ user });
    expect(service.user()).toEqual(user);
  });

  for (const register of [true, false]) {
    it(`submits ${register ? 'registration' : 'login'} with the mutation header`, () => {
      const data = { email: user.email, password: 'test' };
      service.submit(register, data).subscribe();
      const request = http.expectOne(`/api/user/auth/${register ? 'register' : 'login'}`);
      expect(request.request.headers.get('X-G15-Request')).toBe('1');
      expect(request.request.body).toEqual(data);
      request.flush({ user });
      expect(service.user()).toEqual(user);
    });
  }

  it('clears the user after logout', () => {
    service.user.set(user);
    service.logout().subscribe();
    http.expectOne('/api/user/auth/logout').flush({ message: 'Signed out.' });
    expect(service.user()).toBeNull();
  });

  it('allows authenticated routes', async () => {
    const result = TestBed.runInInjectionContext(() => signedInGuard({} as never, {} as never)) as Observable<boolean | UrlTree>;
    const pending = firstValueFrom(result);
    http.expectOne('/api/user/auth/me').flush({ user });
    expect(await pending).toBe(true);
  });

  it('redirects unauthenticated users', async () => {
    const result = TestBed.runInInjectionContext(() => signedInGuard({} as never, {} as never)) as Observable<boolean | UrlTree>;
    const pending = firstValueFrom(result);
    http.expectOne('/api/user/auth/me').flush({ error: 'Sign in' }, { status: 401, statusText: 'Unauthorized' });
    expect((await pending).toString()).toBe('/login');
    expect(service.user()).toBeNull();
  });

  describe('publicProfileGuard', () => {
    const run = (id: string) => TestBed.runInInjectionContext(() =>
      publicProfileGuard({ paramMap: convertToParamMap({ id }) } as never, {} as never));

    it('sends you to your own profile page when you open your public profile', () => {
      service.user.set(user);
      expect(run('1').toString()).toBe('/home/profile');
    });

    it('lets you open other users and any profile while the session user is unknown', () => {
      service.user.set(user);
      expect(run('2')).toBe(true);
      service.user.set(null);
      expect(run('1')).toBe(true);
    });
  });
});

describe('authError', () => {
  it('shows the duplicate message supplied by the API', () => {
    expect(authError(new HttpErrorResponse({ status: 409, error: { error: 'Username already exists.' } })))
      .toBe('Username already exists.');
  });
  it('handles unavailable servers and unknown errors', () => {
    expect(authError(new HttpErrorResponse({ status: 0 }))).toContain('couldn’t reach');
    expect(authError(new Error())).toContain('Something went wrong');
    expect(authError(new HttpErrorResponse({ status: 500 }))).toContain('Something went wrong');
  });
});
