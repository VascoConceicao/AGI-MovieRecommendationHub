import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, timeout } from 'rxjs';

export interface BackendRequestOptions {
  headers?: Record<string, string>;
  timeoutMs?: number;
}

@Injectable({ providedIn: 'root' })
export class BackendService {
  private readonly http = inject(HttpClient);

  get<T>(url: string, options: BackendRequestOptions = {}): Observable<T> {
    return this.request<T>('GET', url, undefined, options);
  }

  post<T>(url: string, body: unknown, options: BackendRequestOptions = {}): Observable<T> {
    return this.request<T>('POST', url, body, options);
  }

  private request<T>(method: 'GET' | 'POST', url: string, body: unknown,
                     options: BackendRequestOptions): Observable<T> {
    return this.http.request<T>(method, url, { body, headers: options.headers }).pipe(
      timeout(options.timeoutMs ?? 8000),
    );
  }
}
