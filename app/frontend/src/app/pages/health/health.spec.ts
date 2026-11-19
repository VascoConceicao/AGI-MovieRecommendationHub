import { TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { HealthService } from '../../shared/services/backend/health/health.service';
import { HealthPage } from './health';

describe('HealthPage', () => {
  it('checks each service and updates its state', () => {
    const check = vi.fn(() => of({ state: 'up' }));
    TestBed.configureTestingModule({ providers: [{ provide: HealthService, useValue: { check } }] });
    const fixture = TestBed.createComponent(HealthPage);
    fixture.detectChanges();
    const page = fixture.componentInstance;
    expect(fixture.nativeElement.textContent).toContain('Service and database connected');
    expect(check).toHaveBeenCalledTimes(3);
    expect(page.states()).toEqual({ movie: 'up', recommendation: 'up', user: 'up' });
    expect(page.pending()).toBe(0);
  });
  it('does not overlap refresh requests', () => {
    const check = vi.fn(() => new Subject());
    TestBed.configureTestingModule({ providers: [{ provide: HealthService, useValue: { check } }] });
    const page = TestBed.createComponent(HealthPage).componentInstance;
    page.refresh();
    expect(check).toHaveBeenCalledTimes(3);
    expect(page.pending()).toBe(3);
  });
});
