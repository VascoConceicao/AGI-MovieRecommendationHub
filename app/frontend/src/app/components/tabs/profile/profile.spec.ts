import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { AuthService } from '../../../shared/services/backend/auth/auth.service';
import { WatchlistService } from '../../../shared/services/backend/watchlist/watchlist.service';
import { ProfileTab } from './profile';

const profile = { display_name: 'Name', bio: 'Bio', avatar_id: 2 };
const movie = { id: 'one', title: 'Movie', release_date: '2020-01-01', duration_minutes: 90, genres: ['Drama'], poster_url: '/poster.jpg' };
const item = { movie_id: 'one', watched_at: null, movie };
const history = { items: [], total: 0, offset: 0, limit: 25, watch_minutes: 0 };

function setup() {
  const listeners = new Map<string, EventListener>();
  const events = { addEventListener: vi.fn((name: string, listener: EventListener) => listeners.set(name, listener)), close: vi.fn() };
  vi.stubGlobal('EventSource', vi.fn(function () { return events; }));
  const backend = { get: vi.fn((url: string): Observable<any> => of(url === '/api/user/profile' ? { profile } : history)),
    post: vi.fn((): Observable<any> => of({ profile })) };
  const watchlist = { changed: new Subject<void>(), ids: signal<string[]>([]), watchedIds: signal<string[]>([]), error: signal(''), reset: vi.fn(), load: vi.fn() };
  const auth = { user: signal({ display_name: 'Name', username: 'name' }) };
  TestBed.configureTestingModule({ providers: [{ provide: BackendService, useValue: backend },
    { provide: WatchlistService, useValue: watchlist }, { provide: AuthService, useValue: auth }] });
  const fixture = TestBed.createComponent(ProfileTab); fixture.detectChanges();
  const dialog = document.createElement('dialog'); dialog.showModal = vi.fn(() => { dialog.open = true; }); dialog.close = vi.fn();
  return { fixture, page: fixture.componentInstance, backend, watchlist, events, listeners, dialog };
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('ProfileTab', () => {
  it('loads recommendations when their tab is selected', () => {
    const { fixture, page, backend } = setup();
    expect(fixture.nativeElement.querySelector('app-profile-recommendations')).toBeNull();
    backend.get.mockReturnValue(of({ items: [], total: 0, offset: 0 }));
    page.activeTab.set('recommendations'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-profile-recommendations').textContent).toContain('Recommended for You');
    const loads = (source: string) => backend.get.mock.calls.filter(([url]) => url === `/api/user/profile/recommendations?source=${source}&offset=0`).length;
    expect([loads('auto'), loads('user_requested')]).toEqual([1, 0]);          // opens on "Recommended for You" only
    page.activeTab.set('watched'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-profile-recommendations')).toBeNull();
    page.activeTab.set('recommendations'); fixture.detectChanges();            // coming back reloads the saved results
    expect([loads('auto'), loads('user_requested')]).toEqual([2, 0]);
  });
  it('loads profile and refreshes history on live events', () => {
    const { fixture, page, backend, watchlist, events, listeners } = setup();
    expect(page.profile()).toEqual(profile);
    expect(watchlist.reset).toHaveBeenCalledOnce(); expect(watchlist.load).toHaveBeenCalledOnce();
    for (const name of ['ready', 'watched-changed', 'signed-out']) listeners.get(name)!(new Event(name));
    watchlist.changed.next();
    expect(watchlist.load).toHaveBeenCalledTimes(4);
    expect(events.close).toHaveBeenCalledOnce();
    backend.get.mockReturnValue(throwError(() => new Error('offline'))); page.loadProfile();
    expect(page.profileError()).not.toBe('');
    fixture.destroy(); expect(events.close).toHaveBeenCalledTimes(2); expect(watchlist.reset).toHaveBeenCalledTimes(2);
  });
  it('calculates watch duration and pagination safely', () => {
    const { page } = setup();
    for (const value of [null, NaN, Infinity, -3]) { page.watchMinutes.set(value); expect(page.watchDuration()).toEqual({ days: 0, minutes: 0 }); }
    page.watchMinutes.set(1501.9); expect(page.watchDuration()).toEqual({ days: 1, minutes: 61 });
    expect(page.currentPage()).toBe(1); expect(page.pageCount()).toBe(1);
    page.offset.set(25); page.matchedTotal.set(51);
    expect(page.currentPage()).toBe(2); expect(page.pageCount()).toBe(3);
    expect(page.avatarUrl(2)).toBe('/assets/avatars/avatar-2.svg');
  });
  it('supports keyboard tabs and restores dialog focus', () => {
    const { page, fixture, dialog } = setup();
    for (const [key, index, expected] of [['x', 0, 'my-list'], ['End', 0, 'recommendations'], ['Home', 2, 'my-list'],
      ['ArrowRight', 0, 'watched'], ['ArrowLeft', 0, 'recommendations']] as const) {
      page.navigateTab(new KeyboardEvent('keydown', { key }), index); expect(page.activeTab()).toBe(expected);
    }
    const trigger = document.createElement('button'); document.body.append(trigger);
    page.openMovie(item, dialog, trigger); expect(page.selectedMovie()).toEqual(item); expect(dialog.showModal).toHaveBeenCalledOnce();
    page.closeMovie(); expect(document.activeElement).toBe(trigger); expect(page.selectedMovie()).toBeNull();
    page.activeTab.set('watched'); fixture.detectChanges();
    trigger.remove(); page.openMovie(item, dialog, trigger); page.closeMovie();
    expect(document.activeElement?.id).toBe('history-title');
    page.closeMovie();
    fixture.nativeElement.querySelector('#history-title').remove(); page.closeMovie();
    fixture.nativeElement.querySelector('#profile-tab-my-list').remove();
    page.navigateTab(new KeyboardEvent('keydown', { key: 'Home' }), 0);
  });
  it('traps avatar picker focus and saves avatars', () => {
    const { page, backend, dialog } = setup();
    document.body.append(dialog);
    const first = document.createElement('button'), second = document.createElement('button');
    first.setAttribute('aria-pressed', 'true'); dialog.append(first, second);
    page.openPicker(dialog); expect(page.choosing()).toBe(true); expect(document.activeElement).toBe(first);
    page.trapPickerFocus(new KeyboardEvent('keydown', { key: 'x' }), dialog);
    page.trapPickerFocus(new KeyboardEvent('keydown', { key: 'Tab' }), dialog); expect(document.activeElement).toBe(second);
    page.trapPickerFocus(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true }), dialog); expect(document.activeElement).toBe(first);
    const pending = new Subject<any>(); backend.post.mockReturnValue(pending);
    page.chooseAvatar(3, dialog); page.chooseAvatar(4, dialog); expect(backend.post).toHaveBeenCalledOnce();
    pending.next({ profile: { ...profile, avatar_id: 3 } }); pending.complete();
    expect(page.profile()?.avatar_id).toBe(3); expect(page.saving()).toBe(false); expect(dialog.close).toHaveBeenCalledOnce();
    backend.post.mockReturnValue(throwError(() => new Error('offline'))); page.chooseAvatar(4, dialog); expect(page.profileError()).not.toBe('');
    page.pickerClosed(second); expect(page.choosing()).toBe(false); expect(document.activeElement).toBe(second);
    first.remove(); second.remove(); page.openPicker(dialog); page.trapPickerFocus(new KeyboardEvent('keydown', { key: 'Tab' }), dialog);
    dialog.remove();
  });
  it('dismisses only dialog backdrop clicks and remembers failed posters', () => {
    const { page, dialog } = setup();
    dialog.getBoundingClientRect = () => ({ left: 10, right: 30, top: 10, bottom: 30 } as DOMRect);
    for (const [x, y, target] of [[20, 20, dialog], [0, 0, document.body], [0, 20, dialog], [40, 20, dialog], [20, 0, dialog], [20, 40, dialog]] as const) {
      page.dismissBackdrop({ clientX: x, clientY: y, target } as unknown as MouseEvent, dialog);
    }
    expect(dialog.close).toHaveBeenCalledTimes(4);
    page.posterFailed('one'); expect(page.failedPosters().has('one')).toBe(true);
  });
  it('removes watched movies with pending and stale-dialog protection', () => {
    const { page, backend, dialog } = setup();
    page.markUnwatched(dialog); expect(backend.post).not.toHaveBeenCalled();
    page.selectedMovie.set(item);
    const pending = new Subject<any>(); backend.post.mockReturnValue(pending);
    page.markUnwatched(dialog); page.markUnwatched(dialog); expect(backend.post).toHaveBeenCalledOnce();
    pending.next({}); pending.complete();
    expect(dialog.close).toHaveBeenCalledOnce(); expect(page.removingWatched()).toBe(false);
    backend.post.mockReturnValue(throwError(() => new Error('offline'))); page.markUnwatched(dialog);
    expect(page.movieError()).not.toBe('');
    const stale = new Subject<any>(); backend.post.mockReturnValue(stale); page.markUnwatched(dialog);
    page.selectedMovie.set(null); stale.error(new Error('offline'));
    expect(page.historyError()).not.toBe('');
    const other = new Subject<any>(); backend.post.mockReturnValue(other); page.selectedMovie.set(item); page.markUnwatched(dialog);
    page.selectedMovie.set({ movie_id: 'other', watched_at: null }); other.next({}); other.complete();
    expect(dialog.close).toHaveBeenCalledOnce();
  });
  it('joins movie metadata and falls back from an empty later page', () => {
    const { page, backend } = setup();
    backend.get.mockReturnValueOnce(of({ ...history, offset: 25 })).mockReturnValueOnce(of({ ...history, items: [{ movie_id: 'one', watched_at: null }],
      total: 1, matched_total: 1, watch_minutes: 90 })).mockReturnValueOnce(of({ movies: [movie] }));
    page.loadHistory(25);
    expect(page.items()).toEqual([item]); expect(page.total()).toBe(1); expect(page.matchedTotal()).toBe(1);
    expect(page.watchMinutes()).toBe(90); expect(page.offset()).toBe(0); expect(page.moviesUnavailable()).toBe(false);
    backend.get.mockReturnValueOnce(of({ ...history, items: [{ movie_id: 'one', watched_at: null }], total: 1 }))
      .mockReturnValueOnce(throwError(() => new Error('offline')));
    page.loadHistory(0, true); expect(page.moviesUnavailable()).toBe(true); expect(page.items()[0].movie).toBeUndefined();
    backend.get.mockReturnValue(throwError(() => new Error('offline'))); page.loadHistory(0);
    expect(page.historyError()).not.toBe(''); expect(page.loading()).toBe(false);
  });
  it('debounces searches and queues the latest request behind a pending load', () => {
    vi.useFakeTimers();
    const { page, backend } = setup();
    const pending = new Subject<any>(); backend.get.mockReturnValueOnce(pending).mockReturnValue(of({ ...history, total: 3 }));
    page.loadHistory(0); page.searchHistory(' first '); page.searchHistory(' latest ');
    vi.advanceTimersByTime(250); page.loadHistory(25, true);
    pending.next({ ...history, total: 99 }); pending.complete();
    expect(page.total()).toBe(3);
    expect(backend.get).toHaveBeenLastCalledWith('/api/user/profile/watched?offset=25&q=latest');
    expect(page.search()).toBe(' latest '); expect(page.loading()).toBe(false);
  });
  it('does not start queued loads after destruction', () => {
    const { page, fixture, backend } = setup();
    backend.get.mockReturnValue(new Subject()); page.loadHistory(0); page.loadHistory(25);
    const calls = backend.get.mock.calls.length; fixture.destroy();
    expect(backend.get).toHaveBeenCalledTimes(calls);
  });
});

it('saves privacy, prevents overlapping saves and reports errors', () => {
  const { page, backend } = setup();
  page.saving.set(true); page.setPrivacy(true); expect(backend.post).not.toHaveBeenCalled(); page.saving.set(false);
  const pending = new Subject<any>(); backend.post.mockReturnValue(pending);
  page.setPrivacy(true); page.setPrivacy(false); expect(backend.post).toHaveBeenCalledOnce();
  expect(backend.post).toHaveBeenCalledWith('/api/user/profile/visibility', { is_public: true }, { headers: { 'X-G15-Request': '1' } });
  pending.next({ profile: { ...profile, is_public: true } }); pending.complete();
  expect(page.profile()?.is_public).toBe(true); expect(page.savingPrivacy()).toBe(false);
  backend.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503, error: { error: 'Retry' } }))); page.setPrivacy(false);
  expect(page.profileError()).toBe('Retry'); expect(page.savingPrivacy()).toBe(false);
});

it('moves watched movies to the list and handles a signed-out account during profile updates', () => {
  const { page, backend, dialog, watchlist } = setup();
  page.selectedMovie.set(item); page.markUnwatched(dialog, true);
  expect(backend.post).toHaveBeenCalledWith('/api/user/profile/watched/move-to-list', { movie_id: 'one' }, { headers: { 'X-G15-Request': '1' } });
  expect(watchlist.load).toHaveBeenCalledTimes(2);
  TestBed.inject(AuthService).user.set(null);
  backend.get.mockReturnValue(of({ profile })); page.loadProfile(); page.chooseAvatar(2, dialog);
  expect(TestBed.inject(AuthService).user()).toBeNull(); expect(page.profile()).toEqual(profile);
});
