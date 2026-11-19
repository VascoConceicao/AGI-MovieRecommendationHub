import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject, Observable, of, Subject, throwError } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { PublicProfilePage } from './public-profile';

const movie = { id: 'one', title: 'Movie' };
const identity = { id: 'user', username: 'alice', display_name: 'Alice', bio: null, avatar_id: 1 };
function result(items: any[] = []) { return { profile: identity, watched_total: 2, watch_minutes: 1500, collection: { items, total: items.length, offset: 0, limit: 25 } }; }
function setup() {
  const params = new BehaviorSubject(convertToParamMap({ id: 'user' }));
  const route = { paramMap: params, snapshot: { paramMap: params.value, queryParams: { q: 'alice' } } };
  const backend = { get: vi.fn((_url: string): Observable<any> => of(result())) };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: ActivatedRoute, useValue: route }, { provide: BackendService, useValue: backend }] });
  // Child movie interactions have their own tests; isolate the profile request lifecycle.
  TestBed.overrideComponent(PublicProfilePage, { set: { template: '' } });
  const fixture = TestBed.createComponent(PublicProfilePage); fixture.detectChanges();
  return { fixture, page: fixture.componentInstance, backend, route, params };
}
afterEach(() => vi.useRealTimers());
describe('PublicProfilePage', () => {
  it('loads identity, joins movie order and combines recommendation reasons', () => {
    const { page, backend } = setup();
    expect(page.profile()).toEqual(identity); expect(page.backParams).toEqual({ q: 'alice' });
    expect(page.watchDuration()).toEqual({ days: 1, minutes: 60 });
    backend.get.mockImplementation(url => of(url.startsWith('/api/movie') ? { movies: [{ id: 'other' }, movie] } : result([
      { movie_id: 'one', reason: 'First' }, { movie_id: 'missing' }, { movie_id: 'one', reason: 'Second' }])));
    page.selectTab('recommendations');
    expect(page.movies()).toEqual([movie]); expect(page.notes()).toEqual({ one: 'First\nSecond' });
    expect(page.searchable().recommendations).toBe(true); expect(page.watchedTotal()).toBe(2);
    expect(page.movieError()).toBe('');
    backend.get.mockImplementation(url => of(url.startsWith('/api/movie') ? { movies: [movie] } : result([{ movie_id: 'one' }, { movie_id: 'missing' }])));
    page.load(25); expect(page.movieError()).toContain('no longer available'); expect(page.offset()).toBe(25);
    expect(page.page(25)).toBe(2); expect(page.pages(0)).toBe(1); expect(page.pages(51)).toBe(3);
    for (const value of [null, Infinity, NaN]) { page.watchMinutes.set(value); expect(page.watchDuration()).toBeNull(); }
    page.watchMinutes.set(-3); expect(page.watchDuration()).toEqual({ days: 0, minutes: 0 });
  });
  it('handles movie and profile failures, clearing identity on access loss', () => {
    const { page, backend } = setup();
    backend.get.mockImplementation(url => url.startsWith('/api/movie') ? throwError(() => new Error('offline')) : of(result([{ movie_id: 'one' }])));
    page.load(0); expect(page.profile()).toEqual(identity); expect(page.movieError()).toContain('details unavailable');
    for (const status of [503, 401, 404]) {
      page.profile.set(identity); backend.get.mockReturnValue(throwError(() => ({ status })));
      page.load(0); expect(page.loading()).toBe(false); expect(page.collection()).toBeNull();
      expect(page.profile()).toEqual(status === 503 ? identity : null);
      expect(page.error()).not.toBe('');
    }
    expect(page.error()).toContain('private');
  });
  it('debounces search, cancels stale requests and resets on route changes', () => {
    vi.useFakeTimers();
    const { fixture, page, backend, route, params } = setup();
    const stale = new Subject<any>(); backend.get.mockReturnValueOnce(stale).mockReturnValue(of(result()));
    page.load(0); page.searchMovies('old'); page.searchMovies(' title ');
    vi.advanceTimersByTime(250); expect(backend.get).toHaveBeenLastCalledWith('/api/user/users/user?section=watchlist&offset=0&q=title', { timeoutMs: 15000 });
    stale.next(result([{ movie_id: 'stale' }])); expect(page.collection()?.items).toEqual([]);
    route.snapshot.paramMap = convertToParamMap({}); params.next(route.snapshot.paramMap);
    expect(page.searches()).toEqual({ watchlist: '', watched: '', recommendations: '' });
    expect(backend.get).toHaveBeenLastCalledWith('/api/user/users/?section=watchlist&offset=0&q=', { timeoutMs: 15000 });
    page.searchMovies('cancel'); const count = backend.get.mock.calls.length; fixture.destroy(); vi.runAllTimers(); expect(backend.get).toHaveBeenCalledTimes(count);
  });
  it('supports tab keyboard navigation and focus', () => {
    const { page } = setup();
    const button = document.createElement('button'); button.id = 'public-tab-watchlist'; document.body.append(button);
    const focus = vi.spyOn(button, 'focus');
    for (const [key, index, tab] of [['x', 0, 'watchlist'], ['End', 0, 'recommendations'], ['Home', 2, 'watchlist'], ['ArrowRight', 0, 'watched'], ['ArrowLeft', 0, 'recommendations']] as const) {
      const event = new KeyboardEvent('keydown', { key, cancelable: true }); page.navigateTab(event, index);
      expect(page.activeTab()).toBe(tab); expect(event.defaultPrevented).toBe(key !== 'x');
    }
    expect(focus).toHaveBeenCalledOnce(); button.remove();
  });
});
