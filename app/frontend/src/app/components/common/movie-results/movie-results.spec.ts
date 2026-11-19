import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { WatchlistService } from '../../../shared/services/backend/watchlist/watchlist.service';
import { MovieResults, Movie } from './movie-results';

const movie: Movie = { id: 'one', title: 'Movie', synopsis: null, poster_url: null, release_date: null, duration_minutes: null, genres: null, actors: null, directors: null };
function setup() {
  const watchlist = { ids: signal<string[]>([]), watchedIds: signal<string[]>([]), loaded: signal(true), error: signal(''),
    reset: vi.fn(), load: vi.fn(), update: vi.fn(() => of({})), markWatched: vi.fn(() => of({})), markUnwatched: vi.fn(() => of({})) };
  TestBed.configureTestingModule({ providers: [{ provide: WatchlistService, useValue: watchlist }] });
  const fixture = TestBed.createComponent(MovieResults);
  fixture.componentRef.setInput('movies', [movie]); fixture.detectChanges();
  const dialog = document.createElement('dialog'); dialog.showModal = vi.fn(); dialog.close = vi.fn();
  return { fixture, page: fixture.componentInstance, watchlist, dialog };
}
describe('MovieResults', () => {
  it('loads status, opens details, restores connected focus and resets on destroy', () => {
    const { fixture, page, watchlist, dialog } = setup();
    expect(watchlist.reset).toHaveBeenCalledOnce(); expect(watchlist.load).toHaveBeenCalledOnce();
    page.close();
    const trigger = document.createElement('button'); const focus = vi.spyOn(trigger, 'focus');
    page.open(movie, dialog, trigger); page.close(); expect(focus).not.toHaveBeenCalled();
    document.body.append(trigger);
    page.open(movie, dialog, trigger); expect(page.selected()).toEqual(movie);
    expect(dialog.showModal).toHaveBeenCalledTimes(2);
    page.close(); expect(page.selected()).toBeNull(); expect(focus).toHaveBeenCalledOnce(); trigger.remove();
    page.posterFailed('one'); expect(page.failedPosters().has('one')).toBe(true);
    fixture.destroy(); expect(watchlist.reset).toHaveBeenCalledTimes(2);
  });
  it('dismisses only backdrop clicks outside dialog bounds', () => {
    const { page, dialog } = setup();
    dialog.getBoundingClientRect = () => ({ left: 10, right: 30, top: 10, bottom: 30 } as DOMRect);
    for (const [x, y, target] of [[20,20,dialog], [0,0,document.body], [0,20,dialog], [40,20,dialog], [20,0,dialog], [20,40,dialog]] as const)
      page.backdrop({ clientX:x, clientY:y, target } as unknown as MouseEvent, dialog);
    expect(dialog.close).toHaveBeenCalledTimes(4);
  });
  it('guards unloaded, pending and watched list actions', () => {
    const { page, watchlist, dialog } = setup();
    watchlist.loaded.set(false); page.save(movie, 'list', dialog); expect(watchlist.update).not.toHaveBeenCalled();
    watchlist.loaded.set(true); watchlist.watchedIds.set(['one']); page.save(movie, 'list', dialog); expect(watchlist.update).not.toHaveBeenCalled();
    watchlist.watchedIds.set([]); const pending = new Subject<{}>(); watchlist.update.mockReturnValue(pending);
    page.selected.set(movie); page.save(movie, 'list', dialog); page.save(movie, 'watched', dialog);
    expect(watchlist.update).toHaveBeenCalledWith('one', true); expect(watchlist.markWatched).not.toHaveBeenCalled();
    pending.next({}); pending.complete(); expect(page.pending()).toBe(false); expect(dialog.close).toHaveBeenCalledOnce();
    watchlist.update.mockReturnValue(of({})); watchlist.ids.set(['one']); page.selected.set(null); page.save(movie, 'list', dialog);
    expect(watchlist.update).toHaveBeenLastCalledWith('one', false); expect(dialog.close).toHaveBeenCalledOnce();
    page.save(movie, 'watched', dialog); expect(watchlist.markWatched).toHaveBeenCalledWith('one');
    watchlist.watchedIds.set(['one']); page.save(movie, 'watched', dialog); expect(watchlist.markUnwatched).toHaveBeenCalledWith('one');
  });
  it('shows errors only for the current movie and reloads status', () => {
    const { page, watchlist, dialog } = setup();
    watchlist.update.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 503, error: { error: 'Retry' } })));
    page.save(movie, 'list', dialog); expect(page.error()).toBe('');
    page.selected.set({ ...movie, id: 'other' }); page.save(movie, 'list', dialog); expect(page.error()).toBe('');
    page.selected.set(movie); page.save(movie, 'list', dialog); expect(page.error()).toBe('Retry');
    expect(watchlist.load).toHaveBeenCalledTimes(4); expect(page.pending()).toBe(false);
  });
});
