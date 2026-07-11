const { createProxyMiddleware } = require("http-proxy-middleware");

/**
 * Route ALL requests to FastAPI (port 8001) except React dev server internals.
 *
 * FastAPI serves: API routes, SEO pages, GEO city pages, static build assets,
 * and the SPA catch-all (index.html).
 *
 * React dev server only handles: HMR websocket, webpack hot updates.
 */
module.exports = function (app) {
  app.use(
    "/",
    createProxyMiddleware({
      target: "http://localhost:8001",
      changeOrigin: true,
      ws: true,
      // Let React dev server handle its own internals
      filter: function (pathname) {
        // Keep HMR/webpack dev server paths on React
        if (pathname.startsWith("/sockjs-node")) return false;
        if (pathname.startsWith("/ws")) return false;
        if (pathname.match(/\.(hot-update\.js|hot-update\.json)$/)) return false;
        // Proxy everything else to FastAPI
        return true;
      },
    })
  );
};
