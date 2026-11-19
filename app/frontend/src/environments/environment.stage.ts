import { Environment } from './environment.model';

export const environment: Environment = {
  production: true,
  healthEndpoints: {
    movie: '/api/movie/health',
    recommendation: '/api/recommendation/health',
    user: '/api/user/health',
  },
};
