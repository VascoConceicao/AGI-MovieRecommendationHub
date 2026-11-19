import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { Observable, of, Subject, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BackendService } from '../../../../shared/services/backend/backend.service';
import { FilterSelect } from '../../../common/filter-select/filter-select';
import { MAX_POLL_FAILURES, POLL_INTERVAL_MS, POLL_TIMEOUT_MS, ProfileRecommendations } from './recommendations';

const options = { choices: { genres: ['Drama'], languages: ['pt', 'en'], actors: [], directors: [] },
  durations: [{ id: 'any', label: 'Any' }], year_min: 1888, year_max: 2030, counts: [5, 10], max_selections: 10 };
const item = { id: 'r1', movie_id: 'm1', source: 'auto' as const, reason: 'Because' };
const movie = { id: 'm1', title: 'Movie', synopsis: 'Plot', poster_url: null, duration_minutes: 90, genres: ['Drama'] };
const emptyPage = { items: [], total: 0, offset: 0 };
const JOBS = '/api/user/profile/recommendation-generations';
const AUTO_URL = '/api/user/profile/recommendations?source=auto&offset=0';
const OWN_URL = '/api/user/profile/recommendations?source=user_requested&offset=0';

function setup(get: (url: string) => Observable<any> = () => of(emptyPage)) {
  const backend = { get: vi.fn(get), post: vi.fn((): Observable<any> => of({})) };
  TestBed.overrideComponent(ProfileRecommendations, {
    add: { providers: [{ provide: BackendService, useValue: backend }] },
  });
  const fixture = TestBed.createComponent(ProfileRecommendations); fixture.detectChanges();
  const dialog = document.createElement('dialog'); dialog.showModal = vi.fn(); dialog.close = vi.fn();
  return { fixture, page: fixture.componentInstance, backend, dialog };
}

/** Opens a ready-to-submit form: options loaded and rendered. */
function ready() {
  const context = setup();
  context.page.selectView('user_requested');                                    // generation lives in "My Recommendations"
  context.page.options.set(options); context.fixture.detectChanges();
  const form = context.fixture.nativeElement.querySelector('form') as HTMLFormElement;
  vi.spyOn(form, 'reportValidity').mockReturnValue(true);
  const submit = () => context.page.submit(new Event('submit'), form, context.dialog);
  return { ...context, form, submit };
}

const job = (status: string, extra: object = {}) => ({ job_id: 'job-1', status, ...extra });
const jobCalls = (backend: { get: ReturnType<typeof vi.fn> }) => backend.get.mock.calls.filter(([url]) => String(url).startsWith(JOBS + '/'));
const text = (fixture: { nativeElement: HTMLElement }, selector: string) => fixture.nativeElement.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
const http = (status: number, error: unknown, headers: Record<string, string> = {}) =>
  throwError(() => new HttpErrorResponse({ status, error, headers: new HttpHeaders(headers) }));

/** Serves job polls from a scripted sequence (the last entry repeats); everything else is an empty page. */
function polling(backend: ReturnType<typeof setup>['backend'], sequence: Observable<any>[]) {
  let polls = 0;
  backend.get.mockImplementation((url: string) => String(url).startsWith(JOBS + '/') ? sequence[Math.min(polls++, sequence.length - 1)] : of(emptyPage));
}

