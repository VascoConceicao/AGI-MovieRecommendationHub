import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';
import { afterEach, expect, it, vi } from 'vitest';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { SearchTab } from './search';
import { PublicProfilePage } from './public-profile';
import { tabRoutes } from '../../../pages/home/tabs.routes';
import { AuthService } from '../../../shared/services/backend/auth/auth.service';

afterEach(() => vi.unstubAllGlobals());


it('renders routed search results and links public profiles', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  const backend = { get: vi.fn((url: string) => of(url.includes('/profile/watchlist') ? { ids: [], watched_ids: [] }
    : url.startsWith('/api/movie') ? { movies: [], total: 0 }
    : { users: [{ id: 'alice', username: 'alice', display_name: 'Alice', avatar_id: 2 }], total: 1 })) };
  TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'home/search', component: SearchTab }]), { provide: BackendService, useValue: backend }] });
  const harness = await RouterTestingHarness.create('/home/search');
  harness.detectChanges();
  expect(harness.routeNativeElement?.textContent).toContain('No movies found.');
  const link = harness.routeNativeElement?.querySelector('.user-card');
  expect(link?.textContent).toContain('Alice'); expect(link?.getAttribute('href')).toContain('/home/search/users/alice');
});


it('renders routed public identity, statistics and collection tabs', async () => {
  const backend = { get: vi.fn((url: string) => of(url.includes('/profile/watchlist') ? { ids: [], watched_ids: [] } : { profile: { id: 'user', username: 'alice', display_name: 'Alice', avatar_id: 1 }, watched_total: 2, watch_minutes: 1500, collection: { items: [], total: 0, offset: 0, limit: 25 } })) };
  TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'home/search/users/:id', component: PublicProfilePage }]), { provide: BackendService, useValue: backend }] });
  const harness = await RouterTestingHarness.create('/home/search/users/user?q=alice');
  harness.detectChanges();
  expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Alice');
  expect(harness.routeNativeElement?.textContent).toContain('No movies in their list yet.');
  expect(harness.routeNativeElement?.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('Their list');
  expect(harness.routeNativeElement?.querySelector('.back-link')?.getAttribute('href')).toBe('/home/search?q=alice');
});


it('redirects your own public profile URL to /home/profile but keeps other users public', async () => {
  const backend = { get: vi.fn(() => of({ profile: { id: 'other', username: 'bob', display_name: 'Bob', avatar_id: 1 }, watched_total: 0, watch_minutes: 0, collection: { items: [], total: 0, offset: 0, limit: 25 } })) };
  TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'home', children: tabRoutes.filter(route => route.path !== 'profile' && route.path !== 'search') .concat([{ path: 'profile', children: [] }]) }]), { provide: BackendService, useValue: backend }] });
  TestBed.inject(AuthService).user.set({ id: 'me', email: 'me@example.test', username: 'me', display_name: 'Me', avatar_id: 1 });
  const harness = await RouterTestingHarness.create('/home/search/users/me');
  expect(TestBed.inject(Router).url).toBe('/home/profile');
  expect(backend.get).not.toHaveBeenCalled();
  await harness.navigateByUrl('/home/search/users/other');
  harness.detectChanges();
  expect(TestBed.inject(Router).url).toBe('/home/search/users/other');
  expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toBe('Bob');
});
