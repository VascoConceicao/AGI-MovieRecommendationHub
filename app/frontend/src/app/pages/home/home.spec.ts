import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NavigationEnd, NavigationStart, provideRouter, Router } from '@angular/router';
import { Observable, of, Subject, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../shared/services/backend/auth/auth.service';
import { HomePage } from './home';

describe('HomePage logout', () => {
  function setup() {
    const auth = { user: signal({ display_name: 'Ana', email: 'ana@example.test' }), logout: vi.fn((): Observable<unknown> => new Subject()) };
    TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AuthService, useValue: auth }] });
    const fixture = TestBed.createComponent(HomePage);
    fixture.detectChanges();
    return { auth, fixture };
  }

  it('blocks repeated logout while pending', () => {
    const { auth, fixture } = setup();
    fixture.componentInstance.logout();
    fixture.componentInstance.logout();
    expect(auth.logout).toHaveBeenCalledTimes(1);
  });
  it('navigates to login after logout', () => {
    const { auth, fixture } = setup();
    auth.logout.mockReturnValue(of({}));
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture.componentInstance.logout();
    expect(navigate).toHaveBeenCalledWith('/login');
    expect(fixture.componentInstance.pending()).toBe(false);
  });
  it('shows API errors and enables retry', () => {
    const { auth, fixture } = setup();
    auth.logout.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503, error: { error: 'Try again' } })));
    fixture.componentInstance.logout();
    expect(fixture.componentInstance.error()).toBe('Try again');
    expect(fixture.componentInstance.pending()).toBe(false);
  });
});


it('tracks profile navigation after redirects and ignores unfinished navigation', () => {
  const events = new Subject<any>();
  const router = { url: '/home/search', events, navigateByUrl: vi.fn() };
  TestBed.configureTestingModule({ providers: [{ provide: Router, useValue: router }, { provide: AuthService, useValue: {} }] });
  TestBed.overrideComponent(HomePage, { set: { template: '' } });
  const fixture = TestBed.createComponent(HomePage); const page = fixture.componentInstance;
  expect(page.onProfile()).toBe(false);
  events.next(new NavigationStart(1, '/home/profile')); expect(page.onProfile()).toBe(false);
  events.next(new NavigationEnd(1, '/home', '/home/profile?q=x#tab')); expect(page.onProfile()).toBe(true);
  events.next(new NavigationEnd(2, '/home/search', '/home/search')); expect(page.onProfile()).toBe(false);
});
