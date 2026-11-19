import { Component, DestroyRef, effect, ElementRef, inject, OnInit, signal, viewChild } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, forkJoin, map, merge, of, Subject, switchMap, tap } from 'rxjs';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { authError } from '../../../shared/services/backend/auth/auth.service';
import { Movie, MovieResults } from '../../common/movie-results/movie-results';

type Filter = 'all' | 'movies' | 'users';
interface User { id: string; username: string; display_name: string; avatar_id: number; }
interface MoviePage { movies: Movie[]; total: number; offset: number; limit: number; }
interface UserPage { users: User[]; total: number; offset: number; limit: number; }

function searchSeed(): string {
  // getRandomValues also works on the HTTP demo origin. randomUUID needs HTTPS.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

@Component({
  selector: 'app-search',
  imports: [RouterLink, MovieResults],
  templateUrl: './search.html',
  styleUrl: './search.scss',
})
export class SearchTab implements OnInit {
  private readonly backend = inject(BackendService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly seed = searchSeed();
  private readonly reload = new Subject<void>();
  private readonly userGrid = viewChild<ElementRef<HTMLElement>>('userGrid');
  private userPageSize = 25;
  private movieBatch: { key: string; page: MoviePage } | null = null;
  private userBatch: { key: string; page: UserPage } | null = null;
  private timer?: ReturnType<typeof setTimeout>;
  readonly filters = [{ value: 'all', label: 'All' }, { value: 'movies', label: 'Movies' }, { value: 'users', label: 'Users' }] as const;
  readonly query = signal('');
  readonly hasSearchItems = signal(false);
  readonly filter = signal<Filter>('all');
  readonly loading = signal(false);
  readonly movies = signal<MoviePage | null>(null);
  readonly users = signal<UserPage | null>(null);
  readonly movieError = signal('');
  readonly userError = signal('');

  constructor() {
    effect(onCleanup => {
      const grid = this.userGrid()?.nativeElement;
      if (!grid) return;
      const observer = new ResizeObserver(() => {
        const columns = getComputedStyle(grid).gridTemplateColumns.split(/\s+/).filter(Boolean).length;
        const size = Math.ceil(25 / Math.max(1, columns)) * Math.max(1, columns);
        if (size === this.userPageSize) return;
        this.userPageSize = size;
        const offset = this.users()?.offset ?? 0;
        const aligned = Math.floor(offset / size) * size;
        if (offset !== aligned) this.navigate(this.filter(), 'users', aligned);
        else this.reload.next();
      });
      observer.observe(grid);
      onCleanup(() => observer.disconnect());
    });
  }

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => clearTimeout(this.timer));
    merge(this.route.queryParamMap, this.reload.pipe(map(() => this.route.snapshot.queryParamMap))).pipe(switchMap(params => {
      const q = (params.get('q') ?? '').slice(0, 200);
      const filter = params.get('type');
      this.query.set(q);
      this.filter.set(filter === 'movies' || filter === 'users' ? filter : 'all');
      this.loading.set(true); this.movieError.set(''); this.userError.set('');
      this.movies.set(null); this.users.set(null);
      const movieOffset = this.validOffset(params.get('movies'));
      const userOffset = this.validOffset(params.get('users'));
      return forkJoin({
        movies: this.filter() === 'users' ? of(null) : this.loadMovies(q.trim(), movieOffset).pipe(
          catchError(error => { this.movieError.set(authError(error)); return of(null); })),
        users: this.filter() === 'movies' ? of(null) : this.loadUsers(q.trim(), userOffset).pipe(
          catchError(error => { this.userError.set(authError(error)); return of(null); })),
      }).pipe(tap(result => {
        if (!q.trim()) this.hasSearchItems.set((result.movies?.total ?? 0) + (result.users?.total ?? 0) > 0);
      }));
    }), takeUntilDestroyed(this.destroyRef)).subscribe(result => {
      this.movies.set(result.movies); this.users.set(result.users); this.loading.set(false);
    });
  }

  private loadMovies(query: string, offset: number) {
    const start = Math.floor(offset / 1000) * 1000;
    const key = JSON.stringify([query, start]);
    const request = this.movieBatch?.key === key ? of(this.movieBatch.page) : this.backend.get<MoviePage>(
      `/api/movie/movies?q=${encodeURIComponent(query)}&offset=${start}&limit=1000&seed=${this.seed}`,
    ).pipe(tap(page => { this.movieBatch = { key, page }; }));
    return request.pipe(map(page => ({ ...page, offset, limit: 25, movies: page.movies.slice(offset - start, offset - start + 25) })));
  }

  private loadUsers(query: string, offset: number) {
    const limit = this.userPageSize;
    // Keep cached batches aligned with full pages, including the batch boundary.
    const batchSize = Math.floor(1000 / limit) * limit;
    const start = Math.floor(offset / batchSize) * batchSize;
    const key = JSON.stringify([query, start, batchSize]);
    const request = this.userBatch?.key === key ? of(this.userBatch.page) : this.backend.get<UserPage>(
      `/api/user/users?q=${encodeURIComponent(query)}&offset=${start}&limit=${batchSize}&seed=${this.seed}`,
    ).pipe(tap(page => { this.userBatch = { key, page }; }));
    return request.pipe(map(page => ({ ...page, offset, limit, users: page.users.slice(offset - start, offset - start + limit) })));
  }

  private validOffset(value: string | null): number {
    const offset = Number(value ?? 0);
    return Number.isInteger(offset) && offset >= 0 && offset <= 1000000 ? offset : 0;
  }
  search(value: string): void {
    this.query.set(value); clearTimeout(this.timer);
    this.timer = setTimeout(() => this.navigate(this.filter()), 250);
  }
  navigate(filter: Filter, kind?: 'movies' | 'users', offset = 0): void {
    clearTimeout(this.timer);
    const sameQuery = this.query() === (this.route.snapshot.queryParamMap.get('q') ?? '');
    void this.router.navigate([], {
      relativeTo: this.route, replaceUrl: true,
      queryParams: {
        q: this.query() || null, type: filter === 'all' ? null : filter,
        movies: kind === 'movies' ? offset : kind && sameQuery ? this.movies()?.offset ?? 0 : null,
        users: kind === 'users' ? offset : kind && sameQuery ? this.users()?.offset ?? 0 : null,
      },
    });
  }
  retry(): void { this.movieBatch = null; this.userBatch = null; this.reload.next(); }
  page(offset: number, limit = 25): number { return Math.floor(offset / limit) + 1; }
  pages(total: number, limit = 25): number { return Math.max(1, Math.ceil(total / limit)); }
}
