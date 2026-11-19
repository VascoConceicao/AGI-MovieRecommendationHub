import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, catchError, finalize, map, of, switchMap } from 'rxjs';
import { BackendService } from '../../../../shared/services/backend/backend.service';
import { authError } from '../../../../shared/services/backend/auth/auth.service';
import { WatchlistService } from '../../../../shared/services/backend/watchlist/watchlist.service';

interface Movie {
  id: string; title: string; synopsis: string | null; poster_url: string | null;
  release_date: string | null; duration_minutes: number | null; genres: string[] | null;
  actors: string[] | null; directors: string[] | null;
}
interface Page { movies: Movie[]; total: number; }

@Component({
  selector: 'app-my-list',
  imports: [DatePipe],
  templateUrl: './my-list.html',
  styleUrl: '../../../../shared/styles/movie-list.scss',
})
export class MyList {
  readonly watchlist = inject(WatchlistService);
  private readonly backend = inject(BackendService);
  private readonly destroyRef = inject(DestroyRef);
  readonly movies = signal<Movie[]>([]);
  readonly total = signal(0);
  readonly search = signal('');
  readonly loading = signal(false);
  private readonly query = signal('');
  private searchTimer?: ReturnType<typeof setTimeout>;
  readonly offset = signal(0);
  readonly currentPage = computed(() => Math.floor(this.offset() / 25) + 1);
  readonly pageCount = computed(() => Math.max(1, Math.ceil(this.total() / 25)));
  readonly error = signal('');
  readonly pending = signal<string | null>(null);
  readonly selected = signal<Movie | null>(null);
  readonly failedPosters = signal<Set<string>>(new Set());
  private readonly requests = new Subject<{ offset: number; ids: string[]; query: string }>();

  constructor() {
    this.destroyRef.onDestroy(() => clearTimeout(this.searchTimer));
    this.requests.pipe(switchMap(request => {
      this.error.set(''); this.loading.set(true);
      const ids = request.query ? this.backend.get<{ items: { movie_id: string }[]; total: number }>(
        `/api/user/profile/watchlist/search?q=${encodeURIComponent(request.query)}&offset=${request.offset}`, { timeoutMs: 15000 },
      ).pipe(map(page => ({ ids: page.items.map(item => item.movie_id), total: page.total })))
        : of({ ids: request.ids.slice(request.offset, request.offset + 25), total: request.ids.length });
      return ids.pipe(switchMap(page => page.ids.length ? this.backend.get<Page>('/api/movie/movies?ids=' + page.ids.join(',')).pipe(
        map(result => ({ movies: page.ids.flatMap(id => result.movies.filter(movie => movie.id === id)), total: page.total })),
      ) : of({ movies: [], total: page.total })),
      catchError(error => { this.error.set(authError(error)); this.movies.set([]); return of(null); }),
      finalize(() => this.loading.set(false)));
    }), takeUntilDestroyed()).subscribe(page => {
      if (page) {
        this.movies.set(page.movies); this.total.set(page.total);
        if (!page.movies.length && this.offset() > 0) this.offset.set(0);
      }
    });
    effect(() => {
      const ids = this.watchlist.ids();
      const offset = this.offset();
      const query = this.query();
      if (offset > 0 && offset >= ids.length) { this.offset.set(0); return; }
      this.requests.next({ ids, offset, query });
    });
  }

  searchMovies(value: string): void {
    this.search.set(value); clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => { this.offset.set(0); this.query.set(value.trim()); }, 250);
  }
  retry(): void { this.requests.next({ ids: this.watchlist.ids(), offset: this.offset(), query: this.query() }); }

  open(movie: Movie, dialog: HTMLDialogElement): void { this.selected.set(movie); dialog.showModal(); }
  backdrop(event: MouseEvent, dialog: HTMLDialogElement): void {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
  }
  markWatched(movie: Movie, dialog?: HTMLDialogElement): void {
    if (this.pending()) return;
    this.pending.set(movie.id); this.error.set('');
    this.watchlist.markWatched(movie.id).pipe(
      takeUntilDestroyed(this.destroyRef), finalize(() => this.pending.set(null)),
    ).subscribe({ next: () => dialog?.close(), error: error => this.error.set(authError(error)) });
  }
  toggle(movie: Movie, dialog?: HTMLDialogElement): void {
    if (this.pending()) return;
    this.pending.set(movie.id); this.error.set('');
    this.watchlist.update(movie.id, !this.watchlist.ids().includes(movie.id)).pipe(
      takeUntilDestroyed(this.destroyRef), finalize(() => this.pending.set(null)),
    ).subscribe({
      next: () => { if (this.selected()?.id === movie.id) dialog?.close(); },
      error: error => this.error.set(authError(error)),
    });
  }
  posterFailed(id: string): void { this.failedPosters.update(ids => new Set([...ids, id])); }
}
