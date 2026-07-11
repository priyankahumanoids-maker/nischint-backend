// API Service with JWT handling
import axios from 'axios';

// Always use relative paths — works on any domain without CORS issues
const API_URL = '';

// Create axios instance
const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Token management
let accessToken = localStorage.getItem('nischint_token');

export const setToken = (token) => {
  accessToken = token;
  if (token) {
    localStorage.setItem('nischint_token', token);
  } else {
    localStorage.removeItem('nischint_token');
  }
};

export const getToken = () => accessToken;

export const isAuthenticated = () => !!accessToken;

// Add token to requests
api.interceptors.request.use(
  (config) => {
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Handle 401 responses
//
// Surgical: only force-logout when the backend signals an actual
// credentials failure (`"Could not validate credentials"` /
// `"Token expired"` / `"Invalid token"`).
//
// Why: a blanket "any 401 → clear auth + redirect" loop misclassifies
//   - role/permission denials (which are 403, but Cloudflare/proxies
//     occasionally rewrite),
//   - race-conditions where a request fired before the token was set
//     (backend says "Not authenticated") — clearing auth here would
//     log out a user who just logged in.
// The interceptor must distinguish "session is dead" from "this single
// request was anonymous / forbidden" and only act on the former.
const CREDENTIAL_FAILURE_HINTS = [
  'could not validate credentials',
  'token expired',
  'invalid token',
  'token has expired',
  'signature has expired',
];

const isCredentialsFailure = (error) => {
  if (error.response?.status !== 401) return false;
  const detail = (error.response?.data?.detail || '').toString().toLowerCase();
  return CREDENTIAL_FAILURE_HINTS.some((h) => detail.includes(h));
};

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isCredentialsFailure(error)) {
      setToken(null);
      window.location.href = '/login';
    } else if (error.response?.status === 401) {
      // Anonymous / unauthenticated request — log a hint but do NOT
      // log the user out. The caller's .catch will handle it.
      // eslint-disable-next-line no-console
      console.warn('[AUTH] 401 ignored (not a credentials failure):', error.response?.data?.detail);
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: async (email, password) => {
    const response = await api.post('/auth/login', { email, password });
    return response.data;
  },
  register: async (email, password, full_name, phone) => {
    const response = await api.post('/auth/register', { email, password, full_name, phone: phone || null });
    return response.data;
  },
};

// Dashboard API
export const dashboardApi = {
  getSummary: async () => {
    const response = await api.get('/dashboard/summary');
    return response.data;
  },
};

// Users API
export const usersApi = {
  getUser: async (userId) => {
    const response = await api.get(`/users/${userId}`);
    return response.data;
  },
  createUser: async (email, password) => {
    const response = await api.post('/users', { email, password });
    return response.data;
  },
};

// Seniors API (self-service)
export const seniorsApi = {
  getSeniors: async (guardianId) => {
    const response = await api.get(`/users/${guardianId}/seniors`);
    return response.data;
  },
  createSenior: async (guardianId, data) => {
    const response = await api.post(`/users/${guardianId}/seniors`, data);
    return response.data;
  },
  getMySeniors: async () => {
    const response = await api.get('/my/seniors');
    return response.data;
  },
  createMySenior: async (data) => {
    const response = await api.post('/my/seniors', data);
    return response.data;
  },
};

// Devices API (self-service)
export const devicesApi = {
  getDevices: async (seniorId) => {
    const response = await api.get(`/seniors/${seniorId}/devices`);
    return response.data;
  },
  getMyDevices: async (seniorId) => {
    const response = await api.get(`/my/seniors/${seniorId}/devices`);
    return response.data;
  },
  linkDevice: async (seniorId, data) => {
    const response = await api.post(`/my/seniors/${seniorId}/devices`, data);
    return response.data;
  },
  getTelemetry: async (deviceId, limit = 100) => {
    const response = await api.get(`/devices/${deviceId}/telemetry?limit=${limit}`);
    return response.data;
  },
};

// Incidents API
export const incidentsApi = {
  getIncidents: async (guardianId, status = null) => {
    let url = `/incidents?guardian_id=${guardianId}`;
    if (status) {
      url += `&status=${status}`;
    }
    const response = await api.get(url);
    return response.data;
  },
  acknowledge: async (incidentId) => {
    const response = await api.patch(`/incidents/${incidentId}/acknowledge`);
    return response.data;
  },
  resolve: async (incidentId) => {
    const response = await api.patch(`/incidents/${incidentId}/resolve`);
    return response.data;
  },
  markFalseAlarm: async (incidentId) => {
    const response = await api.patch(`/incidents/${incidentId}/false-alarm`);
    return response.data;
  },
};

// SSE Stream API with auto-reconnect (capped exponential backoff to prevent reconnect storms).
export const createEventSource = (onEvent, onError, onStatusChange) => {
  const abortController = new AbortController();
  let retryTimeout = null;
  let closed = false;

  // Backoff state — resets to MIN on every clean `connected`.
  const RETRY_MIN_MS = 1000;
  const RETRY_MAX_MS = 30_000;
  let retryDelay = RETRY_MIN_MS;
  const scheduleReconnect = () => {
    if (closed) return;
    onStatusChange?.('reconnecting');
    retryTimeout = setTimeout(connect, retryDelay);
    retryDelay = Math.min(RETRY_MAX_MS, retryDelay * 2);
  };

  const connect = async () => {
    if (closed) return;
    const token = getToken();
    if (!token) {
      console.error('No token available for SSE');
      return;
    }

    const url = `${API_URL}/api/stream?token=${encodeURIComponent(token)}`;
    onStatusChange?.('connecting');

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'text/event-stream',
        },
        signal: abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`SSE connection failed: ${response.status}`);
      }

      onStatusChange?.('connected');
      retryDelay = RETRY_MIN_MS;  // reset on successful connect
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let eventType = 'message';
        let eventData = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7);
          } else if (line.startsWith('data: ')) {
            eventData = line.slice(6);
          } else if (line === '' && eventData) {
            try {
              const data = JSON.parse(eventData);
              onEvent(eventType, data);
            } catch (e) {
              console.error('Failed to parse SSE data:', e);
            }
            eventType = 'message';
            eventData = '';
          }
        }
      }
      // Stream ended normally — reconnect with backoff.
      if (!closed) {
        console.warn(`SSE stream ended. Reconnecting in ${retryDelay}ms...`);
        scheduleReconnect();
      }
    } catch (error) {
      if (error.name === 'AbortError' || closed) return;
      console.error('SSE error:', error);
      onError?.(error);
      scheduleReconnect();
    }
  };

  connect();

  return {
    close: () => {
      closed = true;
      abortController.abort();
      if (retryTimeout) clearTimeout(retryTimeout);
    },
  };
};

