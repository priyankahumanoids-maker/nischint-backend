
const calls = global.__cgs_calls;
const api = {
  post: async (url, body) => { calls.push({ method: 'post', url, body }); return { data: {} }; },
};
api['delete'] = async (url) => { calls.push({ method: 'delete', url }); return { data: {} }; };
Object.defineProperty(module.exports, '__esModule', { value: true });
module.exports.default = api;
