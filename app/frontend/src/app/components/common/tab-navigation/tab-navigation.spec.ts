import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { expect, it } from 'vitest';
import { TabNavigation } from './tab-navigation';

it('renders tab labels and routes', () => {
  TestBed.configureTestingModule({ providers: [provideRouter([])] });
  const fixture = TestBed.createComponent(TabNavigation);
  fixture.componentRef.setInput('tabs', [{ label: 'Profile', path: '/home/profile' }]);
  fixture.detectChanges();
  const link = fixture.nativeElement.querySelector('a');
  expect(link.textContent.trim()).toBe('Profile');
  expect(link.getAttribute('href')).toBe('/home/profile');
});
