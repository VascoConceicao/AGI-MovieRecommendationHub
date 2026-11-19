import { Environment } from './environment.model';

export const environment: Environment = {
  production: false,
  healthEndpoints: {
    movie: '/api/movie/health',
    recommendation: '/api/recommendation/health',
    user: '/api/user/health',
  },
};
