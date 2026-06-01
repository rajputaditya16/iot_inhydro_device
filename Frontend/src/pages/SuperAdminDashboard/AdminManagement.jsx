import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Shield,
  Search,
  Plus,
  Edit2,
  Trash2,
  ShieldAlert,
  AlertTriangle,
  UserCog,
  Users,
  Ban,
  CheckCircle,
} from 'lucide-react';
import { SkeletonTable } from '../../components/Skeleton';
import EmptyState from '../../components/EmptyState';
import Modal from '../../components/Modal';

const API_BASE = import.meta.env.VITE_API_URL || '';

const ROLES = ['admin', 'superadmin'];

const AdminManagement = () => {
  // ── Core state ──────────────────────────────────────────────────────────────
  const [loading, setLoading] = useState(true);
  const [admins, setAdmins] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');

  // ── Modal state ─────────────────────────────────────────────────────────────
  const [showAdminModal, setShowAdminModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);

  // ── Form state ──────────────────────────────────────────────────────────────
  const [editingAdmin, setEditingAdmin] = useState(null);
  const [adminToDelete, setAdminToDelete] = useState(null);
  const [selectedAdmin, setSelectedAdmin] = useState(null);
  const [formData, setFormData] = useState({ name: '', email: '', password: '', role: 'admin' });
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState('');

  // ── Assignment state ────────────────────────────────────────────────────────
  const [devices, setDevices] = useState([]);
  const [locations, setLocations] = useState([]);
  const [assignedLocations, setAssignedLocations] = useState([]);
  const [assignedDeviceIds, setAssignedDeviceIds] = useState([]);
  const [assignLoading, setAssignLoading] = useState(false);
  const [assignError, setAssignError] = useState('');

  // ── Auth ────────────────────────────────────────────────────────────────────
  const token = localStorage.getItem('token');

  // ── Fetch Admins ─────────────────────────────────────────────────────────────
  const fetchAdmins = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/superadmin/admins`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setAdmins(data.data);
      }
    } catch (err) {
      console.error('Failed to fetch admins', err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  // ── Fetch Devices & Locations (for assignment modal) ────────────────────────
  const fetchDevicesAndLocations = useCallback(async () => {
    try {
      const [devRes, locRes] = await Promise.all([
        fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_BASE}/api/users/locations`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);
      const devData = await devRes.json();
      const locData = await locRes.json();
      if (devData.success) setDevices(devData.data);
      if (locData.success) setLocations(locData.data);
    } catch (err) {
      console.error('Failed to fetch devices/locations', err);
    }
  }, [token]);

  useEffect(() => {
    fetchAdmins();
  }, [fetchAdmins]);

  // ── Filtered admins ──────────────────────────────────────────────────────────
  const filtered = admins.filter(
    (a) =>
      a.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.role.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // ── Open Add/Edit Admin Modal ────────────────────────────────────────────────
  const handleOpenModal = (admin = null) => {
    setFormError('');
    if (admin) {
      setEditingAdmin(admin);
      setFormData({ name: admin.name, email: admin.email, password: '', role: admin.role });
    } else {
      setEditingAdmin(null);
      setFormData({ name: '', email: '', password: '', role: 'admin' });
    }
    setShowAdminModal(true);
  };

  // ── Submit Add/Edit Admin ────────────────────────────────────────────────────
  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormLoading(true);
    setFormError('');

    const isEditing = !!editingAdmin;
    const url = isEditing
      ? `${API_BASE}/api/superadmin/admins/${editingAdmin._id}`
      : `${API_BASE}/api/superadmin/admins`;
    const method = isEditing ? 'PUT' : 'POST';

    const payload = { ...formData };
    if (isEditing && !payload.password) delete payload.password;

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.success) {
        setShowAdminModal(false);
        fetchAdmins();
      } else {
        setFormError(data.message || 'Error saving admin');
      }
    } catch {
      setFormError('Network error');
    } finally {
      setFormLoading(false);
    }
  };

  // ── Delete Admin ─────────────────────────────────────────────────────────────
  const handleDeleteClick = (admin) => {
    setAdminToDelete(admin);
    setShowDeleteConfirm(true);
  };

  const handleConfirmDelete = async () => {
    if (!adminToDelete) return;
    try {
      const res = await fetch(`${API_BASE}/api/superadmin/admins/${adminToDelete._id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setShowDeleteConfirm(false);
        setAdminToDelete(null);
        fetchAdmins();
      }
    } catch (err) {
      console.error('Failed to delete admin', err);
    }
  };

  // ── Open Assign Modal ──────────────────────────────────────────────────────
  const handleAssignDevice = async (admin) => {
    setSelectedAdmin(admin);
    setAssignError('');
    setAssignedLocations(admin.assignedLocations || []);
    setAssignedDeviceIds(
      (admin.assignedDevices || []).map((d) => (typeof d === 'string' ? d : d._id))
    );
    setShowAssignModal(true);
    await fetchDevicesAndLocations();
  };

  // ── Toggle Assignment checkbox ──────────────────────────────────────────────
  const toggleLocation = (loc) => {
    setAssignedLocations((prev) =>
      prev.includes(loc) ? prev.filter((l) => l !== loc) : [...prev, loc]
    );
  };

  const toggleDevice = (deviceId) => {
    setAssignedDeviceIds((prev) =>
      prev.includes(deviceId) ? prev.filter((d) => d !== deviceId) : [...prev, deviceId]
    );
  };

  // ── Save Assignment ─────────────────────────────────────────────────────────
  const handleSaveAssignment = async () => {
    if (!selectedAdmin) return;
    setAssignLoading(true);
    setAssignError('');

    try {
      const res = await fetch(`${API_BASE}/api/superadmin/admins/${selectedAdmin._id}/assign`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ assignedLocations, assignedDevices: assignedDeviceIds }),
      });
      const data = await res.json();
      if (data.success) {
        setShowAssignModal(false);
        fetchAdmins();
      } else {
        setAssignError(data.message || 'Error assigning');
      }
    } catch {
      setAssignError('Network error');
    } finally {
      setAssignLoading(false);
    }
  };

  // ── Toggle Block/Unblock ─────────────────────────────────────────────────────
  const handleToggleStatus = async (adminId) => {
    try {
      const res = await fetch(`${API_BASE}/api/superadmin/admins/${adminId}/toggle-status`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) fetchAdmins();
    } catch (err) {
      console.error('Failed to toggle status', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">System Administrators</h2>
          <p className="text-sm text-slate-400">{admins.length} admin accounts</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search admins..."
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 py-2.5 pl-10 pr-4 text-sm text-white placeholder-slate-500 outline-none focus:border-red-500 focus:ring-2 focus:ring-red-500/20 sm:w-64"
            />
          </div>
          <button
            onClick={() => handleOpenModal()}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-red-500 to-rose-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-red-500/20 transition-all hover:shadow-red-500/30"
          >
            <Plus className="h-4 w-4" /> Add Admin
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <SkeletonTable rows={5} cols={6} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Shield} title="No admins found" description="No administrative accounts match your search." />
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/50 bg-slate-800/30 backdrop-blur-sm"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Admin</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Role</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Users Created</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Devices</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Status</th>
                <th className="px-6 py-4 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((admin) => {
                const adminDevices = admin.assignedDevices || [];
                return (
                  <tr key={admin._id} className="border-b border-slate-700/30 transition-colors hover:bg-slate-800/50">
                    {/* Admin */}
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-red-500 to-rose-400 text-xs font-bold text-white uppercase">
                          {admin.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
                        </div>
                        <div>
                          <p className="font-medium text-white">{admin.name}</p>
                          <p className="text-xs text-slate-500">{admin.email}</p>
                        </div>
                      </div>
                    </td>

                    {/* Role */}
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${
                        admin.role === 'superadmin'
                          ? 'bg-purple-500/10 text-purple-400 border-purple-500/20'
                          : 'bg-red-500/10 text-red-400 border-red-500/20'
                      }`}>
                        <Shield className="h-3 w-3" />
                        {admin.role}
                      </span>
                    </td>

                    {/* Users Created */}
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1.5">
                        <Users className="h-3.5 w-3.5 text-slate-500" />
                        <span className="text-slate-300 font-medium">{admin.userCount ?? 0}</span>
                        <span className="text-slate-500 text-xs">user{(admin.userCount ?? 0) !== 1 ? 's' : ''}</span>
                      </div>
                    </td>

                    {/* Devices */}
                    <td className="px-6 py-4">
                      <span className="text-slate-300">
                        {adminDevices.length === 0
                          ? 'None'
                          : `${adminDevices.length} device${adminDevices.length > 1 ? 's' : ''}`}
                      </span>
                    </td>

                    {/* Status */}
                    <td className="px-6 py-4">
                      <button
                        onClick={() => handleToggleStatus(admin._id)}
                        title="Click to toggle block/unblock"
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase cursor-pointer transition-all hover:opacity-80 ${
                          admin.status === 'active'
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : 'bg-red-500/10 text-red-400'
                        }`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${admin.status === 'active' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                        {admin.status === 'active' ? 'active' : 'blocked'}
                      </button>
                    </td>

                    {/* Actions */}
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-1">
                        {/* Assign Devices */}
                        <button
                          onClick={() => handleAssignDevice(admin)}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
                          title="Assign Devices"
                        >
                          <UserCog className="h-4 w-4" />
                        </button>
                        {/* Edit */}
                        <button
                          onClick={() => handleOpenModal(admin)}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-700 hover:text-white"
                          title="Edit"
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>
                        {/* Block/Unblock */}
                        <button
                          onClick={() => handleToggleStatus(admin._id)}
                          className={`rounded-lg p-2 text-slate-400 transition-colors ${
                            admin.status === 'active'
                              ? 'hover:bg-orange-500/10 hover:text-orange-400'
                              : 'hover:bg-emerald-500/10 hover:text-emerald-400'
                          }`}
                          title={admin.status === 'active' ? 'Block Admin' : 'Unblock Admin'}
                        >
                          {admin.status === 'active' ? <Ban className="h-4 w-4" /> : <CheckCircle className="h-4 w-4" />}
                        </button>
                        {/* Delete */}
                        <button
                          onClick={() => handleDeleteClick(admin)}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      )}

      {/* ════════════════════════════════════════════════════════════════════════
          ADD / EDIT ADMIN MODAL
      ════════════════════════════════════════════════════════════════════════ */}
      <Modal isOpen={showAdminModal} onClose={() => setShowAdminModal(false)} title={editingAdmin ? 'Edit Admin' : 'Add New Admin'} size="sm">
        <form onSubmit={handleSubmit} className="space-y-4">
          {formError && (
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-3 flex gap-2 text-red-400 text-sm">
              <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
              <p>{formError}</p>
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Full Name</label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500"
              placeholder="John Doe"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Email</label>
            <input
              type="email"
              required
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500"
              placeholder="john@example.com"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">
              Password {editingAdmin && <span className="text-slate-500 font-normal">(leave empty to keep current)</span>}
            </label>
            <input
              type="password"
              required={!editingAdmin}
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500"
              placeholder={editingAdmin ? '••••••••' : 'Min 6 characters'}
              minLength={formData.password ? 6 : undefined}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Role</label>
            <select
              value={formData.role}
              onChange={(e) => setFormData({ ...formData, role: e.target.value })}
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
              ))}
            </select>
          </div>

          <div className="pt-4 flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setShowAdminModal(false)}
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={formLoading}
              className="rounded-xl bg-gradient-to-r from-red-500 to-rose-500 px-6 py-2 text-sm font-bold text-white shadow-lg shadow-red-500/20 disabled:opacity-50"
            >
              {formLoading ? 'Saving...' : editingAdmin ? 'Update Admin' : 'Create Admin'}
            </button>
          </div>
        </form>
      </Modal>

      {/* ════════════════════════════════════════════════════════════════════════
          ASSIGN DEVICES / LOCATIONS MODAL
      ════════════════════════════════════════════════════════════════════════ */}
      <Modal isOpen={showAssignModal} onClose={() => setShowAssignModal(false)} title="Assign Devices & Locations" size="lg">
        {selectedAdmin && (
          <div className="space-y-5">
            {/* Admin info */}
            <div className="flex items-center gap-3 rounded-xl bg-slate-900/50 p-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-red-500 to-rose-400 text-sm font-bold text-white uppercase">
                {selectedAdmin.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
              </div>
              <div>
                <p className="font-medium text-white">{selectedAdmin.name}</p>
                <p className="text-xs text-slate-500">{selectedAdmin.email} · {selectedAdmin.role}</p>
              </div>
            </div>

            {assignError && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-3 flex gap-2 text-red-400 text-sm">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <p>{assignError}</p>
              </div>
            )}

            {/* Assign Locations */}
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-500">
                Assign Locations
              </label>
              <div className="space-y-2 max-h-36 overflow-y-auto">
                {locations.length === 0 ? (
                  <p className="text-sm text-slate-500 italic">No locations found. Add devices with locations first.</p>
                ) : (
                  locations.map((loc) => (
                    <label
                      key={loc}
                      className="flex items-center gap-3 rounded-lg border border-slate-700/50 bg-slate-900/30 px-4 py-3 cursor-pointer transition-colors hover:bg-slate-800/50"
                    >
                      <input
                        type="checkbox"
                        checked={assignedLocations.includes(loc)}
                        onChange={() => toggleLocation(loc)}
                        className="rounded border-slate-600 bg-slate-800 text-red-500 focus:ring-red-500/20"
                      />
                      <span className="text-sm text-slate-300">{loc}</span>
                    </label>
                  ))
                )}
              </div>
            </div>

            {/* Assign Devices */}
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-500">
                Assign Devices
              </label>
              <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
                {devices.length === 0 ? (
                  <p className="col-span-2 text-sm text-slate-500 italic">No devices found.</p>
                ) : (
                  devices.map((dev) => {
                    const devId = dev._id || dev.id;
                    return (
                      <label
                        key={devId}
                        className="flex items-center gap-2 rounded-lg border border-slate-700/50 bg-slate-900/30 px-3 py-2 cursor-pointer transition-colors hover:bg-slate-800/50"
                      >
                        <input
                          type="checkbox"
                          checked={assignedDeviceIds.includes(devId)}
                          onChange={() => toggleDevice(devId)}
                          className="rounded border-slate-600 bg-slate-800 text-red-500 focus:ring-red-500/20"
                        />
                        <div>
                          <p className="text-xs text-slate-300 font-medium">{dev.name}</p>
                          <p className="text-[10px] text-slate-500">{dev.location}</p>
                        </div>
                      </label>
                    );
                  })
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-3 justify-end pt-2">
              <button
                onClick={() => setShowAssignModal(false)}
                className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-700 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAssignment}
                disabled={assignLoading}
                className="rounded-xl bg-gradient-to-r from-red-500 to-rose-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-red-500/20 disabled:opacity-50"
              >
                {assignLoading ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* ════════════════════════════════════════════════════════════════════════
          DELETE CONFIRMATION MODAL
      ════════════════════════════════════════════════════════════════════════ */}
      <Modal isOpen={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)} title="Delete Admin" size="sm">
        {adminToDelete && (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-500/10 shrink-0">
                <AlertTriangle className="h-5 w-5 text-red-400" />
              </div>
              <div>
                <p className="text-sm text-slate-300">
                  Are you sure you want to delete <strong className="text-white">{adminToDelete.name}</strong>?
                  This action cannot be undone.
                </p>
                <p className="mt-1 text-xs text-slate-500">{adminToDelete.email}</p>
              </div>
            </div>

            <div className="flex gap-3 justify-end pt-2">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-700 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                className="rounded-xl bg-red-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-red-500/20 transition-colors hover:bg-red-600"
              >
                Delete Admin
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default AdminManagement;
