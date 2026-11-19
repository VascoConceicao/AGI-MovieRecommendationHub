import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, ElementRef, inject, signal, viewChild, viewChildren, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, exhaustMap, finalize, map, Observable, of, Subject, Subscription, switchMap, tap, timer } from 'rxjs';
import { BackendService } from '../../../../shared/services/backend/backend.service';
import { authError } from '../../../../shared/services/backend/auth/auth.service';

import { FilterSelect } from '../../../common/filter-select/filter-select';

type Choice = 'genres' | 'languages' | 'actors' | 'directors';
interface FilterOptions {
  choices: Record<Choice, string[]>;
  durations: { id: string; label: string }[];
  year_min: number; year_max: number; counts: number[]; max_selections: number;
}

interface RecommendedMovie { id: string; title: string; synopsis: string | null; poster_url: string | null; duration_minutes: number | null; genres: string[] | null; }
interface Recommendation { id: string; movie_id: string; source: 'auto' | 'user_requested'; reason: string; score?: number | null; movie?: RecommendedMovie; }
interface RecommendationPage { items: Recommendation[]; total: number; offset: number; }

type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';
type GenerationState = 'idle' | 'starting' | JobStatus | 'stalled';
interface GenerationJob {
  job_id: string; status: JobStatus; recommendation_count?: number | null; outcome?: string | null;
  used_fallback?: boolean | null; error?: string | null;
}

// Real Qwen inference can take 60-120 s (plus waiting for the single inference slot), so poll patiently but not forever.
export const POLL_INTERVAL_MS = 3000;
export const POLL_TIMEOUT_MS = 6 * 60 * 1000;
export const MAX_POLL_FAILURES = 5;
const ACTIVE: GenerationState[] = ['starting', 'queued', 'running'];
const FAILURE_MESSAGES: Record<string, string> = {
  invalid_request: 'Those filters could not be used. Please adjust them and try again.',
  user_not_found: 'Your account could not be found. Please sign in again.',
  interrupted: 'The generation was interrupted. Your saved recommendations are shown below; please try again.',
};
const FAILURE_FALLBACK = 'We could not generate recommendations right now. Please try again in a few minutes.';

@Component({
  selector: 'app-profile-recommendations',
  imports: [FilterSelect, NgTemplateOutlet],
  templateUrl: './recommendations.html',
  styleUrl: './recommendations.scss',
})
export class ProfileRecommendations implements OnInit {
  private readonly selectors = viewChildren(FilterSelect);
  readonly trigger = viewChild<ElementRef<HTMLButtonElement>>('trigger');
  private readonly backend = inject(BackendService);
  private readonly destroyRef = inject(DestroyRef);
  readonly fields: { key: Choice; label: string }[] = [
    { key: 'genres', label: 'Genres' }, { key: 'languages', label: 'Languages' },
    { key: 'actors', label: 'Actors' }, { key: 'directors', label: 'Directors' },
  ];
  readonly options = signal<FilterOptions | null>(null);
  readonly selected = signal<Record<Choice, string[]>>({ genres: [], languages: [], actors: [], directors: [] });
  readonly duration = signal('any');
  readonly count = signal('10');
  private readonly languageNames = new Intl.DisplayNames(['en'], { type: 'language' });
  readonly choiceOptions = computed(() => {
    const choices = this.options()?.choices;
    return {
      genres: (choices?.genres ?? []).map(value => ({ value, label: value })),
      languages: (choices?.languages ?? []).map(value => ({ value, label: this.languageName(value) })).sort((a, b) => a.label.localeCompare(b.label)),
      actors: [], directors: [],
    };
  });
  readonly durationOptions = computed(() => (this.options()?.durations ?? []).map(item => ({ value: item.id, label: item.label })));
  readonly countOptions = computed(() => (this.options()?.counts ?? []).map(value => ({ value: String(value), label: String(value) })));

  languageName(code: string): string {
    if (code === 'xx') return 'No dialogue';
    try { const name = this.languageNames.of(code === 'cn' ? 'yue' : code); return name && name !== code ? name : 'Unknown language'; }
    catch { return 'Unknown language'; }
  }

