/**
 * NISCHINT — Persistent Event Store (Web)
 * IndexedDB-backed queue. Events survive page refresh, crashes, offline periods.
 * Flow: event → save to IDB → add to sync queue → try send → mark synced
 */

const DB_NAME = "nischint_journey";
const DB_VERSION = 1;
const STORE_EVENTS = "events";
const STORE_SESSION = "session";

let _db = null;

function openDB() {
  if (_db) return Promise.resolve(_db);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_EVENTS)) {
        const store = db.createObjectStore(STORE_EVENTS, { keyPath: "id" });
        store.createIndex("status", "status", { unique: false });
        store.createIndex("type", "type", { unique: false });
        store.createIndex("createdAt", "createdAt", { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_SESSION)) {
        db.createObjectStore(STORE_SESSION, { keyPath: "key" });
      }
    };
    req.onsuccess = (e) => { _db = e.target.result; resolve(_db); };
    req.onerror = () => reject(req.error);
  });
}

// ── EVENT OPERATIONS ──

export async function saveEvent(event) {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_EVENTS, "readwrite");
    tx.objectStore(STORE_EVENTS).put({ ...event, status: "pending" });
    return true;
  } catch { return false; }
}

export async function getPendingEvents(limit = 10) {
  try {
    const db = await openDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_EVENTS, "readonly");
      const idx = tx.objectStore(STORE_EVENTS).index("status");
      const req = idx.getAll("pending");
      req.onsuccess = () => {
        const all = req.result || [];
        // Sort: high priority first, then oldest first
        all.sort((a, b) => {
          if (a.priority === "high" && b.priority !== "high") return -1;
          if (b.priority === "high" && a.priority !== "high") return 1;
          return a.createdAt - b.createdAt;
        });
        resolve(all.slice(0, limit));
      };
      req.onerror = () => resolve([]);
    });
  } catch { return []; }
}

export async function markEventsSynced(ids) {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_EVENTS, "readwrite");
    const store = tx.objectStore(STORE_EVENTS);
    for (const id of ids) {
      const req = store.get(id);
      req.onsuccess = () => {
        if (req.result) {
          store.put({ ...req.result, status: "synced", syncedAt: Date.now() });
        }
      };
    }
    return true;
  } catch { return false; }
}

export async function markEventFailed(id) {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_EVENTS, "readwrite");
    const store = tx.objectStore(STORE_EVENTS);
    const req = store.get(id);
    req.onsuccess = () => {
      if (req.result) {
        const evt = req.result;
        evt.attempts = (evt.attempts || 0) + 1;
        evt.lastAttemptAt = Date.now();
        // Keep as pending if under max attempts, else mark failed
        evt.status = evt.attempts >= 5 ? "failed" : "pending";
        store.put(evt);
      }
    };
    return true;
  } catch { return false; }
}

export async function getEventCount() {
  try {
    const db = await openDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_EVENTS, "readonly");
      const req = tx.objectStore(STORE_EVENTS).count();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(0);
    });
  } catch { return 0; }
}

// Clean old synced events (keep last 200)
export async function pruneOldEvents() {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_EVENTS, "readwrite");
    const store = tx.objectStore(STORE_EVENTS);
    const idx = store.index("status");
    const req = idx.getAll("synced");
    req.onsuccess = () => {
      const synced = req.result || [];
      if (synced.length > 200) {
        synced.sort((a, b) => a.createdAt - b.createdAt);
        const toDelete = synced.slice(0, synced.length - 200);
        for (const evt of toDelete) store.delete(evt.id);
      }
    };
  } catch { /* ignore */ }
}

// ── SESSION PERSISTENCE ──

export async function saveSession(session) {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_SESSION, "readwrite");
    tx.objectStore(STORE_SESSION).put({ key: "current", ...session });
    return true;
  } catch { return false; }
}

export async function loadSession() {
  try {
    const db = await openDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_SESSION, "readonly");
      const req = tx.objectStore(STORE_SESSION).get("current");
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => resolve(null);
    });
  } catch { return null; }
}
