import { TestBed } from '@angular/core/testing';
import { Subject, of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { BackendService } from '../backend.service';
import { WatchlistService } from './watchlist.service';

function setup() {
  const backend = { get: vi.fn(), post: vi.fn(() => of({})) };
  TestBed.configureTestingModule({ providers: [{ provide: BackendService, useValue: backend }] });
  return { backend, service: TestBed.inject(WatchlistService) };
}

describe('WatchlistService', () => {
  it('ignores stale loads and clears state on reset', () => {
    const { backend, service } = setup();
    const old = new Subject<unknown>(), fresh = new Subject<unknown>();
    backend.get.mockReturnValueOnce(old).mockReturnValueOnce(fresh);
    service.load(); service.load();
    fresh.next({ ids: ['new'], watched_ids: ['watched'] });
    old.next({ ids: ['old'], watched_ids: [] });
    old.error(new Error('stale'));
    expect(service.ids()).toEqual(['new']);
    expect(service.watchedIds()).toEqual(['watched']);
    expect(service.error()).toBe('');
    service.reset();
    expect(service.ids()).toEqual([]);
    expect(service.watchedIds()).toEqual([]);
  });
  it('reports load errors and ignores responses after reset', () => {
    const { backend, service } = setup();
    const failed = new Subject<unknown>(), stale = new Subject<unknown>();
    backend.get.mockReturnValueOnce(failed).mockReturnValueOnce(stale);
    service.load(); failed.error(new Error('offline'));
    expect(service.error()).not.toBe('');
    service.load(); service.reset(); stale.next({ ids: ['old'], watched_ids: [] });
    expect(service.ids()).toEqual([]);
    expect(service.error()).toBe('');
  });
  it('updates unique IDs and broadcasts watched changes only after success', () => {
    const { backend, service } = setup();
    const changed = vi.fn(); service.changed.subscribe(changed);
    service.ids.set(['one', 'two']);
    service.update('two', true).subscribe();
    expect(service.ids()).toEqual(['two', 'one']);
    service.update('one', false).subscribe();
    expect(service.ids()).toEqual(['two']);
    service.watchedIds.set(['two']);
    service.markWatched('two').subscribe();
    expect(service.ids()).toEqual([]);
    expect(service.watchedIds()).toEqual(['two']);
    expect(changed).toHaveBeenCalledOnce();
    expect(backend.post).toHaveBeenLastCalledWith('/api/user/profile/watched/add', { movie_id: 'two' }, { headers: { 'X-G15-Request': '1' } });
  });
});

it('marks a movie unwatched, clears errors and broadcasts after success', () => {
  const { backend, service } = setup();
  const changed = vi.fn(); service.changed.subscribe(changed);
  service.watchedIds.set(['one', 'two']); service.error.set('Old error');
  service.markUnwatched('one').subscribe();
  expect(service.watchedIds()).toEqual(['two']); expect(service.error()).toBe(''); expect(changed).toHaveBeenCalledOnce();
  expect(backend.post).toHaveBeenCalledWith('/api/user/profile/watched/remove', { movie_id: 'one' }, { headers: { 'X-G15-Request': '1' } });
});
