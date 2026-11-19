import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { Observable, of, Subject, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../shared/services/backend/auth/auth.service';
import { AuthPage } from './auth';

function setup() {
  const auth = { user: signal(null), session: () => throwError(() => new Error('not logged in')),
    submit: vi.fn((_register: boolean, _data: Record<string, string>): Observable<unknown> => new Subject()) };
  TestBed.configureTestingModule({ providers: [provideRouter([]),
    { provide: ActivatedRoute, useValue: { data: of({ register: true }) } },
    { provide: AuthService, useValue: auth }] });
  const fixture = TestBed.createComponent(AuthPage);
  fixture.detectChanges();
  const form = fixture.nativeElement.querySelector('form') as HTMLFormElement;
  for (const [name, value] of Object.entries({ username: 'admin', display_name: 'Admin', email: 'other@example.test', password: 'test', password_confirmation: 'test' })) {
    (form.elements.namedItem(name) as HTMLInputElement).value = value;
  }
  return { fixture, form, auth };
}

describe('registration form', () => {
  it('resets the form and navigates after a successful submission', () => {
    const { fixture, form, auth } = setup();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    auth.submit.mockReturnValue(of({}));
    fixture.componentInstance.register.set(false);
    fixture.componentInstance.submit(new Event('submit'), form);
    expect(navigate).toHaveBeenCalledWith('/home');
    expect((form.elements.namedItem('email') as HTMLInputElement).value).toBe('');
    expect(fixture.componentInstance.pending()).toBe(false);
  });

  it('redirects an existing session to home', () => {
    TestBed.configureTestingModule({ providers: [provideRouter([]),
      { provide: ActivatedRoute, useValue: { data: of({ register: false }) } },
      { provide: AuthService, useValue: { user: signal(null), session: () => of({}) } }] });
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const fixture = TestBed.createComponent(AuthPage);
    expect(fixture.componentInstance.register()).toBe(false);
    expect(navigate).toHaveBeenCalledWith('/home');
  });
  it('requires a username and blocks mismatched passwords', () => {
    const { fixture, form, auth } = setup();
    expect(form.querySelector<HTMLInputElement>('[name=username]')?.required).toBe(true);
    (form.elements.namedItem('password_confirmation') as HTMLInputElement).value = 'wrong';
    fixture.componentInstance.submit(new Event('submit'), form);
    expect(auth.submit).not.toHaveBeenCalled();
    expect(fixture.componentInstance.error()).toContain('do not match');
  });

  it('submits username and displays duplicate errors', () => {
    const { fixture, form, auth } = setup();
    auth.submit.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 409, error: { error: 'Username already exists.' } })));
    fixture.componentInstance.submit(new Event('submit'), form);
    fixture.detectChanges();
    expect(auth.submit.mock.calls[0]?.[1]).toMatchObject({ username: 'admin' });
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain('Username already exists.');
    expect(fixture.componentInstance.pending()).toBe(false);
  });

  it('does not submit twice while pending', () => {
    const { fixture, form, auth } = setup();
    fixture.componentInstance.submit(new Event('submit'), form);
    fixture.componentInstance.submit(new Event('submit'), form);
    expect(auth.submit).toHaveBeenCalledTimes(1);
  });
});
