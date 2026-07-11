
let _granted = true;
let _signals = [];
module.exports = {
  requestHealthPermissions: async () => _granted,
  fetchDeltaSignals: async () => _signals,
  resetLastSync: async () => undefined,
  __setMock: (g, s) => { _granted = g; _signals = s; },
};