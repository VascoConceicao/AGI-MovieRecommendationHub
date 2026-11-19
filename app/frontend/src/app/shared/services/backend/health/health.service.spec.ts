import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { environment } from '../../../../../environments/environment';
import { HealthService } from './health.service';

describe('HealthService', () => {
  let http: HttpTestingController;
  let service: HealthService;
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    service = TestBed.inject(HealthService);
  });
  afterEach(() => http.verify());

  for (const body of [null, 'invalid', {}, { service: 'movie-service', status: 'ok', database: 'up' }]) {
    it(`validates the response body ${JSON.stringify(body)}`, () => {
      let state = '';
      service.check('movie').subscribe(result => state = result.state);
      http.expectOne(environment.healthEndpoints.movie).flush(body);
      expect(state).toBe(body && typeof body === 'object' && 'service' in body ? 'up' : 'unreachable');
    });
  }
  it('recognizes a reached service with an unavailable DB', () => {
    let state = '';
    service.check('user').subscribe(result => state = result.state);
    http.expectOne(environment.healthEndpoints.user).flush({ service: 'user-service', status: 'unavailable', database: 'down' },
      { status: 503, statusText: 'Unavailable' });
    expect(state).toBe('down');
  });
  it('rejects an unrelated error response', () => {
    let state = '';
    service.check('user').subscribe(result => state = result.state);
    http.expectOne(environment.healthEndpoints.user).flush({}, { status: 500, statusText: 'Error' });
    expect(state).toBe('unreachable');
  });
});