  select(key: Choice, values: string[]): void { this.selected.update(current => ({ ...current, [key]: values })); }

  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal('');
  // Two lists, never mixed: "Recommended for You" (source auto, from the background agent) and the user's own
  // "My Recommendations" (source user_requested). The selected tab is the source that is listed and searched.
  readonly views = [
    { id: 'auto', label: 'Recommended for You', lede: "Automatically personalized for you by our background agent. You don't need to ask.",
      empty: 'Your personalized recommendations are being prepared. Check back soon!' },
    { id: 'user_requested', label: 'My Recommendations', lede: 'Ask for new picks with your own filters. Results are saved here.',
      empty: 'No recommendations yet. Use "Generate recommendations" to create some.' },
  ] as const;
  readonly source = signal<'auto' | 'user_requested'>('auto');
  readonly currentView = computed(() => this.views[this.source() === 'auto' ? 0 : 1]);
  readonly search = signal('');
  readonly hasSearchItems = signal(false);
  private searchTimer?: ReturnType<typeof setTimeout>;
  readonly results = signal<Recommendation[]>([]);
  readonly total = signal(0);
  readonly offset = signal(0);
  readonly listError = signal('');
  readonly generation = signal<GenerationState>('idle');
  readonly generationMessage = signal('');
  readonly generating = computed(() => ACTIVE.includes(this.generation()));
  private pollSubscription?: Subscription;
  readonly listLoading = signal(false);
  readonly details = signal<Recommendation | null>(null);
  readonly failedPosters = signal<Set<string>>(new Set());

