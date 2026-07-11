
const _store = new Map();
const impl = {
  getItem: async (k) => _store.get(k) ?? null,
  setItem: async (k, v) => { _store.set(k, v); },
  removeItem: async (k) => { _store.delete(k); },
  __dump: () => Object.fromEntries(_store),
};
module.exports = impl;
module.exports.default = impl;
module.exports.__esModule = true;