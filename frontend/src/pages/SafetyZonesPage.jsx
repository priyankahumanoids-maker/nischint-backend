// Safety Zones Page — consumer-grade, demo-ready UX.
// Google-Maps-style: search + click-to-place + radius slider + emotional copy.
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Circle, useMap, useMapEvents } from 'react-leaflet';
import { MapPin, Shield, Plus, Radio, AlertCircle, RefreshCw, Search, Home, Briefcase, Hospital, X, Heart } from 'lucide-react';
import { toast } from 'sonner';
import api from '../api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Slider } from '../components/ui/slider';
import { Badge } from '../components/ui/badge';
import 'leaflet/dist/leaflet.css';

// ── Emotional copy (per spec) ──
const STATE_CONFIG = {
  safe:      { label: 'All Safe',              tint: 'bg-emerald-100 text-emerald-700 border-emerald-200', dot: 'bg-emerald-500',             circle: '#10B981' },
  moving:    { label: 'Moving Safely',         tint: 'bg-amber-100 text-amber-700 border-amber-200',       dot: 'bg-amber-500',               circle: '#F59E0B' },
  warning:   { label: 'Near Boundary',         tint: 'bg-orange-100 text-orange-700 border-orange-200',    dot: 'bg-orange-500',              circle: '#F97316' },
  breach:    { label: 'Outside Safe Care Circle', tint: 'bg-red-100 text-red-700 border-red-200',          dot: 'bg-red-500 animate-pulse',   circle: '#EF4444' },
  recovery:  { label: 'Back Safe',             tint: 'bg-emerald-100 text-emerald-700 border-emerald-200', dot: 'bg-emerald-500',             circle: '#10B981' },
  unknown:   { label: 'Waiting for signal…',   tint: 'bg-slate-100 text-slate-700 border-slate-200',       dot: 'bg-slate-400',               circle: '#10B981' },
  no_zone:   { label: 'No Care Circle Yet',    tint: 'bg-slate-100 text-slate-600 border-slate-200',       dot: 'bg-slate-300',               circle: '#10B981' },
};

function humanDistance(m) {
  if (!m && m !== 0) return '';
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

// ── Leaflet helpers ──
function FlyTo({ lat, lng, zoom }) {
  const map = useMap();
  useEffect(() => { if (lat && lng) map.flyTo([lat, lng], zoom || 14, { duration: 0.8 }); }, [lat, lng, zoom, map]);
  return null;
}

function ClickCapture({ onPick }) {
  useMapEvents({
    click(e) { onPick(e.latlng.lat, e.latlng.lng); },
  });
  return null;
}

// ── Reverse geocode (Nominatim — no API key required) ──
async function reverseGeocode(lat, lng) {
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=14`, {
      headers: { 'Accept-Language': 'en' },
    });
    const j = await res.json();
    return j?.display_name?.split(',').slice(0, 2).join(',').trim() || null;
  } catch { return null; }
}

// ── Nominatim search (geocode) ──
async function searchPlaces(query) {
  if (!query || query.length < 3) return [];
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=6&countrycodes=in`,
      { headers: { 'Accept-Language': 'en' } }
    );
    const arr = await res.json();
    return (arr || []).map(p => ({
      name: p.display_name.split(',').slice(0, 2).join(','),
      full: p.display_name,
      lat: parseFloat(p.lat),
      lng: parseFloat(p.lon),
    }));
  } catch { return []; }
}