  posterFailed(id: string): void { this.failedPosters.update(ids => new Set([...ids, id])); }
  readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / 25)));
  readonly page = computed(() => Math.floor(this.offset() / 25) + 1);
  private readonly loads = new Subject<{ source: string; offset: number; query: string }>();

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => clearTimeout(this.searchTimer));
    this.loads.pipe(switchMap(({ source, offset, query }) => {
      this.listError.set(''); this.listLoading.set(true); this.results.set([]);
      const url = `/api/user/profile/recommendations?source=${source}&offset=${offset}${query ? '&q=' + encodeURIComponent(query) : ''}`;
      const request = query ? this.backend.get<RecommendationPage>(url, { timeoutMs: 15000 }) : this.backend.get<RecommendationPage>(url);
      return request.pipe(
        tap(page => { if (!query) this.hasSearchItems.set(page.total > 0); }),
        switchMap(page => this.withMovies(page)),
        catchError(error => { this.listError.set(authError(error)); return of(null); }),
        finalize(() => this.listLoading.set(false)),
      );
    }), takeUntilDestroyed(this.destroyRef)).subscribe(page => {
      if (page) { this.results.set(page.items); this.total.set(page.total); this.offset.set(page.offset); }
    });
    this.loadResults();
  }

  private withMovies(page: RecommendationPage): Observable<RecommendationPage> {
    return page.items.length ? this.backend.get<{ movies: RecommendedMovie[] }>(
      '/api/movie/movies?ids=' + [...new Set(page.items.map(item => item.movie_id))].join(','),
    ).pipe(map(data => ({ ...page, items: page.items.map(item => ({ ...item, movie: data.movies.find(movie => movie.id === item.movie_id) })) }))) : of(page);
  }

  loadResults(offset = 0): void { clearTimeout(this.searchTimer); this.loads.next({ source: this.source(), offset, query: this.search().trim() }); }
  searchMovies(value: string): void {
    this.search.set(value); clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.loadResults(), 250);
  }
  selectView(source: 'auto' | 'user_requested'): void {
    if (source === this.source()) return;
    clearTimeout(this.searchTimer);
    this.source.set(source); this.search.set(''); this.hasSearchItems.set(false);
    this.results.set([]); this.total.set(0); this.offset.set(0); this.listError.set('');
    this.loadResults();
  }
  navigateView(event: KeyboardEvent, index: number): void {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index;
    this.selectView(this.views[next].id);
    document.getElementById('recommendations-tab-' + this.views[next].id)?.focus();
  }
  showDetails(item: Recommendation, dialog: HTMLDialogElement): void { this.details.set(item); dialog.showModal(); }
  sourceLabel(value: string): string { return value === 'auto' ? 'Auto generated' : 'User requested'; }


  open(dialog: HTMLDialogElement): void {
    this.error.set('');
    dialog.showModal();
    if (!this.options()) this.loadOptions();
  }

  loadOptions(): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.error.set('');
    this.backend.get<FilterOptions>('/api/user/profile/recommendation-filters').pipe(
      takeUntilDestroyed(this.destroyRef), finalize(() => this.loading.set(false)),
    ).subscribe({ next: options => this.options.set(options), error: error => this.error.set(authError(error)) });
  }

  submit(event: Event, form: HTMLFormElement, dialog: HTMLDialogElement): void {
    event.preventDefault();
    if (this.saving() || this.generating() || !this.options() || !form.reportValidity()) return;
    this.selectors().forEach(selector => selector.commit());
    const data = new FormData(form);
    const year = (key: string) => data.get(key) ? Number(data.get(key)) : null;
    const from = year('year_from'), to = year('year_to');
    if (from !== null && to !== null && from > to) { this.error.set('Release year range is reversed.'); return; }
    this.saving.set(true); this.error.set('');
    this.setGeneration('starting');
    this.backend.post<{ job_id: string; status: JobStatus }>('/api/user/profile/recommendation-generations', {
      filters: { ...this.selected(), year_from: from, year_to: to, duration: this.duration(), count: Number(this.count()) },
    }, { headers: { 'X-G15-Request': '1' }, timeoutMs: 15000 }).pipe(
      takeUntilDestroyed(this.destroyRef), finalize(() => this.saving.set(false)),
    ).subscribe({
      next: job => { dialog.close(); this.follow(job.job_id, job.status); },
      error: error => this.startFailed(error, dialog),
    });
  }

  private startFailed(error: unknown, dialog: HTMLDialogElement): void {
    const active = error instanceof HttpErrorResponse && error.status === 409 ? error.error : null;
    if (active && typeof active.job_id === 'string') {
      // A generation is already queued or running for this user: follow it instead of starting another one.
      dialog.close();
      this.follow(active.job_id, active.status === 'running' ? 'running' : 'queued', true);
      return;
    }
    this.setGeneration('idle');
    const wait = error instanceof HttpErrorResponse && error.status === 503 ? Number(error.headers?.get('Retry-After')) : NaN;
    this.error.set(authError(error) + (wait > 0 ? ` Please try again in about ${wait} seconds.` : ''));
  }

  private follow(jobId: string, status: JobStatus, resumed = false): void {
    this.pollSubscription?.unsubscribe();
    this.setGeneration(status, resumed ? 'You already have a generation in progress, so we are following it. ' : '');
    const url = `/api/user/profile/recommendation-generations/${encodeURIComponent(jobId)}`;
    const startedAt = Date.now();
    let failures = 0;
    this.pollSubscription = timer(0, POLL_INTERVAL_MS).pipe(
      exhaustMap(() => this.backend.get<GenerationJob>(url).pipe(map(job => ({ job })), catchError((error: unknown) => of({ error })))),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(result => {
      const job = 'job' in result ? result.job : null;
      if (job && ['queued', 'running', 'succeeded', 'failed'].includes(job.status)) { failures = 0; this.apply(job); }
      else {
        const gone = 'error' in result && result.error instanceof HttpErrorResponse && result.error.status === 404;
        if (gone || ++failures >= MAX_POLL_FAILURES) { this.stalled('We lost track of this request. Your saved recommendations are shown below.'); return; }
      }
      if (this.generating() && Date.now() - startedAt > POLL_TIMEOUT_MS) this.timedOut();     // never poll forever
    });
  }

  private apply(job: GenerationJob): void {
    if (job.status === 'queued' || job.status === 'running') { this.setGeneration(job.status); return; }
    this.pollSubscription?.unsubscribe();
    this.setGeneration(job.status, '', job);
    // Reload the visible list for success and for failure alike: an interrupted job may still have committed a new set.
    this.loadResults();
  }

  private stalled(message: string): void {
    this.pollSubscription?.unsubscribe();
    this.generation.set('stalled'); this.generationMessage.set(message);
    this.loadResults();
  }

  private timedOut(): void {
    this.stalled('This is taking longer than expected. It keeps running in the background; your recommendations will be saved when ready, so check back soon.');
  }

  private setGeneration(state: GenerationState, prefix = '', job?: GenerationJob): void {
    this.generation.set(state);
    this.generationMessage.set(prefix + this.describe(state, job));
  }

  private describe(state: GenerationState, job?: GenerationJob): string {
    switch (state) {
      case 'starting': return 'Starting your request…';
      case 'queued': return 'Your request is waiting its turn. Our AI model handles one request at a time.';
      case 'running': return 'Our AI model is choosing recommendations for you. This usually takes a minute or two.';
      case 'succeeded':
        if (!job?.recommendation_count) return 'No movies match these filters. Try widening them.';
        return `Your recommendations are ready (${job.recommendation_count}).` +
          (job.used_fallback ? ' Our AI model was unavailable, so we ranked them with our standard personalization.' : '');
      case 'failed': return (job?.error && FAILURE_MESSAGES[job.error]) || FAILURE_FALLBACK;
      default: return '';
    }
  }

  backdrop(event: MouseEvent, dialog: HTMLDialogElement): void {
    const bounds = dialog.getBoundingClientRect();
    if (!this.saving() && event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  }

  restoreFocus(): void { this.trigger()?.nativeElement.focus(); }

  cancel(event: Event): void {
    if (this.saving()) event.preventDefault();
  }
}
