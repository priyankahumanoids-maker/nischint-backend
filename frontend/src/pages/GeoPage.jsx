/**
 * GeoPage.jsx (FIXED)
 */

import { useEffect } from "react";
import { useParams, Navigate } from "react-router-dom";
import { geoPages } from "../data/geoPages";

/* ── page-view tracker ─────────────────────────────────────────── */
function track(slug) {
  fetch("/api/blog/track", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug }),
  }).catch(() => {});
}

/* ── head updater ──────────────────────────────────────────────── */
function updateHead({ title, description, canonical, city }) {
  document.title = title;

  const setMeta = (sel, attr, val) => {
    let el = document.querySelector(sel);
    if (!el) {
      el = document.createElement("meta");
      document.head.appendChild(el);
    }
    el.setAttribute(attr, val);
  };

  setMeta('meta[name="description"]', "content", description);
  setMeta('meta[property="og:title"]', "content", title);
  setMeta('meta[property="og:description"]', "content", description);
  setMeta('meta[property="og:url"]', "content", canonical);
  setMeta('meta[name="geo.placename"]', "content", city);

  let canon = document.querySelector('link[rel="canonical"]');
  if (!canon) {
    canon = document.createElement("link");
    canon.rel = "canonical";
    document.head.appendChild(canon);
  }
  canon.href = canonical;
}

/* ── feature map by pageType ───────────────────────────────────── */
const PAGE_CONFIG = {
  women: {
    headline: (city) => `Women's Safety App in ${city}`,
    subhead: (city) =>
      `AI-powered protection for women in ${city} — voice distress detection, silent SOS, and instant guardian alerts.`,
    features: [
      "Voice distress detection",
      "Silent SOS trigger",
      "Live GPS tracking",
      "Instant guardian alerts",
      "Safe route suggestions",
    ],
    color: "#c0392b",
    persona: "women",
    internalLink: "/women-safety-app",
    internalLabel: "See all women's safety features",
  },
  kids: {
    headline: (city) => `Kids Safety App in ${city}`,
    subhead: (city) =>
      `Track and protect your child in ${city} with GPS, geofencing, and AI safety alerts.`,
    features: [
      "Real-time GPS tracking",
      "Geofence alerts",
      "School route monitoring",
      "Panic button",
      "AI anomaly detection",
    ],
    color: "#1a6fa8",
    persona: "children",
    internalLink: "/kids-safety-app",
    internalLabel: "See all kids safety features",
  },
  family: {
    headline: (city) => `Family Safety App in ${city}`,
    subhead: (city) =>
      `Protect your entire family in ${city} with live tracking, emergency SOS, and AI-powered alerts.`,
    features: [
      "Family location sharing",
      "Emergency SOS",
      "Elderly monitoring",
      "AI risk detection",
      "Guardian network alerts",
    ],
    color: "#1a7a4a",
    persona: "families",
    internalLink: "/family-safety-app",
    internalLabel: "See all family safety features",
  },
};

export default function GeoPage() {
  const { slug } = useParams();
  const page = geoPages.find((p) => p.slug === slug);

  // ✅ FIX: Hook always called (no conditional)
  useEffect(() => {
    if (!page) return;
    updateHead(page);
    track(page.slug);
  }, [page]);

  // Redirect if page not found
  if (!page) return <Navigate to="/" replace />;

  const config = PAGE_CONFIG[page.pageType] || PAGE_CONFIG.women;

  return (
    <>
      <div className="geo-page">
        {/* Breadcrumb */}
        <nav className="breadcrumb">
          <a href="/">Home</a> /{" "}
          <a href={config.internalLink}>
            {page.pageType.charAt(0).toUpperCase() +
              page.pageType.slice(1)}{" "}
            Safety
          </a>{" "}
          / <span>{page.city}</span>
        </nav>

        {/* Hero */}
        <header className="geo-hero">
          <div className="geo-hero-inner">
            <p className="geo-eyebrow">
              {page.city}, {page.state} · AI Safety Platform
            </p>
            <h1 className="geo-h1">
              {config.headline(page.city)}
            </h1>
            <p className="geo-subhead">
              {config.subhead(page.city)}
            </p>
            <p className="geo-def">
              NISCHINT is an AI-powered personal safety platform designed
              for {config.persona} in India — including {page.city}.
            </p>
          </div>
        </header>

        {/* Features */}
        <section className="geo-section">
          <div className="geo-inner">
            <h2 className="geo-h2">
              Key features for {page.city}
            </h2>
            <ul className="geo-feature-list">
              {config.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        </section>

        {/* CTA */}
        <section className="geo-cta">
          <div className="geo-cta-inner">
            <h2>Stay safe in {page.city}.</h2>
            <a href="/" className="geo-btn">
              Download NISCHINT
            </a>
          </div>
        </section>
      </div>
    </>
  );
}