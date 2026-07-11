import api from './api';

export const authService = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }),

  register: (data: { email: string; password: string; full_name: string; phone?: string }) =>
    api.post('/auth/register', data),

  getMe: () => api.get('/auth/me'),
};

export const safetyScoreService = {
  getLocationScore: (lat: number, lng: number) =>
    api.get('/safety-score/location', { params: { lat, lng } }),

  getRouteScore: (origin: { lat: number; lng: number }, destination: { lat: number; lng: number }) =>
    api.post('/safety-score/route', { origin, destination }),

  getJourneyScore: (sessionId: string) =>
    api.get(`/safety-score/journey/${sessionId}`),
};

export const guardianService = {
  startSession: (userId: string, location?: { lat: number; lng: number }) =>
    api.post('/guardian/start', {
      user_id: userId,
      location: location || { lat: 0, lng: 0 },
    }),

  stopSession: (sessionId: string) =>
    api.post('/guardian/stop', { session_id: sessionId }),

  updateLocation: (sessionId: string, lat: number, lng: number) =>
    api.post('/guardian/update-location', { session_id: sessionId, location: { lat, lng } }),

  getSession: (sessionId: string) =>
    api.get(`/guardian/session/${sessionId}`),

  listActive: () =>
    api.get('/guardian/sessions/active'),

  getHistory: () =>
    api.get('/guardian/sessions/history'),

  acknowledgeSafety: (sessionId: string) =>
    api.post('/guardian/acknowledge-safety', { session_id: sessionId }),

  // Step 7 — Journey polyline (historical GPS trail with quality metadata
  // for tri-color segmentation: good / degraded / offline).
  getPolyline: (sessionId: string, limit: number = 1000) =>
    api.get(`/guardian/${sessionId}/polyline`, { params: { limit } }),
};

export const guardianDashboardService = {
  getLovedOnes: () =>
    api.get('/guardian/dashboard/loved-ones'),

  getSessions: () =>
    api.get('/guardian/dashboard/sessions'),

  getAlerts: (limit?: number) =>
    api.get('/guardian/dashboard/alerts', { params: { limit } }),

  getHistory: (userId?: string) =>
    api.get('/guardian/dashboard/history', { params: { user_id: userId } }),

  requestCheck: (userId: string) =>
    api.post('/guardian/dashboard/request-check', { user_id: userId }),

  endSession: (sessionId: string) =>
    api.post(`/guardian/dashboard/end-session/${sessionId}`),

  acknowledgeAlert: (eventId: string) =>
    api.post('/guardian/dashboard/alert/acknowledge', { event_id: eventId }),

  getLiveRisk: () =>
    api.get('/guardian/live/risk'),
};

export const checkInService = {
  create: (childUserId: string) =>
    api.post(`/checkin/${childUserId}`),

  getPending: () =>
    api.get('/checkin/pending'),

  respond: (checkInId: string, response: 'safe' | 'help') =>
    api.post(`/checkin/${checkInId}/respond`, { response }),

  getStatus: (checkInId: string) =>
    api.get(`/checkin/status/${checkInId}`),

  getLatest: (childUserId: string) =>
    api.get(`/checkin/latest/${childUserId}`),
};

export const safeRouteService = {
  generateRoutes: (startLat: number, startLng: number, endLat: number, endLng: number) =>
    api.post('/safe-route', { origin: { lat: startLat, lng: startLng }, destination: { lat: endLat, lng: endLng } }),
};

export const predictiveAlertService = {
  evaluate: (lat: number, lng: number, speed?: number, heading?: number) =>
    api.post('/predictive-alert', { location: { lat, lng }, speed }),

  evaluateWithAlternative: (lat: number, lng: number, speed?: number, heading?: number) =>
    api.post('/predictive-alert/with-alternative', { location: { lat, lng }, speed }),
};

export const nightGuardianService = {
  start: (userId: string, destinationLat: number, destinationLng: number) =>
    api.post('/operator/night-guardian/start', { user_id: userId, destination_lat: destinationLat, destination_lng: destinationLng }),

  stop: (userId: string) =>
    api.post('/operator/night-guardian/stop', { user_id: userId }),

  getStatus: (userId: string) =>
    api.get('/operator/night-guardian/status', { params: { user_id: userId } }),

  updateLocation: (userId: string, lat: number, lng: number) =>
    api.post('/operator/night-guardian/update-location', { user_id: userId, lat, lng }),
};

export const pushService = {
  registerToken: (token: string, deviceId: string) =>
    api.post('/push/token', { token, device_id: deviceId }),
};

export const locationShareService = {
  createShare: (durationHours: number = 4) =>
    api.post('/location/share', { duration_hours: durationHours }),
};

export const childLinkService = {
  generateCode: () =>
    api.post('/child/generate-link-code'),
};

export const childHelpService = {
  requestHelp: (lat: number, lng: number, message?: string) =>
    api.post('/child/help-request', { lat, lng, message }),
};

export const guardianLinkService = {
  linkChild: (code: string) =>
    api.post('/guardian/link-child', { code }),
};

export const wearableService = {
  register: (deviceUid: string, deviceType: string = 'wearable') =>
    api.post('/wearable/register', { device_uid: deviceUid, device_type: deviceType }),

  bind: (deviceId: string, userId: string) =>
    api.post('/wearable/bind', { device_id: deviceId, user_id: userId }),

  sendEvent: (deviceId: string, event: {
    event_type: string;
    event_id?: string;
    payload?: Record<string, any>;
    client_timestamp?: string;
  }) =>
    api.post('/wearable/event', { device_id: deviceId, ...event }),

  heartbeat: (deviceId: string, battery?: number, rssi?: number) =>
    api.post('/wearable/heartbeat', { device_id: deviceId, battery, rssi }),

  getDevices: () =>
    api.get('/wearable/devices'),

  getAudit: (deviceId?: string, limit: number = 50) =>
    api.get('/wearable/audit', { params: { device_id: deviceId, limit } }),
};
