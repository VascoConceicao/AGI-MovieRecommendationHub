export type ServiceKey = 'movie' | 'recommendation' | 'user';
export type HealthState = 'checking' | 'up' | 'down' | 'unreachable';
export interface HealthResult { state: HealthState; }
