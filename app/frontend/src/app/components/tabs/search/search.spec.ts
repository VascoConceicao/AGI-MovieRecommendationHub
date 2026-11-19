import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { BehaviorSubject, Observable, of, Subject, throwError } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { SearchTab } from './search';

function setup(grid = false) {
  const params = new BehaviorSubject(convertToParamMap({}));
  const route = { queryParamMap: params, snapshot: { queryParamMap: params.value } };
  const backend = { get: vi.fn((url: string): Observable<any> => of(url.startsWith('/api/movie')
    ? { movies: Array.from({ length: 1000 }, (_, i) => ({ id: String(i) })), total: 2000 }
    : { users: Array.from({ length: 1000 }, (_, i) => ({ id: String(i) })), total: 2000 })) };
  let resize!: () => void;
  const observer = { observe: vi.fn(), disconnect: vi.fn() };
  vi.stubGlobal('ResizeObserver', class { constructor(callback: () => void) { resize = callback; } observe = observer.observe; disconnect = observer.disconnect; });
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: ActivatedRoute, useValue: route }, { provide: BackendService, useValue: backend }] });
  TestBed.overrideComponent(SearchTab, { set: { template: grid ? '<div #userGrid style="display:grid;grid-template-columns:100px 100px 100px"></div>' : '' } });
  const fixture = TestBed.createComponent(SearchTab); fixture.detectChanges();
  const router = TestBed.inject(Router); const navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
  const change = (values: Record<string, string>) => { route.snapshot.queryParamMap = convertToParamMap(values); params.next(route.snapshot.queryParamMap); };
  return { fixture, page: fixture.componentInstance, backend, change, route, navigate, observer, resize: () => resize() };
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('SearchTab', () => {
  it('caches batches, slices pages and fetches new batches', () => {
    const { page, backend, change } = setup();
    expect(page.movies()?.movies).toHaveLength(25); expect(page.users()?.users).toHaveLength(25); expect(page.hasSearchItems()).toBe(true);
    change({ movies: '25', users: '25' }); expect(backend.get).toHaveBeenCalledTimes(2);
    expect(page.movies()?.movies[0].id).toBe('25'); expect(page.users()?.users[0].id).toBe('25');
    change({ movies: '1000', users: '1000' }); expect(backend.get).toHaveBeenCalledTimes(4);
    expect(backend.get.mock.calls[2][0]).toContain('offset=1000&limit=1000&seed=');
    page.retry(); expect(backend.get).toHaveBeenCalledTimes(6);
    change({ type: 'movies', q: ' title &' }); expect(page.users()).toBeNull(); expect(page.filter()).toBe('movies');
    expect(backend.get).toHaveBeenLastCalledWith(expect.stringContaining('q=title%20%26'));
    change({ type: 'users', q: 'x'.repeat(201) }); expect(page.movies()).toBeNull(); expect(page.query()).toHaveLength(200);
    expect(page.page(25)).toBe(2); expect(page.page(27, 27)).toBe(2); expect(page.pages(0)).toBe(1); expect(page.pages(28, 27)).toBe(2);
  });
  it('validates offsets and handles failures independently', () => {
    const { page, backend, change } = setup();
    for (const offset of ['-1', '1.5', '1000001', 'bad']) { change({ movies: offset, users: offset }); expect(page.movies()?.offset).toBe(0); expect(page.users()?.offset).toBe(0); }
    change({ movies: '1000000', users: '1000000' }); expect(page.movies()?.offset).toBe(1000000);
    backend.get.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503, error: { error: 'Retry' } }))); page.retry();
    expect(page.movieError()).toBe('Retry'); expect(page.userError()).toBe('Retry'); expect(page.hasSearchItems()).toBe(false); expect(page.loading()).toBe(false);
    backend.get.mockReturnValue(of({ movies: [], users: [], total: 0 }));
    change({ type: 'movies' }); expect(page.hasSearchItems()).toBe(false);
    change({ type: 'users' }); expect(page.hasSearchItems()).toBe(false);
  });
  it('debounces query edits, builds navigation and cancels requests on destroy', () => {
    vi.useFakeTimers();
    const { fixture, page, backend, change, navigate } = setup();
    page.navigate('all'); expect(navigate.mock.lastCall?.[1]?.queryParams).toEqual({ q: null, type: null, movies: null, users: null });
    change({ q: 'same', movies: '25', users: '50' });
    page.navigate('all', 'movies', 75); expect(navigate.mock.lastCall?.[1]?.queryParams).toEqual({ q: 'same', type: null, movies: 75, users: 50 });
    page.navigate('users', 'users', 100); expect(navigate.mock.lastCall?.[1]?.queryParams).toEqual({ q: 'same', type: 'users', movies: 25, users: 100 });
    page.movies.set(null); page.users.set(null);
    page.navigate('all', 'users', 25); expect(navigate.mock.lastCall?.[1]?.queryParams?.['movies']).toBe(0);
    page.navigate('all', 'movies', 25); expect(navigate.mock.lastCall?.[1]?.queryParams?.['users']).toBe(0);
    page.query.set('new'); page.navigate('all', 'movies', 25); expect(navigate.mock.lastCall?.[1]?.queryParams?.['users']).toBeNull();
    page.navigate('all', 'users', 25); expect(navigate.mock.lastCall?.[1]?.queryParams?.['movies']).toBeNull();
    page.search('old'); page.search('newest'); vi.advanceTimersByTime(250); expect(navigate.mock.lastCall?.[1]?.queryParams?.['q']).toBe('newest');
    const pending = new Subject<any>(); backend.get.mockReturnValue(pending); page.retry(); expect(page.loading()).toBe(true);
    page.search('cancel'); const calls = navigate.mock.calls.length; fixture.destroy(); vi.runAllTimers(); expect(navigate).toHaveBeenCalledTimes(calls);
    expect(pending.observed).toBe(false);
  });
  it('aligns responsive user pages and cleans up its observer', () => {
    const { fixture, page, resize, observer, navigate, change } = setup(true);
    expect(observer.observe).toHaveBeenCalledOnce();
    resize(); expect(page.users()?.limit).toBe(27);
    const previous = page.users(); resize(); expect(page.users()).toBe(previous);
    change({ users: '25' });
    const grid = fixture.nativeElement.querySelector('div') as HTMLElement; grid.style.gridTemplateColumns = '100px 100px';
    resize(); expect(navigate.mock.lastCall?.[1]?.queryParams?.['users']).toBe(0);
    page.users.set(null); grid.style.gridTemplateColumns = ''; resize(); expect(page.users()?.limit).toBe(25);
    fixture.destroy(); expect(observer.disconnect).toHaveBeenCalledOnce();
  });
});
