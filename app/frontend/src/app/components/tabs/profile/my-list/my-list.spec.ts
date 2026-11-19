import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { BackendService } from '../../../../shared/services/backend/backend.service';
import { WatchlistService } from '../../../../shared/services/backend/watchlist/watchlist.service';
import { MyList } from './my-list';

const movie = { id: 'one', title: 'Movie', synopsis: 'Plot', poster_url: null, release_date: null, duration_minutes: 90, genres: ['Drama'], actors: ['Actor'], directors: ['Director'] };
function setup() {
  const backend = { get: vi.fn((_url: string): Observable<any> => of({ movies: [movie] })) };
  const watchlist = { ids: signal<string[]>([]), error: signal(''), watchedIds: signal<string[]>([]), markWatched: vi.fn(() => of({})), update: vi.fn(() => of({})) };
  TestBed.configureTestingModule({ providers: [{ provide: BackendService, useValue: backend }, { provide: WatchlistService, useValue: watchlist }] });
  const fixture = TestBed.createComponent(MyList);
  fixture.detectChanges();
  return { fixture, collection: fixture.componentInstance, backend, watchlist };
}

describe('MyList', () => {
  it('loads IDs in watchlist order and resets invalid pagination', () => {
    const { fixture, collection, backend, watchlist } = setup();
    expect(collection.movies()).toEqual([]);
    watchlist.ids.set(['missing', 'one']); fixture.detectChanges();
    expect(collection.movies()).toEqual([movie]);
    expect(collection.total()).toBe(2);
    expect(collection.pageCount()).toBe(1);
    expect(collection.currentPage()).toBe(1);
    collection.offset.set(25); fixture.detectChanges();
    expect(collection.offset()).toBe(0);
    watchlist.ids.set(Array.from({ length: 30 }, (_, i) => String(i)));
    backend.get.mockReturnValue(of({ movies: [] }));
    collection.offset.set(25); fixture.detectChanges();
    expect(collection.offset()).toBe(0);
    expect(collection.pageCount()).toBe(2);
  });
  it('reports load failures and retains the previous page', () => {
    const { fixture, collection, backend, watchlist } = setup();
    backend.get.mockReturnValue(throwError(() => new Error('offline')));
    watchlist.ids.set(['one']); fixture.detectChanges();
    expect(collection.error()).not.toBe('');
    expect(collection.movies()).toEqual([]);
  });
  it('opens details and closes only outside the dialog bounds', () => {
    const { collection } = setup();
    const dialog = document.createElement('dialog');
    dialog.showModal = vi.fn(); dialog.close = vi.fn();
    dialog.getBoundingClientRect = () => ({ left: 10, right: 30, top: 10, bottom: 30 } as DOMRect);
    collection.open(movie, dialog);
    expect(collection.selected()).toEqual(movie);
    expect(dialog.showModal).toHaveBeenCalledOnce();
    for (const [x, y, target] of [[20, 20, dialog], [0, 0, document.body], [0, 20, dialog], [40, 20, dialog], [20, 0, dialog], [20, 40, dialog]] as const) {
      collection.backdrop({ clientX: x, clientY: y, target } as unknown as MouseEvent, dialog);
    }
    expect(dialog.close).toHaveBeenCalledTimes(4);
    collection.posterFailed('one'); expect(collection.failedPosters().has('one')).toBe(true);
  });
  it('serializes mutations and reports errors', () => {
    const { collection, watchlist } = setup();
    const pending = new Subject<{}>(); watchlist.markWatched.mockReturnValue(pending);
    const dialog = { close: vi.fn() } as unknown as HTMLDialogElement;
    collection.markWatched(movie, dialog); collection.markWatched(movie); collection.toggle(movie);
    expect(watchlist.markWatched).toHaveBeenCalledOnce();
    expect(watchlist.update).not.toHaveBeenCalled();
    pending.next({}); pending.complete();
    expect(dialog.close).toHaveBeenCalledOnce();
    expect(collection.pending()).toBeNull();
    watchlist.markWatched.mockReturnValue(of({})); collection.markWatched(movie);
    watchlist.markWatched.mockReturnValue(throwError(() => new Error('offline'))); collection.markWatched(movie);
    expect(collection.error()).not.toBe('');
    collection.toggle(movie); expect(watchlist.update).toHaveBeenLastCalledWith('one', true);
    watchlist.ids.set(['one']); collection.toggle(movie); expect(watchlist.update).toHaveBeenLastCalledWith('one', false);
    watchlist.update.mockReturnValue(throwError(() => new Error('offline'))); collection.toggle(movie);
    expect(collection.error()).not.toBe('');
    expect(collection.pending()).toBeNull();
  });
});

it('debounces list search, joins matching IDs and retries', () => {
  vi.useFakeTimers();
  try {
    const { fixture, collection, backend } = setup();
    backend.get.mockImplementation(url => of(url.startsWith('/api/movie') ? { movies: [movie] } : { items: [{ movie_id: 'one' }], total: 1 }));
    collection.searchMovies('old'); collection.searchMovies(' title '); vi.advanceTimersByTime(250); fixture.detectChanges();
    expect(backend.get).toHaveBeenCalledWith('/api/user/profile/watchlist/search?q=title&offset=0', { timeoutMs: 15000 });
    expect(collection.movies()).toEqual([movie]); expect(collection.total()).toBe(1); expect(collection.search()).toBe(' title ');
    collection.retry(); expect(collection.loading()).toBe(false);
    const dialog = { close: vi.fn() } as unknown as HTMLDialogElement;
    collection.selected.set(movie); collection.toggle(movie, dialog); expect(dialog.close).toHaveBeenCalledOnce();
    collection.toggle(movie); expect(collection.pending()).toBeNull();
    collection.searchMovies('cancel'); const calls = backend.get.mock.calls.length; fixture.destroy(); vi.runAllTimers(); expect(backend.get).toHaveBeenCalledTimes(calls);
  } finally { vi.useRealTimers(); }
});
