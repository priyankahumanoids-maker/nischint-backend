import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Shield, Download, FileJson, Loader2,
  Database, MicOff, VideoOff, ScanFace, MapPin, Mail, Server,
} from 'lucide-react';
import api from '../../api';

/**
 * DPDP §11 Data Principal portal.
 *
 * Fetches GET /api/privacy/me (JSON) on mount for the summary view,
 * and exposes two download CTAs that hit the same endpoint with
 * ?format=pdf / ?format=json and trigger a file download.
 */
export default function MobilePrivacy() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(null); // 'pdf' | 'json' | null

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get('/privacy/me');
        setSummary(res.data);
      } catch (e) {
        setError(e.response?.data?.detail || e.message || 'Failed to load privacy summary');
      }
      setLoading(false);
    })();
  }, []);

  const triggerDownload = async (format) => {
    setDownloading(format);
    try {
      const res = await api.get('/privacy/me', {
        params: { format },
        responseType: 'blob',
      });
      const ext = format === 'pdf' ? 'pdf' : 'json';
      const mime = format === 'pdf' ? 'application/pdf' : 'application/json';
      const blob = new Blob([res.data], { type: mime });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `nischint-dpdp-export-${(summary?.data_principal?.id || 'me').slice(0, 8)}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || `Failed to download ${format.toUpperCase()}`);
    }
    setDownloading(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="privacy-loading">
        <Loader2 className="w-6 h-6 text-teal-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-6" data-testid="privacy-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <button onClick={() => navigate(-1)} className="p-1" data-testid="privacy-back">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <h1 className="text-base font-semibold text-white">Privacy & My Data</h1>
      </div>

      {/* DPDP banner */}
      <div className="p-4 rounded-2xl bg-teal-500/5 border border-teal-500/20 mb-5">
        <div className="flex items-start gap-3">
          <Shield className="w-5 h-5 text-teal-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-white">Your data, your right.</p>
            <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
              Under India&apos;s Digital Personal Data Protection Act, 2023 (§11), you can download
              everything we hold about you — anytime, in a single file.
            </p>
            <p className="text-[10px] text-teal-400/80 mt-2 flex items-center gap-1.5">
              <Database className="w-3 h-3" /> Stored in India (Supabase Mumbai, ap-south-1)
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div
          className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 mb-4 text-[11px] text-red-300"
          data-testid="privacy-error"
        >
          {error}
        </div>
      )}

      {/* Download CTAs */}
      <div className="mb-6">
        <h2 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">
          Download your data
        </h2>
        <div className="space-y-2">
          <button
            onClick={() => triggerDownload('pdf')}
            disabled={downloading !== null}
            className="w-full p-4 rounded-2xl bg-gradient-to-br from-teal-500/15 to-teal-600/5 border border-teal-500/30 flex items-center gap-3 active:scale-[0.99] transition-transform disabled:opacity-60"
            data-testid="download-pdf-btn"
          >
            <div className="w-10 h-10 rounded-xl bg-teal-500/15 flex items-center justify-center shrink-0">
              {downloading === 'pdf' ? (
                <Loader2 className="w-5 h-5 text-teal-400 animate-spin" />
              ) : (
                <Download className="w-5 h-5 text-teal-400" />
              )}
            </div>
            <div className="flex-1 text-left">
              <p className="text-sm font-semibold text-white">Download my data (PDF)</p>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Human-readable receipt — share with your DPO or store offline.
              </p>
            </div>
          </button>

          <button
            onClick={() => triggerDownload('json')}
            disabled={downloading !== null}
            className="w-full p-4 rounded-2xl bg-slate-800/40 border border-slate-700/40 flex items-center gap-3 active:scale-[0.99] transition-transform disabled:opacity-60"
            data-testid="download-json-btn"
          >
            <div className="w-10 h-10 rounded-xl bg-slate-700/40 flex items-center justify-center shrink-0">
              {downloading === 'json' ? (
                <Loader2 className="w-5 h-5 text-slate-300 animate-spin" />
              ) : (
                <FileJson className="w-5 h-5 text-slate-300" />
              )}
            </div>
            <div className="flex-1 text-left">
              <p className="text-sm font-semibold text-white">Download as JSON</p>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Machine-readable — for porting to another service.
              </p>
            </div>
          </button>
        </div>
      </div>

      {/* What we have */}
      {summary && (
        <div className="mb-6">
          <h2 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">
            What we hold about you
          </h2>
          <div className="rounded-2xl bg-slate-800/30 border border-slate-700/40 divide-y divide-slate-700/40 overflow-hidden">
            {Object.entries(summary.data_categories).map(([cat, info]) => (
              <div
                key={cat}
                className="p-3 flex items-center gap-3"
                data-testid={`category-${cat}`}
              >
                <div className="flex-1">
                  <p className="text-xs text-white font-medium capitalize">{cat.replace(/_/g, ' ')}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{info.purpose}</p>
                </div>
                <span className="text-sm text-teal-400 font-mono font-semibold">{info.records}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* What we DON'T store */}
      <div className="mb-6">
        <h2 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">
          What we never store
        </h2>
        <div className="space-y-2">
          <DisclosureRow
            icon={<MicOff className="w-4 h-4 text-emerald-400" />}
            label="No audio stored — inference only"
            detail="Voice trigger runs in-memory; raw audio is discarded immediately after classification."
            testId="no-audio"
          />
          <DisclosureRow
            icon={<VideoOff className="w-4 h-4 text-emerald-400" />}
            label="No video under normal operation"
            detail="Only active SOS emergency streams are recorded, then auto-purged after 30 days."
            testId="no-video"
          />
          <DisclosureRow
            icon={<ScanFace className="w-4 h-4 text-emerald-400" />}
            label="No biometric templates"
            detail="Fall and motion detection use derived numeric vectors only — no faces or fingerprints."
            testId="no-biometrics"
          />
        </div>
      </div>

      {/* Processors */}
      {summary?.third_party_processors && (
        <div className="mb-6">
          <h2 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2 px-1">
            Who else processes your data
          </h2>
          <div className="rounded-2xl bg-slate-800/30 border border-slate-700/40 divide-y divide-slate-700/40 overflow-hidden">
            {summary.third_party_processors.map((p) => (
              <div key={p.name} className="p-3" data-testid={`processor-${p.name.split(' ')[0].toLowerCase()}`}>
                <div className="flex items-center gap-2">
                  <Server className="w-3.5 h-3.5 text-slate-500" />
                  <p className="text-xs text-white font-medium flex-1">{p.name}</p>
                  <span className="text-[9px] text-slate-500 flex items-center gap-1">
                    <MapPin className="w-2.5 h-2.5" /> {p.data_residency}
                  </span>
                </div>
                <p className="text-[10px] text-slate-500 mt-1 ml-5">{p.purpose}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Rights footer */}
      {summary?.rights && (
        <div className="p-4 rounded-2xl bg-slate-800/30 border border-slate-700/40">
          <p className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2">
            Need to correct or delete your data?
          </p>
          <a
            href={`mailto:${summary.rights.grievance_officer.email}?subject=DPDP%20Request`}
            className="flex items-center gap-2 text-sm text-teal-400 hover:text-teal-300"
            data-testid="grievance-mailto"
          >
            <Mail className="w-4 h-4" />
            {summary.rights.grievance_officer.email}
          </a>
          <p className="text-[10px] text-slate-500 mt-1">
            Response within {summary.rights.grievance_officer.response_sla_days} days.
          </p>
        </div>
      )}

      <p className="text-center text-[9px] text-slate-600 mt-6">
        DPDP Act 2023 · Export format v{summary?.export_meta?.format_version || '1.0'}
      </p>
    </div>
  );
}

function DisclosureRow({ icon, label, detail, testId }) {
  return (
    <div
      className="p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/15 flex items-start gap-3"
      data-testid={`disclosure-${testId}`}
    >
      <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center shrink-0 mt-0.5">
        {icon}
      </div>
      <div className="flex-1">
        <p className="text-xs text-white font-medium">{label}</p>
        <p className="text-[10px] text-slate-400 mt-0.5 leading-relaxed">{detail}</p>
      </div>
    </div>
  );
}