describe('ProfileRecommendations', () => {
  it('loads joined results and switches between the two lists', () => {
    const { page, backend, dialog } = setup();
    expect(page.pages()).toBe(1); expect(page.page()).toBe(1);
    expect(page.source()).toBe('auto');
    backend.get.mockImplementation(url => of(url.startsWith('/api/movie') ? { movies: [{ ...movie, id: 'other' }, movie] } :
      { items: [item, { ...item, id: 'r2', movie_id: 'missing' }], total: 60, offset: 25 }));
    page.loadResults(25);
    expect(page.results()[0].movie).toEqual(movie);
    expect(page.results()[1].movie).toBeUndefined();
    expect(page.pages()).toBe(3); expect(page.page()).toBe(2);
    page.showDetails(page.results()[0], dialog);
    expect(page.details()?.id).toBe('r1'); expect(dialog.showModal).toHaveBeenCalledOnce();
    page.posterFailed('m1'); expect(page.failedPosters().has('m1')).toBe(true);
    expect(page.sourceLabel('auto')).toBe('Auto generated');
    expect(page.sourceLabel('user_requested')).toBe('User requested');
    backend.get.mockReturnValue(of(emptyPage));
    page.selectView('user_requested');
    expect(page.source()).toBe('user_requested'); expect(page.results()).toEqual([]);
    expect(backend.get).toHaveBeenLastCalledWith(OWN_URL);
    backend.get.mockReturnValue(throwError(() => new Error('offline'))); page.loadResults();
    expect(page.listError()).not.toBe(''); expect(page.listLoading()).toBe(false);
  });
  it('loads options once and reports errors', () => {
    const { page, backend, dialog } = setup();
    expect(page.choiceOptions()).toEqual({ genres: [], languages: [], actors: [], directors: [] });
    expect(page.durationOptions()).toEqual([]); expect(page.countOptions()).toEqual([]);
    const pending = new Subject<any>(); backend.get.mockReturnValue(pending);
    page.open(dialog); page.loadOptions(); expect(page.loading()).toBe(true);
    expect(backend.get.mock.calls.filter(([url]) => url.includes('filters'))).toHaveLength(1);
    pending.next(options); pending.complete();
    expect(page.choiceOptions().genres).toEqual([{ value: 'Drama', label: 'Drama' }]);
    expect(page.choiceOptions().languages.map(x => x.label)).toEqual(['English', 'Portuguese']);
    expect(page.durationOptions()).toEqual([{ value: 'any', label: 'Any' }]);
    expect(page.countOptions()).toEqual([{ value: '5', label: '5' }, { value: '10', label: '10' }]);
    page.open(dialog); expect(backend.get.mock.calls.filter(([url]) => url.includes('filters'))).toHaveLength(1);
    backend.get.mockReturnValue(throwError(() => new Error('offline'))); page.loadOptions();
    expect(page.error()).not.toBe(''); expect(page.loading()).toBe(false);
    expect(page.languageName('xx')).toBe('No dialogue');
    expect(page.languageName('cn')).toContain('Cantonese');
    expect(page.languageName('zz')).toBe('Unknown language');
    expect(page.languageName('!')).toBe('Unknown language');
    vi.spyOn(Intl.DisplayNames.prototype, 'of').mockReturnValueOnce(undefined);
    expect(page.languageName('en')).toBe('Unknown language');
  });
  it('protects pending submissions from dialog dismissal', () => {
    const { page, dialog } = setup();
    dialog.getBoundingClientRect = () => ({ left: 10, right: 30, top: 10, bottom: 30 } as DOMRect);
    for (const [x, y, target] of [[20, 20, dialog], [0, 0, document.body], [0, 20, dialog], [40, 20, dialog], [20, 0, dialog], [20, 40, dialog]] as const) {
      page.backdrop({ clientX: x, clientY: y, target } as unknown as MouseEvent, dialog);
    }
    expect(dialog.close).toHaveBeenCalledTimes(4);
    const event = new Event('cancel', { cancelable: true }); page.cancel(event); expect(event.defaultPrevented).toBe(false);
    page.saving.set(true); page.cancel(event); expect(event.defaultPrevented).toBe(true);
    page.backdrop({ target: dialog, clientX: 0, clientY: 0 } as unknown as MouseEvent, dialog);
    expect(dialog.close).toHaveBeenCalledTimes(4);
  });
});

