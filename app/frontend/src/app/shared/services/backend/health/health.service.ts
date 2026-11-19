import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, map, Observable, of } from 'rxjs';
import { BackendService } from '../backend.service';
import { environment } from '../../../../../environments/environment';
import { HealthResult, ServiceKey } from '../../../types/health';

function isHealth(value: unknown, service: ServiceKey, ready: boolean): boolean {
  if (!value || typeof value !== 'object') return false;
  const body = value as Record<string, unknown>;
  return body['service'] === `${service}-service`
    && body['status'] === (ready ? 'ok' : 'unavailable')
    && body['database'] === (ready ? 'up' : 'down');
}

@Injectable({ providedIn: 'root' })
export class HealthService {
  private readonly backend = inject(BackendService);

  check(service: ServiceKey): Observable<HealthResult> {
    return this.backend.get<unknown>(environment.healthEndpoints[service]).pipe(
      map((body): HealthResult => ({ state: isHealth(body, service, true) ? 'up' : 'unreachable' })),
      catchError((error: unknown) => of<HealthResult>({
        state: error instanceof HttpErrorResponse && error.status === 503
          && isHealth(error.error, service, false) ? 'down' : 'unreachable',
      })),
    );
  }
}
