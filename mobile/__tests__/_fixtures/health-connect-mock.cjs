module.exports = {
  initialize: async () => { if (globalThis.__hc01_initShouldThrow__) throw new Error('Health Connect not installed'); return true; },
  requestPermission: async () => (globalThis.__hc01_initShouldThrow__ ? [] : [{ accessType: 'read', recordType: 'HeartRate' }]),
  readRecords: async () => ({ records: [] }),
};