const SafetyZonesPage = () => {
  const [users, setUsers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showEditor, setShowEditor] = useState(false);

  const [editorCenter, setEditorCenter] = useState({ lat: 19.076, lng: 72.877 });
  const [editorRadius, setEditorRadius] = useState(3000);
  const [editorName, setEditorName] = useState('Home Care Zone');
  const [placeLabel, setPlaceLabel] = useState(null);
  const [saving, setSaving] = useState(false);
  const [savedPulse, setSavedPulse] = useState(false);

  // ── Care Locations (saved pins) ──
  const [pins, setPins] = useState([]);
  const [savingPin, setSavingPin] = useState(false);
  const MAX_PINS = 5;

  const loadPins = useCallback(async () => {
    if (!selected) return;
    try {
      const { data } = await api.get(`/geofence/pins/${selected}`);
      setPins(data?.pins || []);
    } catch {
      setPins([]);
    }
  }, [selected]);
  useEffect(() => { loadPins(); }, [loadPins]);

  // ── Tap a pin → instant fly-to + pre-fill zone name ──
  const applyPin = async (p) => {
    setEditorCenter({ lat: p.lat, lng: p.lng });
    setEditorName(`${p.name} Care Zone`);
    const pl = await reverseGeocode(p.lat, p.lng);
    setPlaceLabel(pl || p.name);
    toast.success(`Using your saved ${p.name} location`);
  };

  // ── Save current selection as a pin ──
  const saveCurrentAsPin = async () => {
    if (!selected) return;
    const niceName = (editorName || '').replace(/\s*Care\s*Zone\s*$/i, '').trim() || 'Custom';
    const type = /home/i.test(niceName) ? 'home'
      : /office/i.test(niceName) ? 'office'
      : /school/i.test(niceName) ? 'school'
      : /hospital|clinic|medical/i.test(niceName) ? 'hospital'
      : 'custom';
    setSavingPin(true);
    try {
      const { data } = await api.post('/geofence/pins/add', {
        user_id: selected,
        pin: { type, name: niceName, lat: editorCenter.lat, lng: editorCenter.lng },
      });
      setPins(data?.pins || []);
      toast.success(`${niceName} location saved for quicker care setup 💚`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not save care location');
    } finally {
      setSavingPin(false);
    }
  };

  // ── Search state ──
  const [search, setSearch] = useState('');
  const [results, setResults] = useState([]);
  const [showResults, setShowResults] = useState(false);
  const searchTimer = useRef();

  // ── Load users ──
  const loadUsers = useCallback(async () => {
    try {
      const { data } = await api.get('/dashboard/family-users');
      const protectedUsers = (data || []).filter(u => u.kind === 'child' || u.kind === 'woman' || u.kind === 'senior' || u.kind === 'elderly' || u.role);
      setUsers(protectedUsers);
      if (protectedUsers.length > 0 && !selected) setSelected(protectedUsers[0].id);
    } catch { toast.error('Could not load your loved ones'); }
    finally { setLoading(false); }
  }, [selected]);
  useEffect(() => { loadUsers(); }, [loadUsers]);

  // ── Load status ──
  const loadStatus = useCallback(async () => {
    if (!selected) return;
    try {
      const { data } = await api.get(`/geofence/status/${selected}`);
      setStatus(data);
    } catch { setStatus({ state: 'no_zone', zone: null }); }
  }, [selected]);
  useEffect(() => {
    loadStatus();
    const poll = setInterval(loadStatus, 10_000);
    return () => clearInterval(poll);
  }, [loadStatus]);

  // ── Search debounce ──
  useEffect(() => {
    clearTimeout(searchTimer.current);
    if (!search || search.length < 3) { setResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      const r = await searchPlaces(search);
      setResults(r);
      setShowResults(true);
    }, 350);
    return () => clearTimeout(searchTimer.current);
  }, [search]);

  // ── Open editor pre-populated with current values ──
  const openEditor = async () => {
    const existingZone = status?.zone;
    if (existingZone) {
      setEditorCenter({ lat: existingZone.center_lat, lng: existingZone.center_lng });
      setEditorRadius(existingZone.radius_m || 3000);
      setEditorName(existingZone.name || 'Home Care Zone');
      const pl = await reverseGeocode(existingZone.center_lat, existingZone.center_lng);
      if (pl) setPlaceLabel(pl);
    } else if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(async (pos) => {
        const { latitude, longitude } = pos.coords;
        setEditorCenter({ lat: latitude, lng: longitude });
        const pl = await reverseGeocode(latitude, longitude);
        if (pl) setPlaceLabel(pl);
      });
    }
    setShowEditor(true);
  };

  // ── Select a search result ──
  const pickPlace = async (p) => {
    setEditorCenter({ lat: p.lat, lng: p.lng });
    setPlaceLabel(p.name);
    setSearch(p.name);
    setShowResults(false);
  };

  // ── Click map to place pin ──
  const pickLocation = async (lat, lng) => {
    setEditorCenter({ lat, lng });
    const pl = await reverseGeocode(lat, lng);
    if (pl) setPlaceLabel(pl);
  };

  // ── Quick presets — if a pin of this type exists, use it (one-tap); else fall back to current GPS ──
  const usePreset = async (labelName) => {
    const type = /home/i.test(labelName) ? 'home'
      : /office/i.test(labelName) ? 'office'
      : /school/i.test(labelName) ? 'school'
      : /hospital|clinic/i.test(labelName) ? 'hospital'
      : 'custom';
    // 1. Try saved pin first
    const savedMatch = (pins || []).find(p => (p.type || '').toLowerCase() === type) ||
                       (pins || []).find(p => (p.name || '').toLowerCase().includes(type));
    if (savedMatch) {
      await applyPin(savedMatch);
      setEditorName(`${savedMatch.name} Care Zone`);
      return;
    }
    // 2. Fallback: use current GPS
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(async (pos) => {
        setEditorCenter({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        const pl = await reverseGeocode(pos.coords.latitude, pos.coords.longitude);
        setPlaceLabel(pl);
        setEditorName(labelName);
      });
    } else { setEditorName(labelName); }
  };

  // ── Save ──
  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await api.post('/geofence/zone-for-user', {
        user_id: selected,
        center_lat: editorCenter.lat,
        center_lng: editorCenter.lng,
        radius_m: editorRadius,
        name: editorName,
      });
      const nm = users.find(u => u.id === selected)?.full_name || 'Your loved one';
      toast.success(`${nm} is now protected within a ${(editorRadius / 1000).toFixed(1)} km care circle 💚`);
      setSavedPulse(true);
      setTimeout(() => setSavedPulse(false), 1200);
      setShowEditor(false);
      await loadStatus();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not save zone');
    } finally { setSaving(false); }
  };

  const selectedUser = users.find(u => u.id === selected);
  const zone = status?.zone
    ? status.zone
    : (status?.zone_id ? { id: status.zone_id, name: status.zone_name, center_lat: status.center_lat, center_lng: status.center_lng, radius_m: status.radius_m } : null);
  const livePoint = status?.lat && status?.lng ? { lat: status.lat, lng: status.lng } : null;
  const stateKey = status?.state || (zone ? 'unknown' : 'no_zone');
  const cfg = STATE_CONFIG[stateKey] || STATE_CONFIG.unknown;
  const nameForMsgs = selectedUser?.full_name || 'your loved one';

  return (
    <div className="space-y-6" data-testid="safety-zones-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <Shield className="w-6 h-6 text-teal-600" /> Safety Zones
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            A care circle around each loved one — not surveillance, just peace of mind.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={loadStatus} data-testid="refresh-status-btn">
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
          <Button
            onClick={openEditor}
            className="bg-teal-600 hover:bg-teal-700"
            disabled={!selected}
            data-testid="create-zone-btn"
          >
            <Heart className="w-4 h-4 mr-2" /> {zone ? 'Update Care Zone' : 'Set Care Zone'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* LEFT — loved ones */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Your Loved Ones</CardTitle>
            <CardDescription>{users.length} under your care</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {loading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : users.length === 0 ? (
              <p className="text-sm text-slate-500">No loved ones linked yet.</p>
            ) : users.map(u => (
              <button
                key={u.id}
                onClick={() => setSelected(u.id)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${selected === u.id ? 'border-teal-500 bg-teal-50' : 'border-slate-200 hover:bg-slate-50'}`}
                data-testid={`zone-user-${u.id}`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-800 truncate">{u.full_name}</span>
                  {selected === u.id && (
                    <Badge className={`${cfg.tint} border text-xs ml-2 shrink-0`}>
                      {cfg.label}
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-slate-500 capitalize mt-0.5">{u.kind || u.role || 'loved one'}</p>
              </button>
            ))}
          </CardContent>
        </Card>

        {/* RIGHT — status + map */}
        <Card className={`lg:col-span-2 transition-shadow ${savedPulse ? 'ring-2 ring-teal-400 ring-offset-2' : ''}`}>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Radio className={`w-4 h-4 ${stateKey === 'breach' ? 'text-red-500' : 'text-teal-600'}`} />
              {selectedUser?.full_name || 'Select a loved one'}
              {zone && (
                <span className="inline-flex items-center gap-1 ml-auto px-2 py-0.5 rounded-full bg-teal-50 border border-teal-200 text-[10px] font-bold text-teal-700 tracking-wider">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" /> LIVE
                </span>
              )}
            </CardTitle>
            <CardDescription data-testid="zone-status-message">
              {status?.message || `Follow ${nameForMsgs}'s journey gently — we'll let you know if anything changes.`}
            </CardDescription>
          </CardHeader>

          <CardContent>
            {!zone && (
              <div className="p-6 bg-slate-50 rounded-lg border border-dashed text-center">
                <MapPin className="w-10 h-10 text-slate-400 mx-auto mb-2" />
                <p className="text-slate-700 font-medium">No care circle set yet</p>
                <p className="text-sm text-slate-500 mt-1">
                  Draw a gentle care circle around {nameForMsgs}. Default is 3 km.
                </p>
                <Button onClick={openEditor} className="mt-3 bg-teal-600 hover:bg-teal-700" disabled={!selected}>
                  <Heart className="w-4 h-4 mr-2" /> Set Care Zone
                </Button>
              </div>
            )}

            {zone && (
              <>
                <div className="flex items-center gap-3 flex-wrap mb-3">
                  <div className={`w-3 h-3 rounded-full ${cfg.dot}`} />
                  <Badge className={`${cfg.tint} border`} data-testid="zone-state-badge">
                    {cfg.label}
                  </Badge>
                  <span className="text-sm text-slate-600">
                    Radius: <b>{(zone.radius_m / 1000).toFixed(1)} km</b>
                  </span>
                  {typeof status?.distance_m === 'number' && (
                    <span className="text-sm text-slate-600">
                      <b>{humanDistance(status.distance_m)}</b> away from the care zone
                    </span>
                  )}
                </div>

                <div className="h-[420px] rounded-lg overflow-hidden border border-slate-200">
                  <MapContainer
                    center={[zone.center_lat, zone.center_lng]}
                    zoom={13}
                    style={{ height: '100%', width: '100%' }}
                    scrollWheelZoom
                  >
                    <TileLayer
                      url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
                      attribution='&copy; OpenStreetMap &copy; CARTO'
                    />
                    <Circle
                      center={[zone.center_lat, zone.center_lng]}
                      radius={zone.radius_m}
                      pathOptions={{
                        color: cfg.circle,
                        fillColor: cfg.circle,
                        fillOpacity: 0.15,
                        weight: 2,
                      }}
                    />
                    <Marker position={[zone.center_lat, zone.center_lng]} />
                    {livePoint && <Marker position={[livePoint.lat, livePoint.lng]} />}
                  </MapContainer>
                </div>

                <p className="mt-3 text-xs text-slate-500">
                  {stateKey === 'breach' ? (
                    <><AlertCircle className="w-3.5 h-3.5 text-red-500 inline mr-1" /> Family alerted — support circle informed.</>
                  ) : (
                    <>Care updates every 10 seconds.</>
                  )}
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ─── CUSTOM MODAL OVERLAY (fixes z-index bug vs Leaflet) ─── */}
      {showEditor && (
        <ZoneEditorModal
          onClose={() => setShowEditor(false)}
          name={editorName}
          onName={setEditorName}
          center={editorCenter}
          onPickLocation={pickLocation}
          radius={editorRadius}
          onRadius={setEditorRadius}
          placeLabel={placeLabel}
          search={search}
          onSearch={setSearch}
          results={results}
          showResults={showResults}
          onPickPlace={pickPlace}
          onHideResults={() => setShowResults(false)}
          onPreset={usePreset}
          onSave={handleSave}
          saving={saving}
          nameForMsgs={nameForMsgs}
          pins={pins}
          onApplyPin={applyPin}
          onSaveCurrentAsPin={saveCurrentAsPin}
          savingPin={savingPin}
          maxPins={MAX_PINS}
        />
      )}
    </div>
  );
};

// ═════════════════════════════════════════════════════════════════════
// Zone Editor Modal — fixed-position, z-[9999], blocks map interactions
// ═════════════════════════════════════════════════════════════════════
function ZoneEditorModal(props) {
  // Lock page scroll while modal is open
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  const {
    onClose, name, onName, center, onPickLocation, radius, onRadius, placeLabel,
    search, onSearch, results, showResults, onPickPlace, onHideResults,
    onPreset, onSave, saving, nameForMsgs,
    pins, onApplyPin, onSaveCurrentAsPin, savingPin, maxPins,
  } = props;

  const PIN_ICONS = { home: Home, office: Briefcase, school: Briefcase, hospital: Hospital, custom: MapPin };
  const atMax = (pins?.length || 0) >= (maxPins || 5);
  const hasPins = (pins?.length || 0) > 0;

  return (
    <div
      className="fixed inset-0 bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4"
      style={{ zIndex: 9999 }}
      onClick={onClose}
      data-testid="zone-editor-backdrop"
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[92vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
        data-testid="zone-editor-modal"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
          <div>
            <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <Heart className="w-5 h-5 text-teal-600 fill-teal-100" /> Care Zone for {nameForMsgs}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              A gentle circle of peace around them.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-500"
            aria-label="Close"
            data-testid="zone-editor-close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto px-6 py-5 space-y-4 flex-1">
          {/* ── Care Locations (saved pins) — one-tap setup ── */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                ❤️ Your care locations
              </label>
              <span className="text-[10px] text-slate-400">
                {hasPins ? `${pins.length}/${maxPins}` : 'Save frequent places for one-tap setup'}
              </span>
            </div>
            {hasPins ? (
              <div className="flex items-center gap-2 flex-wrap mt-2" data-testid="care-pins-row">
                {pins.map((p, i) => {
                  const Icon = PIN_ICONS[p.type] || MapPin;
                  return (
                    <button
                      key={`${p.name}-${i}`}
                      onClick={() => onApplyPin(p)}
                      className="group flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-teal-50 hover:bg-teal-100 border border-teal-200 text-sm text-teal-800 transition-all active:scale-95"
                      data-testid={`care-pin-${p.type}-${i}`}
                      title={`Use your saved ${p.name} location`}
                    >
                      <Icon className="w-3.5 h-3.5 text-teal-600" />
                      <span className="font-medium">{p.name}</span>
                    </button>
                  );
                })}
                <button
                  onClick={onSaveCurrentAsPin}
                  disabled={savingPin || atMax}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-amber-50 hover:bg-amber-100 border border-amber-200 text-sm text-amber-800 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
                  title={atMax ? `Max ${maxPins} pins saved — delete one to add more` : 'Save this location for quick re-use'}
                  data-testid="save-current-as-pin-btn"
                >
                  <span className="text-sm">⭐</span>
                  <span className="font-medium">{savingPin ? 'Saving…' : 'Save this'}</span>
                </button>
              </div>
            ) : (
              <div className="mt-2 p-3 rounded-lg bg-gradient-to-r from-teal-50 to-emerald-50 border border-teal-100 flex items-center justify-between gap-3">
                <p className="text-sm text-slate-600 leading-snug">
                  Save frequent places like Home or Office for quicker setup.
                </p>
                <button
                  onClick={onSaveCurrentAsPin}
                  disabled={savingPin}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white hover:bg-amber-50 border border-amber-200 text-sm text-amber-800 transition-all active:scale-95 whitespace-nowrap shrink-0"
                  data-testid="save-current-as-pin-btn-empty"
                >
                  <span>⭐</span>
                  <span className="font-medium">{savingPin ? 'Saving…' : 'Save this location'}</span>
                </button>
              </div>
            )}
          </div>

          {/* Search */}
          <div className="relative">
            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Search a place</label>
            <div className="relative mt-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
              <Input
                value={search}
                onChange={(e) => onSearch(e.target.value)}
                placeholder="Andheri West, Apollo Hospital, Bandra Office…"
                className="pl-9"
                data-testid="zone-search-input"
              />
            </div>
            {showResults && results.length > 0 && (
              <div className="absolute z-10 left-0 right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-56 overflow-y-auto">
                {results.map((r, i) => (
                  <button
                    key={i}
                    onClick={() => onPickPlace(r)}
                    className="w-full text-left px-3 py-2 hover:bg-teal-50 border-b border-slate-100 last:border-0"
                    data-testid={`zone-search-result-${i}`}
                  >
                    <div className="text-sm font-medium text-slate-800 truncate flex items-center gap-1.5">
                      <MapPin className="w-3 h-3 text-teal-500 shrink-0" />
                      {r.name}
                    </div>
                    <div className="text-xs text-slate-400 truncate">{r.full}</div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Presets — shown only when user hasn't saved pins yet (starter presets) */}
          {!hasPins && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider mr-1">Starter presets:</span>
              <button onClick={() => onPreset('Home Care Zone')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-50 hover:bg-teal-50 border border-slate-200 text-sm text-slate-700 transition-colors"
                data-testid="preset-home">
                <Home className="w-3.5 h-3.5 text-teal-600" /> Home
              </button>
              <button onClick={() => onPreset('Office Care Zone')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-50 hover:bg-teal-50 border border-slate-200 text-sm text-slate-700 transition-colors"
                data-testid="preset-office">
                <Briefcase className="w-3.5 h-3.5 text-teal-600" /> Office
              </button>
              <button onClick={() => onPreset('Hospital Care Zone')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-50 hover:bg-teal-50 border border-slate-200 text-sm text-slate-700 transition-colors"
                data-testid="preset-hospital">
                <Hospital className="w-3.5 h-3.5 text-teal-600" /> Hospital
              </button>
            </div>
          )}

          {/* Zone name */}
          <div>
            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Zone name</label>
            <Input
              value={name}
              onChange={(e) => onName(e.target.value)}
              placeholder="Home Care Zone"
              className="mt-1"
              data-testid="zone-name-input"
              onClick={onHideResults}
            />
          </div>

          {/* Mini-map */}
          <div>
            <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              Center on map — tap anywhere to place
            </label>
            {placeLabel && (
              <div className="mt-1 text-xs text-slate-500 flex items-center gap-1">
                <MapPin className="w-3 h-3" /> {placeLabel}
              </div>
            )}
            <div className="mt-2 h-56 rounded-lg overflow-hidden border border-slate-200">
              <MapContainer
                center={[center.lat, center.lng]}
                zoom={13}
                style={{ height: '100%', width: '100%' }}
                scrollWheelZoom
              >
                <TileLayer
                  url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
                  attribution='&copy; OpenStreetMap &copy; CARTO'
                />
                <ClickCapture onPick={onPickLocation} />
                <FlyTo lat={center.lat} lng={center.lng} zoom={14} />
                <Circle
                  center={[center.lat, center.lng]}
                  radius={radius}
                  pathOptions={{ color: '#10B981', fillColor: '#10B981', fillOpacity: 0.18, weight: 2 }}
                />
                <Marker position={[center.lat, center.lng]} />
              </MapContainer>
            </div>
          </div>

          {/* Radius: slider + numeric */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Care circle radius</label>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={500}
                  max={10000}
                  step={100}
                  value={radius}
                  onChange={(e) => onRadius(Math.max(500, Math.min(10000, Number(e.target.value) || 0)))}
                  className="w-24 text-sm"
                  data-testid="zone-radius-input"
                />
                <span className="text-xs text-slate-500">m</span>
                <span className="text-sm font-semibold text-teal-700 w-16 text-right">{(radius / 1000).toFixed(1)} km</span>
              </div>
            </div>
            <Slider
              min={500}
              max={10000}
              step={100}
              value={[radius]}
              onValueChange={(v) => onRadius(v[0])}
              className="mt-3"
              data-testid="zone-radius-slider"
            />
            <div className="flex justify-between text-xs text-slate-400 mt-1">
              <span>0.5 km</span>
              <span>10 km</span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-100 bg-slate-50 shrink-0">
          <Button variant="outline" onClick={onClose} disabled={saving} data-testid="zone-cancel-btn">Cancel</Button>
          <Button onClick={onSave} disabled={saving} className="bg-teal-600 hover:bg-teal-700" data-testid="zone-save-btn">
            <Heart className={`w-4 h-4 mr-2 ${saving ? 'animate-pulse' : ''}`} />
            {saving ? 'Saving…' : 'Save Care Zone'}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default SafetyZonesPage;