export default api;

// Operator API
export const operatorApi = {
  retryNotificationJob: (id) => api.post(`/operator/notification-jobs/${id}/retry`),
  cancelNotificationJob: (id) => api.post(`/operator/notification-jobs/${id}/cancel`),
  getHealthRules: () => api.get('/operator/health-rules'),
  updateHealthRule: (ruleName, payload) => api.put(`/operator/health-rules/${ruleName}`, payload),
  toggleHealthRule: (ruleName, enabled) => api.patch(`/operator/health-rules/${ruleName}/toggle`, { enabled }),
  getHealthRuleAuditLog: (ruleName) => api.get(`/operator/health-rules/${ruleName}/audit-log`),
  simulateHealthRule: (ruleName, payload) => api.post(`/operator/health-rules/${ruleName}/simulate`, payload),
  revertHealthRule: (ruleName, createdAt) => api.post(`/operator/health-rules/${ruleName}/revert/${createdAt}`),
  getDeviceAnomalies: (hours = 24) => api.get(`/operator/device-anomalies?hours=${hours}`),
  getDeviceHealth: () => api.get('/operator/device-health'),
  getSimulationHistory: (page = 1, limit = 20, runType = null) => {
    let url = `/operator/simulations?page=${page}&limit=${limit}`;
    if (runType) url += `&run_type=${runType}`;
    return api.get(url);
  },
  getSimulationDetail: (simulationRunId) => api.get(`/operator/simulations/${simulationRunId}`),
  getEscalationAnalytics: (windowMinutes = 1440) => api.get(`/operator/escalation-analytics?window_minutes=${windowMinutes}`),
  compareMultiMetric: (payload) => api.post('/operator/simulate/compare/multi-metric', payload),
  getDeviceMetricTrends: (deviceId, windowMinutes = 60, metrics = 'battery,signal,combined') =>
    api.get(`/operator/devices/${deviceId}/metric-trends?window_minutes=${windowMinutes}&metrics=${metrics}`),
  getReplayTimeline: (startTime, endTime, threshold = 60) =>
    api.get(`/operator/replay-timeline?start_time=${encodeURIComponent(startTime)}&end_time=${encodeURIComponent(endTime)}&threshold=${threshold}`),
  getFleetHealthTrends: (windowMinutes = 1440) =>
    api.get(`/operator/fleet-health-trends?window_minutes=${windowMinutes}`),
  getDeviceBehaviorPattern: (deviceId, windowHours = 24) =>
    api.get(`/operator/devices/${deviceId}/behavior-pattern?window_hours=${windowHours}`),
  simulateBehavior: (payload) => api.post('/operator/simulate/behavior', payload),
  getDeviceDigitalTwin: (deviceId) => api.get(`/operator/devices/${deviceId}/digital-twin`),
  rebuildDeviceDigitalTwin: (deviceId) => api.post(`/operator/devices/${deviceId}/digital-twin/rebuild`),
  getFleetDigitalTwins: () => api.get('/operator/digital-twins/fleet'),
  getDevicePredictiveRisk: (deviceId) => api.get(`/operator/devices/${deviceId}/predictive-risk`),
  getFleetPredictiveAlerts: () => api.get('/operator/predictive-alerts'),
  // AI Narrative Engine
  generateNarrative: (incidentId) => api.post(`/operator/incidents/${incidentId}/narrative`),
  getNarratives: (incidentId, limit = 10) => api.get(`/operator/incidents/${incidentId}/narrative?limit=${limit}`),
  getNarrativeStatus: (incidentId) => api.get(`/operator/incidents/${incidentId}/narrative/status`),
  // Risk Forecast Timeline
  getDeviceRiskForecast: (deviceId) => api.get(`/operator/devices/${deviceId}/risk-forecast`),
  // Safety Score
  getDeviceSafetyScore: (deviceId) => api.get(`/operator/devices/${deviceId}/safety-score`),
  getFleetSafety: () => api.get('/operator/fleet-safety'),
  // Twin Evolution Timeline
  getTwinEvolution: (deviceId, weeks = 8) => api.get(`/operator/devices/${deviceId}/twin-evolution?weeks=${weeks}`),
  // Life Pattern Graph
  getDeviceLifePattern: (deviceId, days = 30) => api.get(`/operator/devices/${deviceId}/life-pattern?days=${days}`),
  // Location Risk Intelligence
  evaluateLocationRisk: (lat, lng) => api.get(`/operator/location-risk?lat=${lat}&lng=${lng}`),
  getLocationHeatmap: () => api.get('/operator/location-risk/heatmap'),
  updateDeviceLocation: (deviceId, lat, lng) => api.post(`/operator/devices/${deviceId}/location?lat=${lat}&lng=${lng}`),
  createGeofence: (deviceId, params) => api.post(`/operator/devices/${deviceId}/geofence?name=${encodeURIComponent(params.name)}&lat=${params.lat}&lng=${params.lng}&radius=${params.radius || 500}&fence_type=${params.fence_type || 'safe'}`),
  checkGeofence: (deviceId, lat, lng) => api.post(`/operator/geofence-alert?device_id=${deviceId}&lat=${lat}&lng=${lng}`),
  // Environmental Risk AI
  evaluateEnvironmentRisk: (lat, lng) => api.get(`/operator/environment-risk?lat=${lat}&lng=${lng}`),
  getFleetEnvironment: () => api.get('/operator/environment-risk/fleet'),
  // Route Safety
  evaluateRouteSafety: (startLat, startLng, endLat, endLng) => api.post(`/operator/route-safety?start_lat=${startLat}&start_lng=${startLng}&end_lat=${endLat}&end_lng=${endLng}`),
  // Route Monitoring
  assignRouteMonitor: (deviceId, routeIndex, startLat, startLng, endLat, endLng, routeData) =>
    api.post(`/operator/route-monitor?device_id=${deviceId}&route_index=${routeIndex}&start_lat=${startLat}&start_lng=${startLng}&end_lat=${endLat}&end_lng=${endLng}`, { route_data: routeData }),
  getRouteMonitorStatus: (deviceId) => api.get(`/operator/route-monitor/${deviceId}`),
  getActiveRouteMonitors: () => api.get('/operator/route-monitors'),
  cancelRouteMonitor: (deviceId) => api.delete(`/operator/route-monitor/${deviceId}`),
  suggestReroute: (deviceId) => api.post(`/operator/route-monitor/${deviceId}/reroute`),
  acceptReroute: (deviceId, routeData) => api.post(`/operator/route-monitor/${deviceId}/accept-reroute`, { route_data: routeData }),
  recalculateRouteRisk: (deviceId) => api.get(`/operator/route-monitor/${deviceId}/risk-update`),
  // Notifications
  sendNotification: (body) => api.post('/operator/notifications/send', body),
  getNotificationLog: (deviceId, limit = 50) => api.get(`/operator/notifications/log${deviceId ? `/${deviceId}` : ''}?limit=${limit}`),
  acknowledgeNotification: (notifId) => api.post(`/operator/notifications/${notifId}/acknowledge`),
  getNotificationPreferences: (userId) => api.get(`/operator/notifications/preferences/${userId}`),
  updateNotificationPreferences: (userId, prefs) => api.put(`/operator/notifications/preferences/${userId}`, prefs),
  getNotificationProviders: () => api.get('/operator/notifications/providers'),
  acknowledgeIncident: (incidentId) => api.post(`/operator/incidents/${incidentId}/acknowledge`),
  getEscalationConfig: () => api.get('/operator/escalation/config'),
  getEscalationPending: () => api.get('/operator/escalation/pending'),
  getEscalationHistory: (limit = 20) => api.get(`/operator/escalation/history?limit=${limit}`),
  getSmartGuardianProfile: (guardianId) => api.get(`/operator/escalation/smart-profile/${guardianId}`),
  getSmartRecommendation: (incidentId) => api.get(`/operator/escalation/smart-recommendation/${incidentId}`),
  getRiskLearningStats: () => api.get('/operator/risk-learning/stats'),
  getRiskLearningHotspots: () => api.get('/operator/risk-learning/hotspots'),
  triggerRiskRecalculation: () => api.post('/operator/risk-learning/recalculate'),
  getHotspotTrends: () => api.get('/operator/risk-learning/trends'),
  getHotspotTrendStats: () => api.get('/operator/risk-learning/trend-stats'),
  getZoneTrend: (zoneId) => api.get(`/operator/risk-learning/hotspots/${zoneId}/trend`),
  getRiskForecasts: () => api.get('/operator/risk-learning/forecast'),
  getRiskForecastStats: () => api.get('/operator/risk-learning/forecast-stats'),
  getZoneForecast: (zoneId) => api.get(`/operator/risk-learning/hotspots/${zoneId}/forecast`),
  assessActivityRisk: (lat, lng) => api.get(`/operator/human-activity-risk/assess?lat=${lat}&lng=${lng}`),
  getFleetActivityRisk: () => api.get('/operator/human-activity-risk/fleet'),
  getActivityHotspots: () => api.get('/operator/human-activity-risk/hotspots'),
  getForecastScenarios: () => api.get('/operator/simulate/forecast-scenarios'),
  runForecastScenario: (payload) => api.post('/operator/simulate/forecast-scenario', payload),
  // Incident Replay
  getIncidentReplay: (incidentId) => api.get(`/operator/incidents/${incidentId}/replay`),
  getIncidentTimeline: (incidentId) => api.get(`/operator/incidents/${incidentId}/timeline`),
  // Command Center (split endpoints for parallel loading)
  getCommandCenter: () => api.get('/operator/command-center'),
  getCommandCenterFleet: () => api.get('/operator/command-center/fleet'),
  getCommandCenterRisk: () => api.get('/operator/command-center/risk'),
  getCommandCenterIncidents: () => api.get('/operator/command-center/incidents'),
  getCommandCenterEnvironment: () => api.get('/operator/command-center/environment'),
  getCommandCenterFleetWeather: () => api.get('/operator/command-center/fleet-weather'),
  // Phase 1 — Unified per-user Command Center payload (versioned + timestamped)
  getCommandCenterUser: (userId) => api.get(`/operator/command-center/${userId}`),
  // Live Risk Panel — single-call decision surface ("what needs
  // attention in the next 10 seconds?"). Polled every 5s by the
  // docked tile. Backend is 10s-cached; safe to hit aggressively.
  getRiskPanel: (limit = 10) => api.get(`/command-center/risk-panel?incidents_limit=${limit}`),
  // Swipe-right on a tile row fires ack_type="acting" (commits the
  // operator to taking action). "resolved" requires an explicit
  // confirm gesture handled elsewhere to prevent misclick closure.
  ackAlert: (alertId, ackType = 'seen', confirmed = false) =>
    api.post(`/alerts/${alertId}/ack`, { ack_type: ackType, confirmed }),
  // Patrol Routing AI
  generatePatrolRoute: (params) => api.get('/operator/patrol/generate', { params }),
  getPatrolSummary: () => api.get('/operator/patrol/summary'),
  getPatrolShifts: () => api.get('/operator/patrol/shifts'),
  // City Heatmap AI
  getCityHeatmap: () => api.get('/operator/city-heatmap'),
  getCityHeatmapLive: () => api.get('/operator/city-heatmap/live'),
  getCityHeatmapDelta: () => api.get('/operator/city-heatmap/delta'),
  getCityHeatmapTimeline: (limit = 12) => api.get(`/operator/city-heatmap/timeline?limit=${limit}`),
  getCityHeatmapStatus: () => api.get('/operator/city-heatmap/status'),
  getCityHeatmapStats: () => api.get('/operator/city-heatmap/stats'),
  getCityHeatmapCell: (gridId) => api.get(`/operator/city-heatmap/cell/${gridId}`),
  // Safe Zone Detection
  checkZone: (payload) => api.post('/safety/check-zone', payload),
  getZoneMap: () => api.get('/safety/zone-map'),
  // Night Guardian
  startNightGuardian: (payload) => api.post('/night-guardian/start', payload),
  stopNightGuardian: (payload) => api.post('/night-guardian/stop', payload || {}),
  getNightGuardianStatus: (userId) => api.get('/night-guardian/status', { params: userId ? { user_id: userId } : {} }),
  getNightGuardianSessions: () => api.get('/night-guardian/sessions'),
  updateNightGuardianLocation: (payload) => api.post('/night-guardian/update-location', payload),
  acknowledgeNightGuardianSafety: () => api.post('/night-guardian/acknowledge-safety'),
  // Safe Route AI
  generateSafeRoute: (payload) => api.post('/safe-route', payload),
  // Guardian Mode
  addGuardianContact: (payload) => api.post('/guardian/add', payload),
  listGuardianContacts: () => api.get('/guardian/list'),
  removeGuardianContact: (id) => api.delete(`/guardian/remove/${id}`),
  startGuardianSession: (payload) => api.post('/guardian/start', payload),
  stopGuardianSession: (sessionId) => api.post(`/guardian/stop?session_id=${sessionId}`),
  getGuardianSession: (sessionId) => api.get(`/guardian/session/${sessionId}`),
  getGuardianActiveSessions: () => api.get('/guardian/sessions/active'),
  getGuardianHistory: () => api.get('/guardian/sessions/history'),
  getGuardianPolyline: (sessionId, limit = 1000) =>
    api.get(`/guardian/${sessionId}/polyline?limit=${limit}`),
  updateGuardianLocation: (payload) => api.post('/guardian/update-location', payload),
  acknowledgeGuardianSafety: (sessionId) => api.post(`/guardian/acknowledge-safety?session_id=${sessionId}`),
  // Predictive Danger Alerts
  evaluatePredictiveAlert: (payload) => api.post('/predictive-alert', payload),
  evaluatePredictiveAlertWithRoute: (payload) => api.post('/predictive-alert/with-alternative', payload),
  // Guardian Family Dashboard
  getGuardianLovedOnes: () => api.get('/guardian/dashboard/loved-ones'),
  getGuardianDashboardSessions: () => api.get('/guardian/dashboard/sessions'),
  getGuardianDashboardAlerts: (limit = 50) => api.get(`/guardian/dashboard/alerts?limit=${limit}`),
  getGuardianDashboardHistory: (limit = 20) => api.get(`/guardian/dashboard/history?limit=${limit}`),
  requestGuardianSafetyCheck: (sessionId) => api.post('/guardian/dashboard/request-check', { session_id: sessionId }),
  // Safety Score
  getLocationScore: (lat, lng) => api.get(`/safety-score/location?lat=${lat}&lng=${lng}`),
  getRouteScore: (origin, destination) => api.post('/safety-score/route', { origin, destination }),
  getJourneyScore: (sessionId) => api.get(`/safety-score/journey/${sessionId}`),
};
