import api from './api';

export const emergencyService = {
  triggerSOS: (lat: number, lng: number, triggerSource: string, cancelPin?: string, deviceMetadata?: object) =>
    api.post('/emergency/silent-sos', {
      lat, lng,
      trigger_source: triggerSource,
      cancel_pin: cancelPin,
      device_metadata: deviceMetadata,
    }),

  updateLocation: (eventId: string, lat: number, lng: number) =>
    api.post('/emergency/location-update', { event_id: eventId, lat, lng }),

  cancel: (eventId: string, cancelPin: string) =>
    api.post('/emergency/cancel', { event_id: eventId, cancel_pin: cancelPin }),

  smsFallback: (lat: number, lng: number, triggerSource: string = 'offline_fallback') =>
    api.post('/emergency/sms-fallback', { lat, lng, trigger_source: triggerSource }),

  geofenceLocationUpdate: (lat: number, lng: number) =>
    api.post('/geofence/location-update', { lat, lng }),

  resolve: (eventId: string) =>
    api.post('/emergency/resolve', { event_id: eventId }),

  getActive: () =>
    api.get('/emergency/active'),

  getStatus: (eventId: string) =>
    api.get(`/emergency/status/${eventId}`),
};
