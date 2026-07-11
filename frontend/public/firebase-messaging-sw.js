/* eslint-disable no-restricted-globals */
/* eslint-disable no-undef */

importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyAz3yJ2O-fPQAk9Ths_KGtAKtvv4AzjlEc",
  authDomain: "nischint-5f248.firebaseapp.com",
  projectId: "nischint-5f248",
  storageBucket: "nischint-5f248.firebasestorage.app",
  messagingSenderId: "228706516031",
  appId: "1:228706516031:web:8660d4328864906f098c8a",
});

const messaging = firebase.messaging();

// Tag-to-icon mapping for rich notifications
const TAG_ICONS = {
  "nischint-sos": "/icons/icon-192.png",
  "nischint-risk": "/icons/icon-192.png",
  "nischint-invite": "/icons/icon-192.png",
  "nischint-session": "/icons/icon-192.png",
  "nischint-incident": "/icons/icon-192.png",
};

messaging.onBackgroundMessage((payload) => {
  const notification = payload.notification || {};
  const data = payload.data || {};

  const tag = data.tag || "nischint-alert";
  const url = data.url || "/m/home";

  const options = {
    body: notification.body || data.body || "You have a new alert",
    icon: TAG_ICONS[tag] || "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: tag,
    requireInteraction: tag === "nischint-sos",
    vibrate: tag === "nischint-sos" ? [200, 100, 200, 100, 200] : [100, 50, 100],
    data: { url },
    actions: tag === "nischint-sos"
      ? [{ action: "view", title: "View Now" }]
      : [{ action: "open", title: "Open" }],
  };

  self.registration.showNotification(
    notification.title || data.title || "Nischint Safety",
    options
  );
});

// Handle notification click — navigate to the target URL
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const url = event.notification.data?.url || "/m/home";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Focus existing window if open
      for (const client of clients) {
        if (client.url.includes("/m/") && "focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      // Open new window
      return self.clients.openWindow(url);
    })
  );
});
