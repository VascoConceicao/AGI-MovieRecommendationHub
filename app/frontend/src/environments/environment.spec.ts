import { expect, it } from 'vitest';
import { environment as active } from './environment';
import { environment as stage } from './environment.stage';
import { environment as local } from './environment.local';
import { environment as development } from './environment.development';

it('uses the local proxy for each deployment environment', () => {
  for (const environment of [active, stage, local, development]) {
    expect(environment.healthEndpoints).toEqual({ movie: '/api/movie/health', recommendation: '/api/recommendation/health', user: '/api/user/health' });
  }
  expect(active.production).toBe(true); expect(stage.production).toBe(true);
  expect(local.production).toBe(false); expect(development.production).toBe(false);
});
