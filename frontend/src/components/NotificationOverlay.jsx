import React, { useState, useEffect, useCallback } from 'react';
import {
  Calendar, Package, ShieldAlert, MessageCircle, FileText,
  X, Eye, Shield, ChevronRight,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const ICON_MAP = {
  calendar: Calendar,
  package: Package,
  shield: ShieldAlert,
  message: MessageCircle,
  default: FileText,
  alert: ShieldAlert,
};

const CATEGORY_COLORS = {
  Work: '#2563eb',
  Delivery: '#059669',
  Security: '#dc2626',
  Message: '#7c3aed',
  Custom: '#475569',
};

const AUTO_DISMISS_MS = 12000;

const NotificationOverlay = ({ data, onClose }) => {
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [showActions, setShowActions] = useState(false);

  const notifId = data?.notification_id;
  const title = data?.title || 'New Notification';
  const message = data?.message || '';
  const category = data?.category || 'Custom';
  const iconStyle = data?.icon_style || 'default';

  const Icon = ICON_MAP[iconStyle] || ICON_MAP.default;
  const accentColor = CATEGORY_COLORS[category] || CATEGORY_COLORS.Custom;

  // Slide in animation
  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), 50);
    return () => clearTimeout(timer);
  }, []);

  // Auto-dismiss
  useEffect(() => {
    if (showActions) return; // Don't auto-dismiss if user opened actions
    const timer = setTimeout(() => handleDismiss(false), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [showActions]);

  const handleDismiss = useCallback((sendComplete = true) => {
    setExiting(true);
    if (sendComplete && notifId) {
      api.post(`/fake-notification/complete/${notifId}`, { dismissed: true, viewed: false, send_alert: false }).catch(() => {});
    }
    setTimeout(() => onClose?.(), 300);
  }, [notifId, onClose]);

  const handleView = useCallback(() => {
    setShowActions(true);
    if (notifId) {
      api.post(`/fake-notification/complete/${notifId}`, { viewed: true, dismissed: false, send_alert: false }).catch(() => {});
    }
  }, [notifId]);

  const handleAlert = useCallback(() => {
    if (notifId) {
      api.post(`/fake-notification/complete/${notifId}`, { viewed: true, dismissed: false, send_alert: true }).catch(() => {});
      toast.success('Alert sent to trusted contacts');
    }
    setExiting(true);
    setTimeout(() => onClose?.(), 300);
  }, [notifId, onClose]);

  const handleSafeDismiss = useCallback(() => {
    setExiting(true);
    setTimeout(() => onClose?.(), 300);
  }, [onClose]);

  // Post-action view (after "View" tap)
  if (showActions) {
    return (
      <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-black/40 backdrop-blur-sm"
           data-testid="notif-action-overlay">
        <div className={`bg-white rounded-2xl p-6 mx-4 max-w-sm w-full shadow-2xl border transition-all duration-300 ${exiting ? 'opacity-0 scale-95' : 'opacity-100 scale-100'}`}>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center" style={{ background: `${accentColor}15` }}>
              <Icon className="w-6 h-6" style={{ color: accentColor }} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-bold text-slate-800">{title}</div>
              <div className="text-xs text-slate-500">{category}</div>
            </div>
          </div>

          <p className="text-sm text-slate-600 mb-6">{message}</p>

          <div className="space-y-2">
            <button
              onClick={handleAlert}
              className="w-full py-3 px-4 bg-amber-500 hover:bg-amber-600 text-white rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all active:scale-95"
              data-testid="notif-alert-contacts-btn"
            >
              <Shield className="w-4 h-4" />
              Alert Trusted Contacts
            </button>
            <button
              onClick={handleSafeDismiss}
              className="w-full py-3 px-4 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all active:scale-95"
              data-testid="notif-safe-dismiss-btn"
            >
              <X className="w-4 h-4" />
              I'm Safe — Dismiss
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Banner notification (slides from top)
  return (
    <div
      className={`fixed top-0 left-0 right-0 z-[9998] flex justify-center pointer-events-none transition-transform duration-300 ${
        visible && !exiting ? 'translate-y-0' : '-translate-y-full'
      }`}
      data-testid="notification-banner"
    >
      <div className="pointer-events-auto mx-4 mt-4 w-full max-w-lg bg-white rounded-2xl shadow-2xl border overflow-hidden"
           style={{ borderTopWidth: 3, borderTopColor: accentColor }}>
        <div className="flex items-start gap-3 p-4">
          {/* Icon */}
          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: `${accentColor}15` }}>
            <Icon className="w-5 h-5" style={{ color: accentColor }} />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold" style={{ color: accentColor }}>{category}</span>
              <span className="text-[10px] text-slate-400">now</span>
            </div>
            <div className="font-bold text-slate-800 text-sm mt-0.5" data-testid="notif-banner-title">{title}</div>
            <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{message}</p>
          </div>

          {/* Close button */}
          <button onClick={() => handleDismiss(true)} className="text-slate-400 hover:text-slate-600 p-1 flex-shrink-0" data-testid="notif-close-btn">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Action bar */}
        <div className="flex border-t divide-x">
          <button
            onClick={handleView}
            className="flex-1 py-2.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 flex items-center justify-center gap-1 transition-colors"
            data-testid="notif-view-btn"
          >
            <Eye className="w-3.5 h-3.5" /> View
          </button>
          <button
            onClick={() => handleDismiss(true)}
            className="flex-1 py-2.5 text-xs font-semibold text-slate-400 hover:bg-slate-50 flex items-center justify-center gap-1 transition-colors"
            data-testid="notif-dismiss-btn"
          >
            <X className="w-3.5 h-3.5" /> Dismiss
          </button>
        </div>
      </div>
    </div>
  );
};

export default NotificationOverlay;
