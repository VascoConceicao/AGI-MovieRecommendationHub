import { Routes } from '@angular/router';
import { CreditsPage } from './pages/credits/credits';
import { HealthPage } from './pages/health/health';
import { AuthPage } from './pages/auth/auth';
import { HomePage } from './pages/home/home';
import { tabRoutes } from './pages/home/tabs.routes';
import { signedInGuard } from './shared/services/backend/auth/auth.service';

export const routes: Routes = [
  { path: '', redirectTo: 'home', pathMatch: 'full' },
  { path: 'login', component: AuthPage, data: { register: false } },
  { path: 'register', component: AuthPage, data: { register: true } },
  { path: 'home', component: HomePage, canActivate: [signedInGuard], children: tabRoutes },
  { path: 'account', redirectTo: 'home/profile', pathMatch: 'full' },
  { path: 'profile', redirectTo: 'home/profile', pathMatch: 'full' },
  { path: 'credits', component: CreditsPage },
  { path: 'health', component: HealthPage },
  { path: '**', redirectTo: 'login' },
];
