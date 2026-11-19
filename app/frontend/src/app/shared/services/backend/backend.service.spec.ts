import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { TimeoutError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BackendService } from './backend.service';

describe('BackendService', () => {
  let backend: BackendService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    backend = TestBed.inject(BackendService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  it('returns typed GET responses without adding auth-specific headers', () => {
    const next = vi.fn();
    backend.get<{ value: number }>('/api/example').subscribe(next);
    const request = http.expectOne('/api/example');
    expect(request.request.method).toBe('GET');
    expect(request.request.headers.has('X-G15-Request')).toBe(false);
    request.flush({ value: 42 });
    expect(next).toHaveBeenCalledWith({ value: 42 });
  });

  it('forwards POST payloads and caller headers', () => {
    backend.post('/api/example', { value: 42 }, { headers: { 'X-Example': 'test' } }).subscribe();
    const request = http.expectOne('/api/example');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ value: 42 });
    expect(request.request.headers.get('X-Example')).toBe('test');
    request.flush({});
  });

  it('also supports POST without options', () => {
    backend.post('/api/example', {}).subscribe();
    http.expectOne('/api/example').flush({});
  });

  it('preserves HTTP errors for domain services to interpret', () => {
    const error = vi.fn();
    backend.get('/api/example').subscribe({ error });
    http.expectOne('/api/example').flush({ error: 'Unavailable' }, { status: 503, statusText: 'Unavailable' });
    expect(error.mock.calls[0]?.[0]).toBeInstanceOf(HttpErrorResponse);
    expect(error.mock.calls[0]?.[0].status).toBe(503);
  });

  for (const timeoutMs of [undefined, 15000]) {
    it(`cancels requests after ${timeoutMs ?? 8000}ms`, () => {
      vi.useFakeTimers();
      const error = vi.fn();
      backend.get('/api/example', { timeoutMs }).subscribe({ error });
      const request = http.expectOne('/api/example');
      vi.advanceTimersByTime((timeoutMs ?? 8000) - 1);
      expect(error).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(error.mock.calls[0]?.[0]).toBeInstanceOf(TimeoutError);
      expect(request.cancelled).toBe(true);
    });
  }
});
