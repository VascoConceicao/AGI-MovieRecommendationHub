import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { expect, it } from 'vitest';
import { AuthService } from '../../shared/services/backend/auth/auth.service';
import { CreditsPage } from './credits';

it('links back to the right page for the session', () => {
  const user = signal<unknown>(null);
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AuthService, useValue: { user } }] });
  const fixture = TestBed.createComponent(CreditsPage); fixture.detectChanges();
  expect(fixture.nativeElement.querySelector('.back-link').getAttribute('href')).toBe('/login');
  user.set({ id: 'user' }); fixture.detectChanges();
  expect(fixture.nativeElement.querySelector('.back-link').getAttribute('href')).toBe('/home/profile');
  expect(fixture.nativeElement.textContent).toContain('not endorsed or certified by TMDB');
});
