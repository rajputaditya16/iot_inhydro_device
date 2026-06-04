import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Users, Search, Plus, Edit2, Trash2, Shield, Eye, UserCog, ShieldAlert, AlertTriangle, Ban, CheckCircle } from 'lucide-react';
import { SkeletonTable } from '../../components/Skeleton';
import EmptyState from '../../components/EmptyState';
import Modal from '../../components/Modal';

const API_BASE = import.meta.env.VITE_API_URL || '';
 
const roleBadge = {
  // admin: 'bg-red-500/10 text-red-400 border-red-500/20',
  // operator: 'bg-green-500/10 text-green-400 border-green-500/20',
  viewer: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
};

const roleIcon = {
  // admin: Shield,
  // operator: Users, 
  viewer: Eye,
};
 
const ROLES = ['viewer'];

const UserManagement = () => {
  // ── Core state ──────────────────────────────────────────────────────────────
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');

  // ── Modal state ─────────────────────────────────────────────────────────────
  const [showUserModal, setShowUserModal] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // ── Form state ──────────────────────────────────────────────────────────────
  const [editingUser, setEditingUser] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [userToDelete, setUserToDelete] = useState(null);
  const [formData, setFormData] = useState({ name: '', email: '', password: '', role: 'viewer' });
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

  // ── Fetch Users ─────────────────────────────────────────────────────────────
  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setUsers(data.data);
      }
    } catch (err) {
      console.error('Failed to fetch users', err);
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
    fetchUsers();
  }, [fetchUsers]);

  // ── Filtered users ──────────────────────────────────────────────────────────
  const filtered = users.filter(
    (u) =>
      u.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      u.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      u.role.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // ── Open Add/Edit User Modal ────────────────────────────────────────────────
  const handleOpenUserModal = (user = null) => {
    setFormError('');
    if (user) {
      setEditingUser(user);
      setFormData({
        name: user.name,
        email: user.email,
        password: '',
        role: user.role,
      });
    } else {
      setEditingUser(null);
      setFormData({ name: '', email: '', password: '', role: 'viewer' });
    }
    setShowUserModal(true);
  };

  // ── Submit Add/Edit User ────────────────────────────────────────────────────
  const handleSubmitUser = async (e) => {
    e.preventDefault();
    setFormLoading(true);
    setFormError('');

    const isEditing = !!editingUser;
    const url = isEditing
      ? `${API_BASE}/api/users/${editingUser._id}`
      : `${API_BASE}/api/users`;
    const method = isEditing ? 'PUT' : 'POST';

    // Build payload — don't send password on edit if empty
    const payload = { ...formData };
    if (isEditing && !payload.password) {
      delete payload.password;
    }

    try {
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.success) {
        setShowUserModal(false);
        fetchUsers();
      } else {
        setFormError(data.message || data.errors?.map((e) => e.msg).join(', ') || 'Error saving user');
      }
    } catch (err) {
      setFormError('Network error');
    } finally {
      setFormLoading(false);
    }
  };

  // ── Delete User ─────────────────────────────────────────────────────────────
  const handleDeleteClick = (user) => {
    setUserToDelete(user);
    setShowDeleteConfirm(true);
  };

  const handleConfirmDelete = async () => {
    if (!userToDelete) return;
    try {
      const res = await fetch(`${API_BASE}/api/users/${userToDelete._id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setShowDeleteConfirm(false);
        setUserToDelete(null);
        fetchUsers();
      }
    } catch (err) {
      console.error('Failed to delete user', err);
    }
  };

  // ── Open Assign Modal ──────────────────────────────────────────────────────
  const handleAssignDevice = async (user) => {
    setSelectedUser(user);
    setAssignError('');
    setAssignedLocations(user.assignedLocations || []);
    setAssignedDeviceIds(
      (user.assignedDevices || []).map((d) => (typeof d === 'string' ? d : d._id))
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
    if (!selectedUser) return;
    setAssignLoading(true);
    setAssignError('');

    try {
      const res = await fetch(`${API_BASE}/api/users/${selectedUser._id}/assign`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          assignedLocations,
          assignedDevices: assignedDeviceIds,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setShowAssignModal(false);
        fetchUsers();
      } else {
        setAssignError(data.message || 'Error assigning');
      }
    } catch (err) {
      setAssignError('Network error');
    } finally {
      setAssignLoading(false);
    }
  };

  // ── Toggle Status ───────────────────────────────────────────────────────────
  const handleToggleStatus = async (userId) => {
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}/toggle-status`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) fetchUsers();
    } catch (err) {
      console.error('Failed to toggle status', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">User Management</h2>
          <p className="text-sm text-slate-400">{users.length} registered users</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search users..."
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 py-2.5 pl-10 pr-4 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 sm:w-64"
            />
          </div>
          <button
            onClick={() => handleOpenUserModal()}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20 transition-all hover:shadow-green-500/30"
          >
            <Plus className="h-4 w-4" /> Add User
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <SkeletonTable rows={5} cols={6} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Users} title="No users found" description="No users match your search criteria." />
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/50 bg-slate-800/30 backdrop-blur-sm"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">User</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Role</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Locations</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Devices</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Status</th>
                <th className="px-6 py-4 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((user) => {
                const RoleIcon = roleIcon[user.role] || Users;
                const userDevices = user.assignedDevices || [];
                const userLocations = user.assignedLocations || [];
                return (
                  <tr key={user._id} className="border-b border-slate-700/30 transition-colors hover:bg-slate-800/50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-green-500 to-emerald-400 text-xs font-bold text-white">
                          {user.name.split(' ').map((n) => n[0]).join('').toUpperCase()}
                        </div>
                        <div>
                          <p className="font-medium text-white">{user.name}</p>
                          <p className="text-xs text-slate-500">{user.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${roleBadge[user.role] || roleBadge.viewer}`}>
                        <RoleIcon className="h-3 w-3" />
                        {user.role}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-1">
                        {userLocations.length === 0 ? (
                          <span className="text-[10px] text-slate-500 italic">None</span>
                        ) : (
                          <>
                            {userLocations.slice(0, 2).map((loc) => (
                              <span key={loc} className="rounded-md bg-slate-700/50 px-2 py-0.5 text-[10px] text-slate-300">
                                {loc}
                              </span>
                            ))}
                            {userLocations.length > 2 && (
                              <span className="rounded-md bg-slate-700/50 px-2 py-0.5 text-[10px] text-slate-400">
                                +{userLocations.length - 2}
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-slate-300">
                        {userDevices.length === 0
                          ? 'None'
                          : `${userDevices.length} device${userDevices.length > 1 ? 's' : ''}`}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <button
                        onClick={() => handleToggleStatus(user._id)}
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase cursor-pointer transition-all hover:opacity-80 ${
                          user.status === 'active'
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : 'bg-slate-500/10 text-slate-500'
                        }`}
                        title="Click to toggle status"
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            user.status === 'active' ? 'bg-emerald-400' : 'bg-slate-500'
                          }`}
                        />
                        {user.status}
                      </button>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleAssignDevice(user)}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-green-500/10 hover:text-green-400"
                          title="Assign Devices"
                        >
                          <UserCog className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => handleOpenUserModal(user)}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-700 hover:text-white"
                          title="Edit"
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => handleToggleStatus(user._id)}
                          className={`rounded-lg p-2 text-slate-400 transition-colors ${
                            user.status === 'active'
                              ? 'hover:bg-orange-500/10 hover:text-orange-400'
                              : 'hover:bg-emerald-500/10 hover:text-emerald-400'
                          }`}
                          title={user.status === 'active' ? 'Block User' : 'Unblock User'}
                        >
                          {user.status === 'active'
                            ? <Ban className="h-4 w-4" />
                            : <CheckCircle className="h-4 w-4" />}
                        </button>
                        <button
                          onClick={() => handleDeleteClick(user)}
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

      {/* ══════════════════════════════════════════════════════════════════════
          ADD / EDIT USER MODAL
      ══════════════════════════════════════════════════════════════════════ */}
      <Modal
        isOpen={showUserModal}
        onClose={() => setShowUserModal(false)}
        title={editingUser ? 'Edit User' : 'Add New User'}
        size="sm"
      >
        <form onSubmit={handleSubmitUser} className="space-y-4">
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
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
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
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
              placeholder="john@example.com"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">
              Password {editingUser && <span className="text-slate-500 font-normal">(leave empty to keep current)</span>}
            </label>
            <input
              type="password"
              required={!editingUser}
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
              placeholder={editingUser ? '••••••••' : 'Min 6 characters'}
              minLength={formData.password ? 6 : undefined}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Role</label>
            <select
              value={formData.role}
              onChange={(e) => setFormData({ ...formData, role: e.target.value })}
              className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r.charAt(0).toUpperCase() + r.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <div className="pt-4 flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setShowUserModal(false)}
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={formLoading}
              className="rounded-xl border border-transparent bg-gradient-to-r from-green-500 to-emerald-500 px-6 py-2 text-sm font-semibold text-white shadow-lg shadow-green-500/20 disabled:opacity-50"
            >
              {formLoading ? 'Saving...' : editingUser ? 'Update User' : 'Create User'}
            </button>
          </div>
        </form>
      </Modal>

      {/* ══════════════════════════════════════════════════════════════════════
          ASSIGN DEVICES / LOCATIONS MODAL
      ══════════════════════════════════════════════════════════════════════ */}
      <Modal isOpen={showAssignModal} onClose={() => setShowAssignModal(false)} title="Assign Devices & Locations" size="lg">
        {selectedUser && (
          <div className="space-y-5">
            {/* User info */}
            <div className="flex items-center gap-3 rounded-xl bg-slate-900/50 p-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-green-500 to-emerald-400 text-sm font-bold text-white">
                {selectedUser.name.split(' ').map((n) => n[0]).join('').toUpperCase()}
              </div>
              <div>
                <p className="font-medium text-white">{selectedUser.name}</p>
                <p className="text-xs text-slate-500">{selectedUser.email} · {selectedUser.role}</p>
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
              <div className="space-y-2 flex flex-wrap items-start justify-start max-h-60 overflow-y-scroll">
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
                        className="rounded border-slate-600 bg-slate-800 text-green-500 focus:ring-green-500/20"
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
                          className="rounded border-slate-600 bg-slate-800 text-green-500 focus:ring-green-500/20"
                        />
                        <span className="text-xs text-slate-300">{dev.name}</span>
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
                className="rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20 disabled:opacity-50"
              >
                {assignLoading ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* ══════════════════════════════════════════════════════════════════════
          DELETE CONFIRMATION MODAL
      ══════════════════════════════════════════════════════════════════════ */}
      <Modal isOpen={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)} title="Delete User" size="sm">
        {userToDelete && (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-500/10 shrink-0">
                <AlertTriangle className="h-5 w-5 text-red-400" />
              </div>
              <div>
                <p className="text-sm text-slate-300">
                  Are you sure you want to delete <strong className="text-white">{userToDelete.name}</strong>?
                  This action cannot be undone.
                </p>
                <p className="mt-1 text-xs text-slate-500">{userToDelete.email}</p>
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
                Delete User
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default UserManagement;
