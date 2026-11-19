import { Component, inject } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { RouterOutlet } from '@angular/router';
import palette from './assets/palette.json';

@Component({ selector: 'app-root', imports: [RouterOutlet], templateUrl: './app.html' })
export class App {
  constructor() {
    const root = inject(DOCUMENT).documentElement;
    for (const [name, color] of Object.entries(palette)) {
      root.style.setProperty(`--${name.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`, color);
    }
  }
}
