import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { Toggle } from '../../common/toggle/toggle';
import { DatePipe } from '@angular/common';
import { MyList } from './my-list/my-list';
import { ProfileRecommendations } from './recommendations/recommendations';
import { WatchlistService } from '../../../shared/services/backend/watchlist/watchlist.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, finalize, forkJoin, map, of, switchMap } from 'rxjs';
import { BackendService } from '../../../shared/services/backend/backend.service';
import { AuthService, authError } from '../../../shared/services/backend/auth/auth.service';

interface Profile { display_name: string; bio: string | null; avatar_id: number; is_public: boolean; }
interface Movie { id: string; title: string; release_date: string | null; duration_minutes: number | null; genres: string[] | null; poster_url: string | null;
  original_title?: string | null; synopsis?: string | null; movie_type?: string | null;
  actors?: string[] | null; directors?: string[] | null; languages?: string[] | null; countries?: string[] | null;
}
interface Watched { movie_id: string; watched_at: string | null; movie?: Movie; }
interface History { matched_total?: number; watch_minutes: number | null; items: Watched[]; total: number; offset: number; limit: number; }

@Component({
  selector: 'app-profile',
  imports: [DatePipe, MyList, ProfileRecommendations, Toggle],
  templateUrl: './profile.html',
  styleUrl: './profile.scss',
})
export class ProfileTab implements OnInit {
  readonly activeTab = signal<'my-list' | 'watched' | 'recommendations'>('my-list');
  readonly profileTabs = [{ id: 'my-list', label: 'My list' }, { id: 'watched', label: 'Watched' }, { id: 'recommendations', label: 'Recommendations' }] as const;
  private readonly watchlist = inject(WatchlistService);

  navigateTab(event: KeyboardEvent, index: number): void {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    this.activeTab.set(this.profileTabs[next].id);
    document.getElementById('profile-tab-' + this.profileTabs[next].id)?.focus();
  }
  readonly auth = inject(AuthService);
  private readonly backend = inject(BackendService);
  private readonly destroyRef = inject(DestroyRef);
  private historyPending = false;
  private historyQueued = false;
  readonly removingWatched = signal(false);
  readonly movieError = signal('');
  readonly selectedMovie = signal<Watched | null>(null);
  private movieTrigger: HTMLButtonElement | null = null;
  readonly profile = signal<Profile | null>(null);
  readonly avatars = ['Orbit', 'Fox', 'Cat', 'Robot', 'Owl', 'Ghost', 'Sun', 'Mountain', 'Flower', 'Cinema'];
  readonly choosing = signal(false);
  readonly saving = signal(false);
  readonly savingPrivacy = signal(false);
  readonly profileError = signal('');
  readonly items = signal<Watched[]>([]);
  readonly total = signal(0);
  readonly watchMinutes = signal<number | null>(null);
  readonly watchDuration = computed(() => {
    const value = this.watchMinutes();
    const total = typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
    return { days: Math.floor(total / 1440), minutes: total % 1440 };
  });
  readonly search = signal('');
  readonly matchedTotal = signal(0);
  private searchTimer?: ReturnType<typeof setTimeout>;
  private queuedOffset = 0;
  private queuedBackground = false;
  readonly offset = signal(0);
  readonly currentPage = computed(() => Math.floor(this.offset() / 25) + 1);
  readonly pageCount = computed(() => Math.max(1, Math.ceil(this.matchedTotal() / 25)));
  readonly loading = signal(false);
  readonly historyError = signal('');
  readonly moviesUnavailable = signal(false);
  readonly failedPosters = signal<Set<string>>(new Set());

