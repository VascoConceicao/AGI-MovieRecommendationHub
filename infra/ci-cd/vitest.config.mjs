// CI shares Kubernetes nodes with the app and monitoring.
export default {
  test: {
    pool: 'threads',
    maxWorkers: 1,
    fileParallelism: false,
    testTimeout: 30000,
    hookTimeout: 30000,
  },
};