describe('real generation (submit -> poll -> reload)', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('validates the form and sends the selected structured filters to the generation endpoint', () => {
    const { page, fixture, backend, dialog, form, submit } = ready();
    const validity = vi.spyOn(form, 'reportValidity').mockReturnValue(false);
    submit(); expect(backend.post).not.toHaveBeenCalled();
    validity.mockReturnValue(true);
    const from = form.elements.namedItem('year_from') as HTMLInputElement;
    const to = form.elements.namedItem('year_to') as HTMLInputElement;
    from.value = '2020'; to.value = '2000';
    submit(); expect(page.error()).toContain('reversed'); expect(backend.post).not.toHaveBeenCalled();
    from.value = '1990'; to.value = '';
    page.select('genres', ['Drama']); page.duration.set('any'); page.count.set('5');
    (fixture.debugElement.queryAll(By.directive(FilterSelect))[2].componentInstance as FilterSelect).edit(' Actor ');
    backend.post.mockReturnValue(of(job('queued')));
    submit();
    expect(backend.post).toHaveBeenCalledOnce();
    expect(backend.post).toHaveBeenCalledWith(JOBS, { filters: {
      genres: ['Drama'], languages: [], actors: ['Actor'], directors: [], year_from: 1990, year_to: null, duration: 'any', count: 5,
    } }, { headers: { 'X-G15-Request': '1' }, timeoutMs: 15000 });
    expect(dialog.close).toHaveBeenCalledOnce();
  });

  it('does nothing until the filter options have loaded', () => {
    const { page, backend, dialog } = setup();
    page.submit(new Event('submit'), document.createElement('form'), dialog);
    expect(backend.post).not.toHaveBeenCalled(); expect(page.generation()).toBe('idle');
  });

  it('shows the queued and running states while polling, then reloads the saved list on success', () => {
    const { page, fixture, backend, submit } = ready();
    polling(backend, [of(job('queued')), of(job('running')), of(job('running')), of(job('succeeded', { recommendation_count: 10, outcome: 'llm', used_fallback: false }))]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); fixture.detectChanges();
    expect(page.generating()).toBe(true); expect(page.saving()).toBe(false);
    expect(text(fixture, '.generate-button')).toBe('Generating…');
    expect(fixture.nativeElement.querySelector('.generate-button').disabled).toBe(true);
    expect(text(fixture, '.generation-status')).toContain('waiting its turn');
    const listLoads = () => backend.get.mock.calls.filter(([url]) => url === OWN_URL).length;
    const before = listLoads();
    vi.advanceTimersByTime(0); fixture.detectChanges();
    expect(jobCalls(backend)[0][0]).toBe(`${JOBS}/job-1`);
    vi.advanceTimersByTime(POLL_INTERVAL_MS); fixture.detectChanges();
    expect(page.generation()).toBe('running');
    expect(text(fixture, '.generation-status')).toContain('choosing recommendations');
    expect(fixture.nativeElement.querySelector('.spinner')).not.toBeNull();
    expect(listLoads()).toBe(before);                                           // nothing is reloaded while it is still running
    vi.advanceTimersByTime(2 * POLL_INTERVAL_MS); fixture.detectChanges();
    expect(page.generation()).toBe('succeeded'); expect(page.generating()).toBe(false);
    expect(text(fixture, '.generation-status')).toContain('Your recommendations are ready (10).');
    expect(fixture.nativeElement.querySelector('.spinner')).toBeNull();
    expect(listLoads()).toBe(before + 1);                                       // reloaded through the existing listing endpoint
    expect(fixture.nativeElement.querySelector('.generate-button').disabled).toBe(false);
    const calls = jobCalls(backend).length;
    vi.advanceTimersByTime(10 * POLL_INTERVAL_MS);
    expect(jobCalls(backend)).toHaveLength(calls);                              // polling stopped at the terminal state
  });

  it('treats the deterministic fallback as a successful generation', () => {
    const { page, fixture, backend, submit } = ready();
    polling(backend, [of(job('succeeded', { recommendation_count: 10, outcome: 'fallback_inference_error', used_fallback: true }))]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); vi.advanceTimersByTime(0); fixture.detectChanges();
    expect(page.generation()).toBe('succeeded');
    expect(text(fixture, '.generation-status')).toContain('Your recommendations are ready (10).');
    expect(text(fixture, '.generation-status')).toContain('standard personalization');
    expect(fixture.nativeElement.querySelector('.generation-status').dataset.state).toBe('succeeded');
  });

  it('shows an empty state, not an error, when no movie matches the filters', () => {
    const { page, fixture, backend, submit } = ready();
    polling(backend, [of(job('succeeded', { recommendation_count: 0, outcome: 'no_candidates', used_fallback: false }))]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); vi.advanceTimersByTime(0); fixture.detectChanges();
    expect(page.generation()).toBe('succeeded');
    expect(text(fixture, '.generation-status')).toBe('No movies match these filters. Try widening them.');
    expect(fixture.nativeElement.querySelector('.generation-status').dataset.state).toBe('succeeded');
  });

  it.each([['invalid_request', 'could not be used'], ['interrupted', 'interrupted'], ['user_not_found', 'could not be found'],
    ['movie_catalog_unavailable', 'try again in a few minutes'], ['internal_error', 'try again in a few minutes'], [null, 'try again in a few minutes']])(
    'shows a friendly message for a failed job (%s) and still reloads the saved list', (category, expected) => {
      const { page, fixture, backend, submit } = ready();
      polling(backend, [of(job('failed', { error: category }))]);
      backend.post.mockReturnValue(of(job('queued')));
      const before = backend.get.mock.calls.filter(([url]) => url === OWN_URL).length;
      submit(); vi.advanceTimersByTime(0); fixture.detectChanges();
      expect(page.generation()).toBe('failed'); expect(page.generating()).toBe(false);
      expect(text(fixture, '.generation-status')).toContain(expected);
      expect(text(fixture, '.generation-status')).not.toContain(String(category ?? 'null') === 'internal_error' ? 'internal_error' : '\u0000');
      expect(backend.get.mock.calls.filter(([url]) => url === OWN_URL).length).toBe(before + 1);     // an interrupted job may have saved a new set
    });

  it('reloads whichever list is showing when a generation finishes', () => {
    const { page, backend, submit } = ready();
    polling(backend, [of(job('succeeded', { recommendation_count: 5 }))]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); page.selectView('auto');                                           // the user wandered to the other tab while it ran
    vi.advanceTimersByTime(0);
    expect(page.source()).toBe('auto');
    expect(backend.get).toHaveBeenLastCalledWith(AUTO_URL);
  });

  it('follows the active job instead of starting another one on a 409 conflict', () => {
    const { page, fixture, backend, dialog, submit } = ready();
    polling(backend, [of(job('running')), of(job('succeeded', { recommendation_count: 10 }))]);
    backend.post.mockReturnValue(http(409, { error: 'A generation is already queued or running for this user.', job_id: 'active-7', status: 'running' }));
    submit(); fixture.detectChanges();
    expect(dialog.close).toHaveBeenCalledOnce();
    expect(page.error()).toBe('');
    expect(text(fixture, '.generation-status')).toContain('already have a generation in progress');
    vi.advanceTimersByTime(0); fixture.detectChanges();
    expect(jobCalls(backend)[0][0]).toBe(`${JOBS}/active-7`);
    expect(page.generation()).toBe('running'); expect(backend.post).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    expect(page.generation()).toBe('succeeded');
  });

  it('follows a conflicting job that is still waiting in the queue', () => {
    const { page, fixture, backend, submit } = ready();
    polling(backend, [of(job('queued'))]);
    backend.post.mockReturnValue(http(409, { error: 'A generation is already queued or running for this user.', job_id: 'waiting-3', status: 'queued' }));
    submit(); vi.advanceTimersByTime(0); fixture.detectChanges();
    expect(page.generation()).toBe('queued'); expect(jobCalls(backend)[0][0]).toBe(`${JOBS}/waiting-3`);
    expect(text(fixture, '.generation-status')).toContain('waiting its turn');
  });

  it('asks the user to retry later when the queue is full, honouring Retry-After', () => {
    const { page, fixture, backend, dialog, submit } = ready();
    backend.post.mockReturnValue(http(503, { error: 'Generation queue is full. Please retry later.' }, { 'Retry-After': '30' }));
    submit(); fixture.detectChanges();
    expect(page.generation()).toBe('idle'); expect(page.generating()).toBe(false); expect(page.saving()).toBe(false);
    expect(page.error()).toBe('Generation queue is full. Please retry later. Please try again in about 30 seconds.');
    expect(dialog.close).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('dialog[aria-labelledby=recommendation-filters-title] .error')?.textContent).toContain('queue is full');
    expect(jobCalls(backend)).toHaveLength(0);
    backend.post.mockReturnValue(http(503, { error: 'Recommendations unavailable. Please retry.' }));
    submit(); expect(page.error()).toBe('Recommendations unavailable. Please retry.');
  });

  it('shows validation and network errors in the dialog and lets the user retry', () => {
    const { page, backend, submit } = ready();
    backend.post.mockReturnValue(http(400, { error: 'Select an available duration.' }));
    submit(); expect(page.error()).toBe('Select an available duration.'); expect(page.generation()).toBe('idle');
    backend.post.mockReturnValue(throwError(() => new Error('offline')));
    submit(); expect(page.error()).not.toBe(''); expect(page.saving()).toBe(false); expect(page.generating()).toBe(false);
  });

  it('ignores repeated submissions while a request is starting or a generation is active', () => {
    const { page, backend, submit } = ready();
    const pending = new Subject<any>(); backend.post.mockReturnValue(pending);
    submit(); submit(); expect(backend.post).toHaveBeenCalledOnce();
    polling(backend, [of(job('running'))]);
    pending.next(job('queued')); pending.complete(); vi.advanceTimersByTime(0);
    submit(); submit(); expect(backend.post).toHaveBeenCalledOnce();
    expect(page.generating()).toBe(true);
  });

  it('never has two job polls in flight at once', () => {
    const { backend, submit } = ready();
    const slow = new Subject<any>();
    polling(backend, [slow]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); vi.advanceTimersByTime(5 * POLL_INTERVAL_MS);
    expect(jobCalls(backend)).toHaveLength(1);
    slow.next(job('running')); slow.complete(); vi.advanceTimersByTime(POLL_INTERVAL_MS);
    expect(jobCalls(backend).length).toBeGreaterThan(1);
  });

  it('stops polling when the component is destroyed', () => {
    const { fixture, backend, submit } = ready();
    polling(backend, [of(job('running'))]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); vi.advanceTimersByTime(2 * POLL_INTERVAL_MS);
    const calls = backend.get.mock.calls.length; expect(jobCalls(backend).length).toBeGreaterThan(1);
    fixture.destroy(); vi.advanceTimersByTime(20 * POLL_INTERVAL_MS);
    expect(backend.get.mock.calls).toHaveLength(calls);
  });

  it('does not poll forever: it stops after the overall timeout and says the job keeps running', () => {
    const { page, fixture, backend, submit } = ready();
    polling(backend, [of(job('running'))]);
    backend.post.mockReturnValue(of(job('queued')));
    submit(); vi.advanceTimersByTime(POLL_TIMEOUT_MS + 2 * POLL_INTERVAL_MS); fixture.detectChanges();
    expect(page.generation()).toBe('stalled'); expect(page.generating()).toBe(false);
    expect(text(fixture, '.generation-status')).toContain('taking longer than expected');
    const calls = jobCalls(backend).length;
    vi.advanceTimersByTime(10 * POLL_INTERVAL_MS); expect(jobCalls(backend)).toHaveLength(calls);
  });

  it('tolerates transient poll errors but gives up after repeated failures or a 404', () => {
    const { page, backend, submit } = ready();
    backend.post.mockReturnValue(of(job('queued')));
    polling(backend, [throwError(() => new Error('blip')), throwError(() => new Error('blip')), of(job('succeeded', { recommendation_count: 3 }))]);
    submit(); vi.advanceTimersByTime(3 * POLL_INTERVAL_MS);
    expect(page.generation()).toBe('succeeded');
    polling(backend, [throwError(() => new Error('down'))]);
    submit(); vi.advanceTimersByTime((MAX_POLL_FAILURES + 1) * POLL_INTERVAL_MS);
    expect(page.generation()).toBe('stalled');
    polling(backend, [http(404, { error: 'Generation job not found.' })]);
    submit(); vi.advanceTimersByTime(POLL_INTERVAL_MS);
    expect(page.generation()).toBe('stalled'); expect(jobCalls(backend).length).toBeGreaterThan(0);
    polling(backend, [of({ unexpected: true })]);                                // an unrecognised payload counts as a failed poll
    submit(); vi.advanceTimersByTime((MAX_POLL_FAILURES + 1) * POLL_INTERVAL_MS);
    expect(page.generation()).toBe('stalled');
  });
});

