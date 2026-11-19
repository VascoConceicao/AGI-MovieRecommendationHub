export interface Environment {
  production: boolean;
  healthEndpoints: { movie: string; recommendation: string; user: string };
}
