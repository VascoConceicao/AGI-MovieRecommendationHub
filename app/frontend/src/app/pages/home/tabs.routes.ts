import { Routes } from '@angular/router';
import { SearchTab } from '../../components/tabs/search/search';
import { PublicProfilePage } from '../../components/tabs/search/public-profile';
import { ProfileTab } from '../../components/tabs/profile/profile';
import { publicProfileGuard } from '../../shared/services/backend/auth/auth.service';

const tabs = [
  { path: 'profile', component: ProfileTab, data: { label: 'Profile' } },
  { path: 'search', component: SearchTab, data: { label: 'Search' } },
] satisfies Routes;

export const tabRoutes: Routes = [
  { path: '', redirectTo: tabs[0].path, pathMatch: 'full' },
  { path: 'search/users/:id', component: PublicProfilePage, canActivate: [publicProfileGuard] },
  ...tabs,
];

export const tabNavigation = tabs.map(tab => ({
  label: tab.data.label,
  path: `/home/${tab.path}`,
}));