describe('two recommendation tabs', () => {
  const autoItem = { id: 'a1', movie_id: 'm1', source: 'auto' as const, reason: 'Matches your interest in Drama.', score: 1 };
  const ownItem = { id: 'u1', movie_id: 'm1', source: 'user_requested' as const, reason: 'Requested one.', score: 0.9 };
  const serve = (autoItems: unknown[], ownItems: unknown[] = []) => (url: string): Observable<any> => url.startsWith('/api/movie') ? of({ movies: [movie] }) :
    url.startsWith(AUTO_URL.split('?')[0] + '?source=auto') ? of({ items: autoItems, total: autoItems.length, offset: 0 }) :
    url.includes('source=user_requested') ? of({ items: ownItems, total: ownItems.length, offset: 0 }) : of(emptyPage);
  const tabs = (fixture: { nativeElement: HTMLElement }) => Array.from(fixture.nativeElement.querySelectorAll('[role=tab]')) as HTMLButtonElement[];

  it('offers exactly two tabs and no All / Auto generated / User requested filter', () => {
    const { fixture, page } = setup();
    expect(tabs(fixture).map(tab => tab.textContent?.trim())).toEqual(['Recommended for You', 'My Recommendations']);
    expect(tabs(fixture).map(tab => tab.getAttribute('aria-selected'))).toEqual(['true', 'false']);
    expect(tabs(fixture).map(tab => tab.tabIndex)).toEqual([0, -1]);
    expect(fixture.nativeElement.querySelector('.source-filter')).toBeNull();
    expect(fixture.nativeElement.querySelector('[role=tabpanel]').getAttribute('aria-labelledby')).toBe('recommendations-tab-auto');
    expect(page.source()).toBe('auto');
  });

  it('opens on "Recommended for You" and loads only the automatic set, without any generation or click', () => {
    const { fixture, backend, page } = setup(serve([autoItem]));
    expect(backend.get).toHaveBeenCalledWith(AUTO_URL);
    expect(backend.get).not.toHaveBeenCalledWith(OWN_URL);
    expect(backend.post).not.toHaveBeenCalled(); expect(jobCalls(backend)).toHaveLength(0);
    expect(page.results()[0].movie).toEqual(movie);
    expect(text(fixture, '[role=tabpanel] .section-lede')).toContain('background agent');
    expect(fixture.nativeElement.querySelector('.generate-button')).toBeNull();       // no Generate button here
    expect(fixture.nativeElement.querySelector('.generation-status')).toBeNull();
    const card = fixture.nativeElement.querySelector('article');
    expect(card.textContent).toContain('Auto generated'); expect(card.textContent).toContain('Matches your interest in Drama.');
    expect(card.textContent).toContain('#1 · Ordering score 1.00');
    expect(card.querySelector('.ordering').title).toContain('not a probability');
  });

  it('shows a friendly empty state when the background agent has not produced anything yet', () => {
    const { fixture } = setup(serve([]));
    expect(text(fixture, '.empty-state')).toBe('Your personalized recommendations are being prepared. Check back soon!');
    expect(fixture.nativeElement.querySelectorAll('article')).toHaveLength(0);
  });

  it('reports a load error with a retry button', () => {
    const { fixture, backend, page } = setup(() => throwError(() => new Error('offline')));
    expect(page.listError()).not.toBe(''); expect(page.listLoading()).toBe(false);
    expect(fixture.nativeElement.querySelector('.empty-state')).toBeNull();
    backend.get.mockImplementation(serve([autoItem]));
    (fixture.nativeElement.querySelector('.error button') as HTMLButtonElement).click(); fixture.detectChanges();
    expect(page.listError()).toBe(''); expect(page.results()).toHaveLength(1);
  });

  it('"My Recommendations" lists only user_requested and carries the Generate button', () => {
    const { fixture, backend, page } = setup(serve([autoItem], [ownItem]));
    tabs(fixture)[1].click(); fixture.detectChanges();
    expect(page.source()).toBe('user_requested');
    expect(backend.get).toHaveBeenCalledWith(OWN_URL);
    expect(tabs(fixture).map(tab => tab.getAttribute('aria-selected'))).toEqual(['false', 'true']);
    expect(fixture.nativeElement.querySelector('[role=tabpanel]').getAttribute('aria-labelledby')).toBe('recommendations-tab-user_requested');
    expect(text(fixture, '.generate-button')).toBe('Generate recommendations');
    const cards = fixture.nativeElement.querySelectorAll('article');
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain('User requested'); expect(cards[0].textContent).toContain('Requested one.');
    expect(cards[0].textContent).not.toContain('Matches your interest in Drama.');   // the automatic set is not repeated here
    tabs(fixture)[0].click(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.generate-button')).toBeNull();
    expect(fixture.nativeElement.querySelector('article').textContent).toContain('Matches your interest in Drama.');
    expect(fixture.nativeElement.querySelector('article').textContent).not.toContain('Requested one.');
  });

  it('shows an empty state for "My Recommendations" that points to Generate', () => {
    const { fixture, page } = setup(serve([autoItem], []));
    page.selectView('user_requested'); fixture.detectChanges();
    expect(text(fixture, '.empty-state')).toContain('Generate recommendations');
  });

  it('returns focus to the Generate button when the filter dialog closes, if it is on screen', () => {
    const { fixture, page } = setup();
    expect(() => page.restoreFocus()).not.toThrow();                            // not on "My Recommendations": no button, nothing to focus
    page.selectView('user_requested'); fixture.detectChanges();
    const focus = vi.spyOn(page.trigger()!.nativeElement, 'focus');
    page.restoreFocus(); expect(focus).toHaveBeenCalledOnce();
  });

  it('does nothing when the active tab is clicked again', () => {
    const { page, backend } = setup(serve([autoItem]));
    const calls = backend.get.mock.calls.length;
    page.selectView('auto'); expect(backend.get).toHaveBeenCalledTimes(calls);
  });

  it('supports keyboard navigation between the two tabs', () => {
    const { fixture, page } = setup();
    document.body.appendChild(fixture.nativeElement);
    const press = (key: string, index: number) => { const event = new KeyboardEvent('keydown', { key, cancelable: true }); page.navigateView(event, index); return event; };
    expect(press('x', 0).defaultPrevented).toBe(false); expect(page.source()).toBe('auto');
    expect(press('ArrowRight', 0).defaultPrevented).toBe(true); expect(page.source()).toBe('user_requested');
    press('ArrowLeft', 1); expect(page.source()).toBe('auto');
    press('End', 0); expect(page.source()).toBe('user_requested');
    press('Home', 1); expect(page.source()).toBe('auto');
    fixture.nativeElement.remove();
  });

  it('searches inside the current tab with that tab\'s source and clears the search when switching', () => {
    vi.useFakeTimers();
    try {
      const { fixture, backend, page } = setup(serve([autoItem], [ownItem]));
      expect(page.hasSearchItems()).toBe(true);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('input[type=search]')).not.toBeNull();
      const called = (url: string, ...rest: unknown[]) => backend.get.mock.calls.some(call => call[0] === url && JSON.stringify(call.slice(1)) === JSON.stringify(rest));
      page.searchMovies('drama'); vi.advanceTimersByTime(250);
      expect(called('/api/user/profile/recommendations?source=auto&offset=0&q=drama', { timeoutMs: 15000 })).toBe(true);
      page.selectView('user_requested');
      expect(page.search()).toBe('');
      expect(called(OWN_URL)).toBe(true);
      page.searchMovies('dune'); vi.advanceTimersByTime(250);
      expect(called('/api/user/profile/recommendations?source=user_requested&offset=0&q=dune', { timeoutMs: 15000 })).toBe(true);
      page.searchMovies('pending'); page.selectView('auto'); vi.advanceTimersByTime(500);   // a pending search never leaks into the other tab
      expect(backend.get.mock.calls.some(call => String(call[0]).includes('q=pending'))).toBe(false);
      expect(page.search()).toBe('');
      backend.get.mockReturnValue(of(emptyPage)); page.searchMovies('zzz'); vi.advanceTimersByTime(250); fixture.detectChanges();
      expect(text(fixture, '.empty-state')).toBe('No movies found.');
    } finally { vi.useRealTimers(); }
  });

  it('keeps generation state on its own tab and shows it again when you come back', () => {
    vi.useFakeTimers();
    try {
      const { fixture, backend, page } = ready();
      polling(backend, [of(job('running'))]);
      backend.post.mockReturnValue(of(job('queued')));
      const form = fixture.nativeElement.querySelector('form') as HTMLFormElement;
      const dialog = document.createElement('dialog'); dialog.close = vi.fn();
      page.submit(new Event('submit'), form, dialog); vi.advanceTimersByTime(0); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.generation-status')).not.toBeNull();
      page.selectView('auto'); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.generation-status')).toBeNull();     // not shown above the automatic list
      expect(page.generating()).toBe(true);
      page.selectView('user_requested'); fixture.detectChanges();
      expect(text(fixture, '.generation-status')).toContain('choosing recommendations');
    } finally { vi.useRealTimers(); }
  });

  it('reloads the saved results every time the section is opened again', () => {
    const first = setup(serve([autoItem]));
    const loads = (url: string) => first.backend.get.mock.calls.filter(([called]) => called === url).length;
    expect(loads(AUTO_URL)).toBe(1);
    first.fixture.destroy();                                                    // the user leaves the Recommendations sub-tab...
    const again = TestBed.createComponent(ProfileRecommendations); again.detectChanges();      // ...and comes back
    expect(loads(AUTO_URL)).toBe(2);
    expect(again.componentInstance.results()).toHaveLength(1);
    expect(first.backend.post).not.toHaveBeenCalled();
  });

  it('numbers cards by position within the current list, across pages', () => {
    const { fixture, page } = setup(url => url.startsWith('/api/movie') ? of({ movies: [movie] }) : of({ items: [autoItem], total: 60, offset: 25 }));
    page.loadResults(25); fixture.detectChanges();
    expect(text(fixture, '.ordering')).toBe('#26 · Ordering score 1.00');
    expect(fixture.nativeElement.querySelector('.pagination')).not.toBeNull();
  });
});

it('debounces recommendation search and keeps search available for empty matches', () => {
  vi.useFakeTimers();
  try {
    const { page, fixture, backend } = setup();
    backend.get.mockReturnValue(of({ items: [], total: 3, offset: 0 })); page.loadResults(); expect(page.hasSearchItems()).toBe(true);
    backend.get.mockReturnValue(of(emptyPage));
    page.searchMovies('old'); page.searchMovies(' title & '); vi.advanceTimersByTime(250);
    expect(backend.get).toHaveBeenLastCalledWith('/api/user/profile/recommendations?source=auto&offset=0&q=title%20%26', { timeoutMs: 15000 });
    expect(page.hasSearchItems()).toBe(true); expect(page.results()).toEqual([]);
    page.searchMovies('cancel'); const calls = backend.get.mock.calls.length; fixture.destroy(); vi.runAllTimers(); expect(backend.get).toHaveBeenCalledTimes(calls);
  } finally { vi.useRealTimers(); }
});
