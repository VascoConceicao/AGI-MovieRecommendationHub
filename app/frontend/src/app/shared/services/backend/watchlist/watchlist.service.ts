import { Injectable, inject, signal } from '@angular/core';
import { Subject, tap } from 'rxjs';
import { BackendService } from '../backend.service';
import { authError } from '../auth/auth.service';

@Injectable({ providedIn: 'root' })
export class WatchlistService {
  private readonly backend = inject(BackendService);
  readonly changed = new Subject<void>();
  readonly watchedIds = signal<string[]>([]);
  readonly ids = signal<string[]>([]);
  readonly error = signal('');
  readonly loaded = signal(false);
  private revision = 0;

  reset(): void { this.revision++; this.ids.set([]); this.watchedIds.set([]); this.error.set(''); this.loaded.set(false); }

  load(): void {
    const revision = ++this.revision;
    this.loaded.set(false);
    this.backend.get<{ ids: string[]; watched_ids: string[] }>('/api/user/profile/watchlist').subscribe({
      next: result => { if (revision === this.revision) { this.ids.set(result.ids); this.watchedIds.set(result.watched_ids); this.error.set(''); this.loaded.set(true); } },
      error: error => { if (revision === this.revision) this.error.set(authError(error)); },
    });
  }

  markWatched(id: string) {
    return this.backend.post('/api/user/profile/watched/add', { movie_id: id }, {
      headers: { 'X-G15-Request': '1' },
    }).pipe(tap(() => {
      this.revision++;
      this.ids.update(ids => ids.filter(value => value !== id));
      this.watchedIds.update(ids => [...new Set([...ids, id])]);
      this.changed.next();
    }));
  }

  markUnwatched(id: string) {
    return this.backend.post('/api/user/profile/watched/remove', { movie_id: id }, {
      headers: { 'X-G15-Request': '1' },
    }).pipe(tap(() => {
      this.revision++;
      this.error.set('');
      this.watchedIds.update(ids => ids.filter(value => value !== id));
      this.changed.next();
    }));
  }

  update(id: string, add: boolean) {
    return this.backend.post('/api/user/profile/watchlist', { movie_id: id, add }, {
      headers: { 'X-G15-Request': '1' },
    }).pipe(tap(() => {
      this.revision++;
      this.error.set('');
      this.ids.update(ids => add ? [id, ...ids.filter(value => value !== id)] : ids.filter(value => value !== id));
    }));
  }
}
