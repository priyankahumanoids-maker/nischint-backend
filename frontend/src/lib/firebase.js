import { initializeApp, getApps } from "firebase/app";
import { getMessaging, getToken, onMessage, isSupported } from "firebase/messaging";

const firebaseConfig = {
  apiKey: process.env.REACT_APP_FIREBASE_API_KEY,
  authDomain: process.env.REACT_APP_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.REACT_APP_FIREBASE_PROJECT_ID,
  storageBucket: process.env.REACT_APP_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.REACT_APP_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.REACT_APP_FIREBASE_APP_ID,
};

// Initialize Firebase app (singleton)
const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0];

let messagingInstance = null;

async function getMessagingInstance() {
  if (messagingInstance) return messagingInstance;
  const supported = await isSupported();
  if (!supported) {
    console.warn("[Firebase] Messaging not supported in this browser");
    return null;
  }
  messagingInstance = getMessaging(app);
  return messagingInstance;
}

export async function requestPushToken() {
  try {
    const messaging = await getMessagingInstance();
    if (!messaging) return null;

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      console.warn("[Firebase] Push permission denied");
      return null;
    }

    // Register the firebase-messaging service worker
    const registration = await navigator.serviceWorker.register("/firebase-messaging-sw.js");

    const token = await getToken(messaging, {
      vapidKey: process.env.REACT_APP_FIREBASE_VAPID_KEY,
      serviceWorkerRegistration: registration,
    });

    console.log("[Firebase] FCM token obtained");
    return token;
  } catch (err) {
    console.error("[Firebase] Token error:", err.message);
    return null;
  }
}

export function onForegroundMessage(callback) {
  // async init, then subscribe
  getMessagingInstance().then((messaging) => {
    if (messaging) {
      onMessage(messaging, (payload) => {
        callback(payload);
      });
    }
  });
  // Return noop unsub since onMessage doesn't return one in async case
  return () => {};
}
