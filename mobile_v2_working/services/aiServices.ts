// Mobile API client for AI Services
// Maps to /api/ai/* backend endpoints

import api from './api';

export const aiServices = {
  /** Life pattern analysis for family member */
  getLifePattern: (deviceId?: string) =>
    api.get('/ai/life-pattern', { params: deviceId ? { device_id: deviceId } : undefined }),

  /** Digital twin behavioural profile */
  getDigitalTwin: (deviceId?: string) =>
    api.get('/ai/digital-twin', { params: deviceId ? { device_id: deviceId } : undefined }),

  /** Predicted risk for next 24h */
  getRiskForecast: (deviceId?: string) =>
    api.get('/ai/risk-forecast', { params: deviceId ? { device_id: deviceId } : undefined }),

  /** Environmental conditions at location */
  getEnvironmentRisk: (lat: number, lng: number) =>
    api.get('/ai/environment-risk', { params: { lat, lng } }),

  /** Behavioral anomaly detection */
  getBehaviorAnalysis: (deviceId?: string) =>
    api.get('/ai/behavior-analysis', { params: deviceId ? { device_id: deviceId } : undefined }),

  /** Digital twin evolution history */
  getTwinEvolution: (deviceId?: string) =>
    api.get('/ai/twin-evolution', { params: deviceId ? { device_id: deviceId } : undefined }),

  /** Local safety hotspot trends */
  getHotspotTrends: (lat: number, lng: number, radiusKm = 5) =>
    api.get('/ai/hotspot-trends', { params: { lat, lng, radius_km: radiusKm } }),

  /** Compact AI summary across all family members */
  getFamilySummary: () =>
    api.get('/ai/family-summary'),
};
