import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Users, Building2, Activity, Shield, Search, Plus, Pencil,
  Trash2, Loader2, ChevronDown, ChevronUp, CheckCircle, XCircle,
  Phone, Mail, MapPin, Hash, UserCog, Database, Globe, Key, BarChart3,
  ChevronLeft, ChevronRight, Eye, Power, User as UserIcon, X,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { MonitoringTab } from './MonitoringTab';

const ROLE_COLORS = {
  admin: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', dot: 'bg-red-500' },
  operator: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', dot: 'bg-amber-500' },
  caregiver: { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  guardian: { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', dot: 'bg-blue-500' },
  user: { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-600', dot: 'bg-slate-400' },
};

const FACILITY_TYPES = ['home', 'hospital', 'elder_care', 'community', 'smart_city'];
const FACILITY_TYPE_LABELS = { home: 'Home', hospital: 'Hospital', elder_care: 'Elder Care', community: 'Community', smart_city: 'Smart City' };
const ROLES = ['admin', 'operator', 'caregiver', 'guardian'];

const RoleBadge = ({ role }) => {
  const c = ROLE_COLORS[role] || ROLE_COLORS.user;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${c.bg} ${c.text} ${c.border} border`} data-testid={`role-badge-${role}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />{role}
    </span>
  );
};

const StatusDot = ({ active }) => (
  <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${active ? 'text-emerald-600' : 'text-slate-400'}`}>
    <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-emerald-500' : 'bg-slate-300'}`} />{active ? 'Active' : 'Inactive'}
  </span>
);

/* ═══════════════════════════════════════════════════════════════════════
   SYSTEM HEALTH TAB
   ═══════════════════════════════════════════════════════════════════════ */
const SystemHealthTab = () => {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get('/admin/system-health');
        setHealth(res.data);
      } catch {}
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-teal-500" /></div>;
  if (!health) return <p className="text-sm text-slate-400 text-center py-8">Failed to load system health</p>;

  return (
    <div className="space-y-4" data-testid="system-health-tab">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Status', value: health.status, icon: Activity, color: health.status === 'healthy' ? 'emerald' : 'red' },
          { label: 'Database', value: health.services?.database || 'unknown', icon: Database, color: 'blue' },
          { label: 'Auth', value: health.services?.authentication || 'unknown', icon: Key, color: 'violet' },
          { label: 'Notifications', value: health.services?.notifications || 'unknown', icon: Globe, color: 'amber' },
        ].map(s => (
          <Card key={s.label} className="p-3">
            <div className="flex items-center gap-2">
              <s.icon className={`w-4 h-4 text-${s.color}-500`} />
              <div>
                <p className="text-[10px] text-slate-500">{s.label}</p>
                <p className={`text-sm font-semibold text-${s.color}-600`}>{s.value}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>
      {health.role_counts && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">User Roles Distribution</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(health.role_counts).map(([role, count]) => (
                <div key={role} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-50 border">
                  <RoleBadge role={role} /><span className="text-sm font-bold text-slate-700">{count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   CREATE USER MODAL
   ═══════════════════════════════════════════════════════════════════════ */
const CreateUserModal = ({ facilities, onClose, onCreated }) => {
  const [form, setForm] = useState({ email: '', full_name: '', phone: '', password: '', role: 'guardian', facility_id: '' });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form };
      if (!payload.facility_id) delete payload.facility_id;
      await api.post('/admin/users', payload);
      toast.success('User created');
      onCreated();
      onClose();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create user');
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="create-user-modal">
      <Card className="w-full max-w-md">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base">Create New User</CardTitle>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="w-4 h-4" /></Button>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <Input placeholder="Email" type="email" required value={form.email} onChange={e => set('email', e.target.value)} data-testid="create-user-email" />
            <Input placeholder="Full Name" value={form.full_name} onChange={e => set('full_name', e.target.value)} data-testid="create-user-name" />
            <Input placeholder="Phone" value={form.phone} onChange={e => set('phone', e.target.value)} data-testid="create-user-phone" />
            <Input placeholder="Password (min 6 chars)" type="password" required minLength={6} value={form.password} onChange={e => set('password', e.target.value)} data-testid="create-user-password" />
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Role</label>
              <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={form.role} onChange={e => set('role', e.target.value)} data-testid="create-user-role">
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Facility (optional)</label>
              <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={form.facility_id} onChange={e => set('facility_id', e.target.value)} data-testid="create-user-facility">
                <option value="">No facility</option>
                {facilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" size="sm" onClick={onClose}>Cancel</Button>
              <Button type="submit" size="sm" disabled={saving} data-testid="create-user-submit">
                {saving && <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />}Create User
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   USERS TAB
   ═══════════════════════════════════════════════════════════════════════ */
const UsersTab = ({ facilities }) => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [facilityFilter, setFacilityFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [expanded, setExpanded] = useState(null);
  const [showCreate, setShowCreate] = useState(false);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: 15 });
      if (search) params.append('search', search);
      if (roleFilter) params.append('role', roleFilter);
      if (facilityFilter) params.append('facility_id', facilityFilter);
      if (statusFilter) params.append('is_active', statusFilter);
      const res = await api.get(`/admin/users?${params}`);
      setUsers(res.data.users || []);
      setTotalPages(res.data.total_pages || 1);
      setTotal(res.data.total || 0);
    } catch { toast.error('Failed to load users'); }
    setLoading(false);
  }, [search, roleFilter, facilityFilter, statusFilter, page]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);
  useEffect(() => { setPage(1); }, [search, roleFilter, facilityFilter, statusFilter]);

  const toggleStatus = async (userId, currentActive) => {
    try {
      await api.patch(`/admin/users/${userId}/status`, { is_active: !currentActive });
      toast.success(`User ${!currentActive ? 'activated' : 'deactivated'}`);
      fetchUsers();
    } catch { toast.error('Failed to update status'); }
  };

  const updateRole = async (userId, newRole) => {
    try {
      await api.patch(`/admin/users/${userId}/role`, { role: newRole });
      toast.success('Role updated');
      fetchUsers();
    } catch { toast.error('Failed to update role'); }
  };

  const updateFacility = async (userId, facId) => {
    try {
      await api.patch(`/admin/users/${userId}/facility`, { facility_id: facId || null });
      toast.success('Facility updated');
      fetchUsers();
    } catch { toast.error('Failed to update facility'); }
  };

  const getFacName = (id) => facilities.find(f => f.id === id)?.name || '-';

  return (
    <div className="space-y-4" data-testid="users-tab">
      {showCreate && <CreateUserModal facilities={facilities} onClose={() => setShowCreate(false)} onCreated={fetchUsers} />}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <Input className="pl-9 h-9 text-sm" placeholder="Search by name or email..." value={search} onChange={e => setSearch(e.target.value)} data-testid="user-search" />
        </div>
        <select className="h-9 rounded-md border px-2 text-xs" value={roleFilter} onChange={e => setRoleFilter(e.target.value)} data-testid="user-role-filter">
          <option value="">All Roles</option>
          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select className="h-9 rounded-md border px-2 text-xs" value={facilityFilter} onChange={e => setFacilityFilter(e.target.value)} data-testid="user-facility-filter">
          <option value="">All Facilities</option>
          {facilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
        <select className="h-9 rounded-md border px-2 text-xs" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} data-testid="user-status-filter">
          <option value="">All Status</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
        <Button size="sm" className="h-9 gap-1" onClick={() => setShowCreate(true)} data-testid="create-user-btn">
          <Plus className="w-3.5 h-3.5" />New User
        </Button>
      </div>

      {/* Summary */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">{total} users found</p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-7 text-xs" disabled={page <= 1} onClick={() => setPage(p => p - 1)} data-testid="users-prev-page">
            <ChevronLeft className="w-3 h-3" />
          </Button>
          <span className="text-xs text-slate-500">Page {page} of {totalPages}</span>
          <Button size="sm" variant="outline" className="h-7 text-xs" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} data-testid="users-next-page">
            <ChevronRight className="w-3 h-3" />
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">{[1,2,3,4,5].map(i => <div key={i} className="h-14 rounded-lg bg-slate-50 animate-pulse" />)}</div>
      ) : users.length === 0 ? (
        <div className="text-center py-12 border rounded-lg border-dashed">
          <Users className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-400">No users match your filters</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {users.map(u => (
            <div key={u.id} className={`rounded-lg border ${u.is_active ? 'border-slate-200 bg-white' : 'border-slate-100 bg-slate-50 opacity-70'} transition-all`} data-testid={`user-row-${u.id}`}>
              {/* Main Row */}
              <div className="flex items-center gap-3 px-4 py-3 cursor-pointer" onClick={() => setExpanded(expanded === u.id ? null : u.id)}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${u.is_active ? 'bg-teal-50 text-teal-600' : 'bg-slate-100 text-slate-400'}`}>
                  {(u.full_name || u.email || '?')[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-800 truncate">{u.full_name || u.email.split('@')[0]}</span>
                    <RoleBadge role={u.role} />
                    <StatusDot active={u.is_active} />
                  </div>
                  <p className="text-[11px] text-slate-400 truncate">{u.email}</p>
                </div>
                <div className="text-[11px] text-slate-400 hidden md:block">{getFacName(u.facility_id)}</div>
                {expanded === u.id ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
              </div>

              {/* Expanded Detail */}
              {expanded === u.id && (
                <div className="px-4 pb-4 pt-1 border-t border-slate-100 space-y-3" data-testid={`user-detail-${u.id}`}>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div><span className="text-slate-400 block">Email</span><span className="text-slate-700">{u.email}</span></div>
                    <div><span className="text-slate-400 block">Phone</span><span className="text-slate-700">{u.phone || '-'}</span></div>
                    <div><span className="text-slate-400 block">Cognito</span><span className="text-slate-700">{u.cognito_sub ? 'Linked' : 'Local only'}</span></div>
                    <div><span className="text-slate-400 block">Created</span><span className="text-slate-700">{u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}</span></div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <select className="h-8 rounded border px-2 text-xs" value={u.role} onChange={e => updateRole(u.id, e.target.value)} data-testid={`edit-role-${u.id}`}>
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <select className="h-8 rounded border px-2 text-xs" value={u.facility_id || ''} onChange={e => updateFacility(u.id, e.target.value)} data-testid={`edit-facility-${u.id}`}>
                      <option value="">No facility</option>
                      {facilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
                    </select>
                    <Button size="sm" variant={u.is_active ? 'outline' : 'default'} className={`h-8 text-xs gap-1 ${!u.is_active ? '' : 'text-red-600 hover:bg-red-50 border-red-200'}`} onClick={() => toggleStatus(u.id, u.is_active)} data-testid={`toggle-status-${u.id}`}>
                      <Power className="w-3 h-3" />{u.is_active ? 'Deactivate' : 'Activate'}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   EDIT FACILITY MODAL
   ═══════════════════════════════════════════════════════════════════════ */
const EditFacilityModal = ({ facility, onClose, onUpdated }) => {
  const [form, setForm] = useState({
    name: facility.name || '',
    facility_type: facility.facility_type || 'home',
    address: facility.address || '',
    city: facility.city || '',
    state: facility.state || '',
    phone: facility.phone || '',
    email: facility.email || '',
    max_users: facility.max_users || '',
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form, max_users: form.max_users ? parseInt(form.max_users) : null };
      await api.put(`/admin/facilities/${facility.id}`, payload);
      toast.success('Facility updated');
      onUpdated();
      onClose();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to update facility');
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="edit-facility-modal">
      <Card className="w-full max-w-md">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base">Edit Facility</CardTitle>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="w-4 h-4" /></Button>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <Input placeholder="Facility Name" required value={form.name} onChange={e => set('name', e.target.value)} data-testid="edit-fac-name" />
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Facility Type</label>
              <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={form.facility_type} onChange={e => set('facility_type', e.target.value)} data-testid="edit-fac-type">
                {FACILITY_TYPES.map(t => <option key={t} value={t}>{FACILITY_TYPE_LABELS[t]}</option>)}
              </select>
            </div>
            <Input placeholder="Address" value={form.address} onChange={e => set('address', e.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <Input placeholder="City" value={form.city} onChange={e => set('city', e.target.value)} />
              <Input placeholder="State" value={form.state} onChange={e => set('state', e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input placeholder="Phone" value={form.phone} onChange={e => set('phone', e.target.value)} />
              <Input placeholder="Email" value={form.email} onChange={e => set('email', e.target.value)} />
            </div>
            <Input placeholder="Max Users (capacity)" type="number" value={form.max_users} onChange={e => set('max_users', e.target.value)} data-testid="edit-fac-max-users" />
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" size="sm" onClick={onClose}>Cancel</Button>
              <Button type="submit" size="sm" disabled={saving} data-testid="edit-fac-submit">
                {saving && <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />}Save Changes
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   FACILITIES TAB
   ═══════════════════════════════════════════════════════════════════════ */
const FacilitiesTab = ({ facilities, onRefresh, onDrillDown }) => {
  const [showCreate, setShowCreate] = useState(false);
  const [editFac, setEditFac] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newFac, setNewFac] = useState({ name: '', code: '', facility_type: 'home', address: '', city: '', state: '', phone: '', email: '', max_users: '' });
  const setField = (k, v) => setNewFac(f => ({ ...f, [k]: v }));

  const handleCreate = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      const payload = { ...newFac, max_users: newFac.max_users ? parseInt(newFac.max_users) : null };
      await api.post('/admin/facilities', payload);
      toast.success('Facility created');
      setShowCreate(false);
      setNewFac({ name: '', code: '', facility_type: 'home', address: '', city: '', state: '', phone: '', email: '', max_users: '' });
      onRefresh();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create');
    }
    setCreating(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this facility?')) return;
    try {
      await api.delete(`/admin/facilities/${id}`);
      toast.success('Facility deleted');
      onRefresh();
    } catch { toast.error('Failed to delete'); }
  };

  const toggleFacStatus = async (id, currentActive) => {
    try {
      await api.patch(`/admin/facilities/${id}/status`, { is_active: !currentActive });
      toast.success(`Facility ${!currentActive ? 'activated' : 'deactivated'}`);
      onRefresh();
    } catch { toast.error('Failed to update status'); }
  };

  return (
    <div className="space-y-4" data-testid="facilities-tab">
      {editFac && <EditFacilityModal facility={editFac} onClose={() => setEditFac(null)} onUpdated={onRefresh} />}

      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">{facilities.length} facilities</p>
        <Button size="sm" className="h-9 gap-1" onClick={() => setShowCreate(!showCreate)} data-testid="toggle-create-facility">
          <Plus className="w-3.5 h-3.5" />New Facility
        </Button>
      </div>

      {/* Create Form */}
      {showCreate && (
        <Card data-testid="create-facility-form">
          <CardContent className="pt-4">
            <form onSubmit={handleCreate} className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <Input placeholder="Facility Name" required value={newFac.name} onChange={e => setField('name', e.target.value)} data-testid="new-fac-name" />
                <Input placeholder="Code (unique)" required value={newFac.code} onChange={e => setField('code', e.target.value)} data-testid="new-fac-code" />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-slate-500 mb-1 block">Facility Type</label>
                  <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newFac.facility_type} onChange={e => setField('facility_type', e.target.value)} data-testid="new-fac-type">
                    {FACILITY_TYPES.map(t => <option key={t} value={t}>{FACILITY_TYPE_LABELS[t]}</option>)}
                  </select>
                </div>
                <Input placeholder="Max Users" type="number" value={newFac.max_users} onChange={e => setField('max_users', e.target.value)} data-testid="new-fac-max-users" />
              </div>
              <Input placeholder="Address" value={newFac.address} onChange={e => setField('address', e.target.value)} />
              <div className="grid grid-cols-2 gap-2">
                <Input placeholder="City" value={newFac.city} onChange={e => setField('city', e.target.value)} />
                <Input placeholder="State" value={newFac.state} onChange={e => setField('state', e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Input placeholder="Phone" value={newFac.phone} onChange={e => setField('phone', e.target.value)} />
                <Input placeholder="Email" value={newFac.email} onChange={e => setField('email', e.target.value)} />
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => setShowCreate(false)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={creating} data-testid="create-fac-submit">
                  {creating && <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />}Create
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Facility List */}
      {facilities.length === 0 ? (
        <div className="text-center py-12 border rounded-lg border-dashed">
          <Building2 className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-400">No facilities yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {facilities.map(f => (
            <Card key={f.id} className={`${f.is_active ? '' : 'opacity-60'}`} data-testid={`facility-card-${f.id}`}>
              <CardContent className="pt-4 pb-3">
                <div className="flex items-start justify-between mb-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <h4 className="text-sm font-semibold text-slate-800 truncate">{f.name}</h4>
                      <StatusDot active={f.is_active} />
                    </div>
                    <div className="flex items-center gap-2 text-[10px]">
                      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium">{FACILITY_TYPE_LABELS[f.facility_type] || f.facility_type}</span>
                      <span className="text-slate-400">#{f.code}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => setEditFac(f)} data-testid={`edit-fac-${f.id}`}><Pencil className="w-3 h-3" /></Button>
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-red-500" onClick={() => handleDelete(f.id)} data-testid={`delete-fac-${f.id}`}><Trash2 className="w-3 h-3" /></Button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-500 mt-2">
                  {f.city && <span className="flex items-center gap-1"><MapPin className="w-2.5 h-2.5" />{f.city}{f.state ? `, ${f.state}` : ''}</span>}
                  {f.phone && <span className="flex items-center gap-1"><Phone className="w-2.5 h-2.5" />{f.phone}</span>}
                  {f.email && <span className="flex items-center gap-1"><Mail className="w-2.5 h-2.5" />{f.email}</span>}
                </div>

                {/* Capacity bar */}
                <div className="mt-3 flex items-center gap-3">
                  <button className="text-xs text-teal-600 font-medium hover:underline" onClick={() => onDrillDown?.(f.id)} data-testid={`fac-users-${f.id}`}>
                    {f.user_count || 0} users
                  </button>
                  {f.max_users && (
                    <div className="flex-1">
                      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all ${(f.user_count || 0) >= f.max_users ? 'bg-red-500' : 'bg-teal-500'}`}
                          style={{ width: `${Math.min(100, ((f.user_count || 0) / f.max_users) * 100)}%` }} />
                      </div>
                      <p className="text-[9px] text-slate-400 mt-0.5">{f.user_count || 0}/{f.max_users} capacity</p>
                    </div>
                  )}
                  <Button size="sm" variant={f.is_active ? 'outline' : 'default'} className={`h-7 text-[10px] gap-1 ${!f.is_active ? '' : 'text-red-500 hover:bg-red-50 border-red-200'}`} onClick={() => toggleFacStatus(f.id, f.is_active)} data-testid={`toggle-fac-status-${f.id}`}>
                    <Power className="w-2.5 h-2.5" />{f.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   ADMIN PANEL (MAIN)
   ═══════════════════════════════════════════════════════════════════════ */
const AdminPanel = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('health');
  const [facilities, setFacilities] = useState([]);

  const isAdmin = user?.role === 'admin' || user?.roles?.includes('admin');

  const fetchFacilities = useCallback(async () => {
    try {
      const res = await api.get('/admin/facilities');
      setFacilities(res.data.facilities || []);
    } catch {}
  }, []);

  useEffect(() => {
    if (!isAdmin) { navigate('/family'); return; }
    fetchFacilities();
  }, [isAdmin, navigate, fetchFacilities]);

  if (!isAdmin) return null;

  const tabs = [
    { id: 'health', label: 'System Health', icon: Activity },
    { id: 'monitoring', label: 'Monitoring', icon: BarChart3 },
    { id: 'users', label: 'Users', icon: Users },
    { id: 'facilities', label: 'Facilities', icon: Building2 },
  ];

  const handleFacilityDrillDown = (facilityId) => {
    setActiveTab('users');
  };

  return (
    <div className="min-h-screen bg-slate-50" data-testid="admin-panel">
      <div className="bg-slate-900 text-white px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-teal-500/20 flex items-center justify-center">
              <Shield className="w-5 h-5 text-teal-400" />
            </div>
            <div>
              <h1 className="text-base font-bold" data-testid="admin-panel-title">Admin Panel</h1>
              <p className="text-[11px] text-slate-400">NISCHINT Platform Administration</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" className="text-slate-300 border-slate-600 hover:bg-slate-800" onClick={() => navigate('/command-center')} data-testid="go-to-command-center">
              Command Center
            </Button>
            <Button size="sm" variant="outline" className="text-slate-300 border-slate-600 hover:bg-slate-800" onClick={() => navigate('/family')} data-testid="back-to-dashboard">
              Dashboard
            </Button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex gap-1 border-b border-slate-200 mb-6">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${activeTab === t.id ? 'bg-white border border-b-white border-slate-200 text-teal-600 -mb-px' : 'text-slate-500 hover:text-slate-700'}`}
              data-testid={`tab-${t.id}`}
            >
              <t.icon className="w-3.5 h-3.5" />{t.label}
            </button>
          ))}
        </div>

        {activeTab === 'health' && <SystemHealthTab />}
        {activeTab === 'monitoring' && <MonitoringTab />}
        {activeTab === 'users' && <UsersTab facilities={facilities} />}
        {activeTab === 'facilities' && <FacilitiesTab facilities={facilities} onRefresh={fetchFacilities} onDrillDown={handleFacilityDrillDown} />}
      </div>
    </div>
  );
};

export default AdminPanel;
