
const store = {
  getItem: async (k) => (k in global.__cgs_kv ? global.__cgs_kv[k] : null),
  setItem: async (k, v) => { global.__cgs_kv[k] = v; },
  removeItem: async (k) => { delete global.__cgs_kv[k]; },
};
Object.defineProperty(module.exports, '__esModule', { value: true });
module.exports.default = store;
