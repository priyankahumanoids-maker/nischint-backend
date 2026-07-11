import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api';
import {
  Phone, Plus, Trash2, ArrowLeft, Loader2, User,
  Inbox, Edit3, Check, X,
} from 'lucide-react';

export default function MobileContacts() {
  const navigate = useNavigate();
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editId, setEditId] = useState(null);

  // Form state
  const [formName, setFormName] = useState('');
  const [formPhone, setFormPhone] = useState('');
  const [formRelationship, setFormRelationship] = useState('');
  const [saving, setSaving] = useState(false);

  const fetch_ = useCallback(async () => {
    try {
      const res = await api.get('/guardian-network/emergency-contacts');
      setContacts(res.data.contacts || []);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetch_(); }, [fetch_]);

  const resetForm = () => {
    setFormName('');
    setFormPhone('');
    setFormRelationship('');
    setShowAdd(false);
    setEditId(null);
  };

  const handleSave = async () => {
    if (!formName || !formPhone) return;
    setSaving(true);
    try {
      if (editId) {
        await api.put(`/guardian-network/emergency-contacts/${editId}`, {
          name: formName,
          phone_number: formPhone,
          relationship: formRelationship || 'other',
        });
      } else {
        await api.post('/guardian-network/emergency-contacts', {
          name: formName,
          phone_number: formPhone,
          relationship: formRelationship || 'other',
        });
      }
      resetForm();
      fetch_();
    } catch { /* silent */ }
    setSaving(false);
  };

  const startEdit = (c) => {
    setFormName(c.name);
    setFormPhone(c.phone_number);
    setFormRelationship(c.relationship || '');
    setEditId(c.id);
    setShowAdd(true);
  };

  const removeContact = async (id) => {
    if (!window.confirm('Remove this emergency contact?')) return;
    try {
      await api.delete(`/guardian-network/emergency-contacts/${id}`);
      setContacts(c => c.filter(x => x.id !== id));
    } catch { /* silent */ }
  };

  return (
    <div className="px-4 pt-4 pb-6" data-testid="mobile-contacts">
      <div className="flex items-center justify-between mb-4">
        <button onClick={() => navigate('/m/guardians')} className="p-2 -ml-2 rounded-full active:bg-slate-800">
          <ArrowLeft className="w-5 h-5 text-slate-400" />
        </button>
        <h1 className="text-base font-bold text-white">Emergency Contacts</h1>
        <button
          onClick={() => { resetForm(); setShowAdd(true); }}
          className="p-2 rounded-full bg-blue-500/15 active:bg-blue-500/25"
          data-testid="add-contact-btn"
        >
          <Plus className="w-4 h-4 text-blue-400" />
        </button>
      </div>

      {/* Add/Edit Form */}
      {showAdd && (
        <div className="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/40 mb-4" data-testid="contact-form">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-white">{editId ? 'Edit Contact' : 'New Contact'}</p>
            <button onClick={resetForm} className="p-1 rounded-full active:bg-slate-700">
              <X className="w-4 h-4 text-slate-500" />
            </button>
          </div>
          <div className="space-y-2.5">
            <input
              type="text"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              placeholder="Full name"
              className="w-full px-3 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
              data-testid="contact-name-input"
            />
            <input
              type="tel"
              value={formPhone}
              onChange={e => setFormPhone(e.target.value)}
              placeholder="Phone number"
              className="w-full px-3 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
              data-testid="contact-phone-input"
            />
            <input
              type="text"
              value={formRelationship}
              onChange={e => setFormRelationship(e.target.value)}
              placeholder="Relationship (e.g. neighbor, doctor)"
              className="w-full px-3 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-white text-sm placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none"
              data-testid="contact-rel-input"
            />
            <button
              onClick={handleSave}
              disabled={saving || !formName || !formPhone}
              className="w-full py-2.5 rounded-xl bg-blue-500 text-white font-bold text-xs flex items-center justify-center gap-1.5 disabled:opacity-50 active:scale-[0.98] transition-transform"
              data-testid="save-contact-btn"
            >
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              {editId ? 'Update' : 'Save'} Contact
            </button>
          </div>
        </div>
      )}

      {/* Contact List */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      ) : contacts.length === 0 && !showAdd ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Inbox className="w-12 h-12 text-slate-700 mb-3" />
          <p className="text-sm text-slate-400 font-medium">No emergency contacts</p>
          <p className="text-xs text-slate-600 mt-1">Add contacts who can be reached during emergencies</p>
        </div>
      ) : (
        <div className="space-y-2" data-testid="contacts-list">
          {contacts.map(c => (
            <div key={c.id} className="p-3 rounded-2xl bg-slate-800/30 border border-slate-700/30" data-testid={`contact-card-${c.id}`}>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-blue-500/15 flex items-center justify-center shrink-0">
                  <User className="w-4 h-4 text-blue-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-white truncate">{c.name}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] text-slate-500 flex items-center gap-1">
                      <Phone className="w-2.5 h-2.5" /> {c.phone_number}
                    </span>
                    {c.relationship && (
                      <span className="text-[10px] text-slate-600 capitalize">{c.relationship}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-0.5">
                  <button
                    onClick={() => startEdit(c)}
                    className="p-1.5 rounded-lg active:bg-slate-700/50"
                    data-testid={`edit-contact-${c.id}`}
                  >
                    <Edit3 className="w-3.5 h-3.5 text-slate-500" />
                  </button>
                  <button
                    onClick={() => removeContact(c.id)}
                    className="p-1.5 rounded-lg active:bg-red-500/20"
                    data-testid={`remove-contact-${c.id}`}
                  >
                    <Trash2 className="w-3.5 h-3.5 text-red-400/60" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
