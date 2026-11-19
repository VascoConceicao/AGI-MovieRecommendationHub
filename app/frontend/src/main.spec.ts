import { bootstrapApplication } from '@angular/platform-browser';
import { describe, expect, it, vi } from 'vitest';
import { App } from './app/app';
import { appConfig } from './app/app.config';

vi.mock('@angular/platform-browser', async importOriginal => ({
  ...await importOriginal<typeof import('@angular/platform-browser')>(),
  bootstrapApplication: vi.fn(() => Promise.reject(new Error('bootstrap failed'))),
}));

describe('application startup', () => {
  it('bootstraps the app and reports startup failures', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    await import('./main');
    await Promise.resolve();
    expect(bootstrapApplication).toHaveBeenCalledWith(App, appConfig);
    expect(error).toHaveBeenCalledWith(expect.objectContaining({ message: 'bootstrap failed' }));
  });
});
