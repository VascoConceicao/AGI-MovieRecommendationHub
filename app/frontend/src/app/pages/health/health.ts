import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs';
import { HealthService, HealthState, ServiceKey } from '../../shared';

@Component({
  selector: 'app-health',
  templateUrl: './health.html',
})
export class HealthPage {
  private readonly health = inject(HealthService);
  private readonly destroyRef = inject(DestroyRef);
  readonly services: { key: ServiceKey; label: string }[] = [
    { key: 'movie', label: 'Movies' },
    { key: 'recommendation', label: 'Recommendations' },
    { key: 'user', label: 'Users' },
  ];
  readonly states = signal<Record<ServiceKey, HealthState>>({
    movie: 'checking', recommendation: 'checking', user: 'checking',
  });
  readonly pending = signal(0);
  readonly labels: Record<HealthState, string> = {
    checking: 'Checking connection?',
    up: 'Service and database connected',
    down: 'Service reached ? database unavailable',
    unreachable: 'Could not verify service connection',
  };

  constructor() { this.refresh(); }

  refresh(): void {
    if (this.pending()) return;
    this.pending.set(this.services.length);
    for (const service of this.services) {
      this.states.update(states => ({ ...states, [service.key]: 'checking' }));
      this.health.check(service.key).pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.pending.update(count => count - 1)),
      ).subscribe(result => this.states.update(states => ({ ...states, [service.key]: result.state })));
    }
  }
}
