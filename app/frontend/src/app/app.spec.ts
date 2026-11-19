import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { App } from './app';
import palette from './assets/palette.json';

describe('App palette', () => {
  it('applies every palette color as a CSS variable', () => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('router-outlet')).not.toBeNull();
    for (const [name, color] of Object.entries(palette)) {
      const variable = `--${name.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`;
      expect(document.documentElement.style.getPropertyValue(variable)).toBe(color);
    }
  });
});
