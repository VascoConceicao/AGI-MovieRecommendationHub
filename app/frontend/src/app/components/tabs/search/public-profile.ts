import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, map, of, Subject, switchMap, tap } from 'rxjs';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { authError } from '../../../shared/services/backend/auth/auth.service';
import { Movie, MovieResults } from '../../common/movie-results/movie-results';

type Section = 'watchlist' | 'watched' | 'recommendations';
interface Identity { id: string; username: string; display_name: string; bio: string | null; avatar_id: number; }
interface Collection {
  items: { movie_id: string; reason?: string; source?: string }[];
  total: number; offset: number; limit: number;
}
interface PublicProfile { profile: Identity; watched_total: number; watch_minutes: number | null; collection: Collection; }

@Component({
  selector: 'app-public-profile',
  imports: [RouterLink, MovieResults],
  templateUrl: './public-profile.html',
  styleUrls: ['./search.scss', './public-profile.scss'],
})
export class PublicProfilePage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly backend = inject(BackendService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly requests = new Subject<{ id: string; offset: number; section: Section; query: string }>();
  readonly tabs = [
    { id: 'watchlist', label: 'Their list', empty: 'No movies in their list yet.' },
    { id: 'watched', label: 'Watched movies', empty: 'No watched movies yet.' },
    { id: 'recommendations', label: 'Recommendations', empty: 'No recommendations yet.' },
  ] as const;
  readonly activeTab = signal<Section>('watchlist');
  readonly searchable = signal<Record<Section, boolean>>({ watchlist: false, watched: false, recommendations: false });
  readonly searches = signal<Record<Section, string>>({ watchlist: '', watched: '', recommendations: '' });
  private searchTimer?: ReturnType<typeof setTimeout>;
  readonly profile = signal<Identity | null>(null);
  readonly watchedTotal = signal(0);
  readonly watchMinutes = signal<number | null>(null);
  readonly watchDuration = computed(() => {
    const minutes = this.watchMinutes();
    if (typeof minutes !== 'number' || !Number.isFinite(minutes)) return null;
    const total = Math.max(0, Math.floor(minutes));
    return { days: Math.floor(total / 1440), minutes: total % 1440 };
  });
  readonly collection = signal<Collection | null>(null);
  readonly movies = signal<Movie[]>([]);
  readonly notes = signal<Record<string, string>>({});
  readonly loading = signal(false);
  readonly error = signal('');
  readonly movieError = signal('');
  readonly offset = signal(0);
  readonly backParams = this.route.snapshot.queryParams;

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => clearTimeout(this.searchTimer));
    this.requests.pipe(switchMap(({ id, offset, section, query }) => {
      this.collection.set(null); this.movies.set([]); this.notes.set({});
      this.error.set(''); this.movieError.set(''); this.loading.set(true);
      return this.backend.get<PublicProfile>(`/api/user/users/${encodeURIComponent(id)}?section=${section}&offset=${offset}&q=${encodeURIComponent(query)}`, { timeoutMs: 15000 }).pipe(
        tap(result => { if (!query) this.searchable.update(sections => ({ ...sections, [section]: result.collection.total > 0 })); }),
        switchMap(result => {
          const ids = [...new Set(result.collection.items.map(item => item.movie_id))];
          return (ids.length ? this.backend.get<{ movies: Movie[] }>('/api/movie/movies?ids=' + ids.join(',')).pipe(
            map(page => {
              if (page.movies.length < ids.length) this.movieError.set('Some movies are no longer available.');
              return ids.flatMap(id => page.movies.filter(movie => movie.id === id));
            }), catchError(() => { this.movieError.set('Movie details unavailable. Please retry.'); return of([] as Movie[]); }),
          ) : of([] as Movie[])).pipe(map(movies => ({ result, movies })));
        }),
        catchError(error => {
          if (error.status === 404 || error.status === 401) this.profile.set(null);
          this.error.set(error.status === 404 ? 'This profile is private or unavailable.' : authError(error));
          return of(null);
        }),
      );
    }), takeUntilDestroyed(this.destroyRef)).subscribe(page => {
      this.loading.set(false);
      if (page) {
        this.profile.set(page.result.profile); this.watchedTotal.set(page.result.watched_total);
        this.watchMinutes.set(page.result.watch_minutes);
        this.collection.set(page.result.collection); this.movies.set(page.movies);
        const notes: Record<string, string> = {};
        for (const item of page.result.collection.items) {
          if (item.reason) notes[item.movie_id] = [notes[item.movie_id], item.reason].filter(Boolean).join('\n');
        }
        this.notes.set(notes);
      }
    });
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.searchable.set({ watchlist: false, watched: false, recommendations: false });
      this.profile.set(null); this.searches.set({ watchlist: '', watched: '', recommendations: '' }); this.activeTab.set('watchlist'); this.load(0);
    });
  }
  searchMovies(value: string): void {
    this.searches.update(queries => ({ ...queries, [this.activeTab()]: value }));
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.load(0), 250);
  }
  selectTab(section: Section): void { this.activeTab.set(section); this.load(0); }
  navigateTab(event: KeyboardEvent, index: number): void {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    this.selectTab(this.tabs[next].id);
    document.getElementById('public-tab-' + this.tabs[next].id)?.focus();
  }
  load(offset: number): void {
    clearTimeout(this.searchTimer);
    this.offset.set(offset);
    this.requests.next({ id: this.route.snapshot.paramMap.get('id') ?? '', offset, section: this.activeTab(), query: this.searches()[this.activeTab()].trim() });
  }
  page(offset: number): number { return Math.floor(offset / 25) + 1; }
  pages(total: number): number { return Math.max(1, Math.ceil(total / 25)); }
}
