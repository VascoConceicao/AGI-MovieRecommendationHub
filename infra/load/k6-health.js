import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 50 },
    { duration: '2m', target: 100 },
    { duration: '1m30s', target: 200 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

const BASE = __ENV.K6_BASE_URL || 'http://34.175.14.61:30080';
const PATHS = ['/api/movie/health', '/api/recommendation/health', '/api/user/health', '/'];

export default function () {
  const path = PATHS[Math.floor(Math.random() * PATHS.length)];
  const res = http.get(`${BASE}${path}`);
  check(res, { 'status is 2xx': (r) => r.status >= 200 && r.status < 300 });
  sleep(0.2);
}