  ngOnInit(): void {
    this.watchlist.changed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.loadHistory(this.offset(), true));
    this.watchlist.reset();
    this.watchlist.load();
    this.loadProfile();
    this.loadHistory(0);
    const events = new EventSource('/api/user/profile/events');
    const refresh = () => { this.loadHistory(this.offset(), true); this.watchlist.load(); };
    events.addEventListener('ready', refresh);
    events.addEventListener('watched-changed', refresh);
    events.addEventListener('signed-out', () => { events.close(); refresh(); });
    this.destroyRef.onDestroy(() => { events.close(); this.watchlist.reset(); clearTimeout(this.searchTimer); });
  }

  avatarUrl(id: number): string { return `/assets/avatars/avatar-${id}.svg`; }

  loadProfile(): void {
    this.profileError.set('');
    this.backend.get<{ profile: Profile }>('/api/user/profile').pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => {
        this.profile.set(result.profile);
        this.auth.user.update(user => user ? { ...user, avatar_id: result.profile.avatar_id } : user);
      },
      error: error => this.profileError.set(authError(error)),
    });
  }

  setPrivacy(isPublic: boolean): void {
    if (this.savingPrivacy() || this.saving()) return;
    this.savingPrivacy.set(true);
    this.profileError.set('');
    this.backend.post<{ profile: Profile }>('/api/user/profile/visibility', { is_public: isPublic }, {
      headers: { 'X-G15-Request': '1' },
    }).pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.savingPrivacy.set(false))).subscribe({
      next: result => this.profile.set(result.profile),
      error: error => this.profileError.set(authError(error)),
    });
  }

  openMovie(item: Watched, dialog: HTMLDialogElement, trigger: HTMLButtonElement): void {
    this.movieError.set('');
    this.selectedMovie.set(item);
    this.movieTrigger = trigger;
    dialog.showModal();
  }

  markUnwatched(dialog: HTMLDialogElement, moveToList = false): void {
    const item = this.selectedMovie();
    if (!item || this.removingWatched()) return;
    this.removingWatched.set(true);
    this.movieError.set('');
    const endpoint = moveToList ? 'move-to-list' : 'remove';
    this.backend.post(`/api/user/profile/watched/${endpoint}`, { movie_id: item.movie_id }, {
      headers: { 'X-G15-Request': '1' },
    }).pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.removingWatched.set(false))).subscribe({
      next: () => {
        if (this.selectedMovie()?.movie_id === item.movie_id) dialog.close();
        this.loadHistory(this.offset());
        this.watchlist.load();
      },
      error: error => {
        if (this.selectedMovie()?.movie_id === item.movie_id) this.movieError.set(authError(error));
        else this.historyError.set(authError(error));
      },
    });
  }

  closeMovie(): void {
    this.selectedMovie.set(null);
    if (this.movieTrigger?.isConnected) this.movieTrigger.focus();
    else document.getElementById('history-title')?.focus();
    this.movieTrigger = null;
  }

  openPicker(dialog: HTMLDialogElement): void {
    this.choosing.set(true);
    dialog.showModal();
    dialog.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus();
  }

  trapPickerFocus(event: KeyboardEvent, dialog: HTMLDialogElement): void {
    if (event.key !== 'Tab') return;
    const buttons = Array.from(dialog.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
    if (!buttons.length) return;
    const current = buttons.indexOf(dialog.ownerDocument.activeElement as HTMLButtonElement);
    const next = (current + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length;
    event.preventDefault();
    buttons[next].focus();
  }

  pickerClosed(trigger: HTMLButtonElement): void {
    this.choosing.set(false);
    trigger.focus();
  }

  dismissBackdrop(event: MouseEvent, dialog: HTMLDialogElement): void {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  }

  chooseAvatar(id: number, dialog: HTMLDialogElement): void {
    if (this.saving()) return;
    this.saving.set(true); this.profileError.set('');
    this.backend.post<{ profile: Profile }>('/api/user/profile/avatar', { avatar_id: id }, {
      headers: { 'X-G15-Request': '1' },
    }).pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.saving.set(false))).subscribe({
      next: result => {
        this.profile.set(result.profile);
        this.auth.user.update(user => user ? { ...user, avatar_id: result.profile.avatar_id } : user);
        dialog.close();
      },
      error: error => this.profileError.set(authError(error)),
    });
  }

  searchHistory(value: string): void {
    this.search.set(value);
    this.offset.set(0);
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.loadHistory(0, true), 250);
  }

  loadHistory(offset: number, background = false): void {
    if (this.historyPending) { this.historyQueued = true; this.queuedOffset = offset; this.queuedBackground = background; return; }
    const query = this.search().trim();
    const suffix = `&q=${encodeURIComponent(query)}`;
    this.historyPending = true;
    if (!background) this.loading.set(true);
    this.backend.get<History>(`/api/user/profile/watched?offset=${offset}${suffix}`).pipe(
      switchMap(history => history.offset > 0 && history.items.length === 0
        ? this.backend.get<History>(`/api/user/profile/watched?offset=0${suffix}`) : of(history)),
      switchMap(history => forkJoin({
        history: of(history),
        movies: history.items.length ? this.backend.get<{ movies: Movie[] }>(
          `/api/movie/movies?ids=${history.items.map(item => item.movie_id).join(',')}`,
        ).pipe(map(result => result.movies), catchError(() => of(null))) : of([] as Movie[]),
      })),
      takeUntilDestroyed(this.destroyRef), finalize(() => {
        this.historyPending = false;
        this.loading.set(false);
        if (this.historyQueued && !this.destroyRef.destroyed) {
          this.historyQueued = false;
          this.loadHistory(this.queuedOffset, this.queuedBackground);
        }
      }),
    ).subscribe({
      next: ({ history, movies }) => {
        if (query !== this.search().trim()) return;
        this.matchedTotal.set(history.matched_total ?? history.total);
        this.historyError.set('');
        this.moviesUnavailable.set(movies === null);
        const byId = new Map((movies ?? []).map(movie => [movie.id, movie]));
        this.items.set(history.items.map(item => ({ ...item, movie: byId.get(item.movie_id) })));
        this.watchMinutes.set(history.watch_minutes);
        this.total.set(history.total); this.offset.set(history.offset);
      },
      error: error => this.historyError.set(authError(error)),
    });
  }

  posterFailed(id: string): void { this.failedPosters.update(ids => new Set([...ids, id])); }
}
