import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { Cpu, Search, Plus, MapPin, Activity, Edit2, Trash2, PowerOff, ShieldAlert, Radio, Info, Copy, Check, Calendar, Clock } from 'lucide-react';
import { getStatusBg, getStatusDot, formatTimestamp } from '../../utils/helpers';
import { SkeletonTable } from '../../components/Skeleton';
import EmptyState from '../../components/EmptyState';
import Modal from '../../components/Modal';

const EMPTY_FORM = {
  name: '',
  location: '',
  status: 'offline',
  deviceType: 'system2',
  mqttId: '',
  clientName: '',
  locationCode: '',
  model: '',
  unit: '',
  nicknameByClient: '',
  thingspeak: {
    port: 1883,
  },
};

const DevicesPage = () => {
  const [loading, setLoading] = useState(true);
  const [devices, setDevices] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const navigate = useNavigate();

  // Modal & Form State
  const [showModal, setShowModal] = useState(false);
  const [editingDevice, setEditingDevice] = useState(null);
  const [formData, setFormData] = useState(EMPTY_FORM);
  const [formLoading, setFormLoading] = useState(false);
  const [error, setError] = useState(null);

  // Details Modal State
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [selectedDeviceIdDetails, setSelectedDeviceIdDetails] = useState(null);
  const selectedDeviceDetails = devices.find(d => (d._id || d.id) === selectedDeviceIdDetails);
  const [copiedId, setCopiedId] = useState(false);

  const token = localStorage.getItem('token');
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const isAdmin = user.accountType === 'admin' || user.accountType === 'superadmin';
  const isSuperAdmin = user.accountType === 'superadmin';
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Fetch devices
  const fetchDevices = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/devices`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const contentType = res.headers.get("content-type");
      if (!contentType || !contentType.includes("application/json")) {
        throw new Error("Received non-JSON response from server (Backend might be down)");
      }
      const data = await res.json();
      if (data.success) {
        setDevices(data.data);
      }
    } catch (error) {
      console.error('Failed to fetch devices', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDevices();
  }, [token]);

  // Open Modal
  const handleOpenModal = (device = null) => {
    if (!isAdmin) return;
    setError(null);
    if (device) {
      setEditingDevice(device);
      setFormData({
        name: device.name,
        location: device.location,
        status: device.status,
        deviceType: device.deviceType,
        mqttId: device.mqttId || '',
        clientName: device.clientName || '',
        locationCode: device.locationCode || '',
        model: device.model || '',
        unit: device.unit || '',
        nicknameByClient: device.nicknameByClient || '',
        thingspeak: {
          port: device.thingspeak?.port || 1883,
        },
      });
    } else {
      setEditingDevice(null);
      setFormData(EMPTY_FORM);
    }
    setShowModal(true);
  };

  // Submit Form (Create / Update)
  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormLoading(true);
    setError(null);

    const url = editingDevice ? `${API_BASE}/api/devices/${editingDevice._id}` : `${API_BASE}/api/devices`;
    const method = editingDevice ? 'PUT' : 'POST';

    try {
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(formData),
      });
      const contentType = res.headers.get("content-type");
      if (!contentType || !contentType.includes("application/json")) {
        throw new Error("Received non-JSON response from server (Backend might be down)");
      }
      const data = await res.json();
      if (data.success) {
        setShowModal(false);
        fetchDevices();
      } else {
        setError(data.message || 'Error saving device');
      }
    } catch (err) {
      setError('Network error');
    } finally {
      setFormLoading(false);
    }
  };

  // Delete Device
  const handleDelete = async (id) => {
    if (!isAdmin || !confirm('Are you sure you want to delete this device?')) return;
    try {
      const res = await fetch(`${API_BASE}/api/devices/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) fetchDevices();
    } catch (error) {
      console.error('Failed to delete', error);
    }
  };

  // Toggle Block Status
  const handleToggleBlock = async (id) => {
    if (!isSuperAdmin) return;
    try {
      const res = await fetch(`${API_BASE}/api/devices/${id}/block`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) fetchDevices();
    } catch (error) {
      console.error('Failed to block/unblock', error);
    }
  };

  const filtered = devices.filter((d) => {
    const searchId = String(d._id || d.id || '');
    const mqttId = String(d.mqttId || '');
    const matchesSearch =
      String(d.name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      searchId.toLowerCase().includes(searchTerm.toLowerCase()) ||
      String(d.location || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      mqttId.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'all' || d.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">All Devices</h2>
          <p className="text-sm text-slate-400">{devices.length} sensors deployed</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search devices..."
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 py-2.5 pl-10 pr-4 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 sm:w-64"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2.5 text-sm text-white outline-none focus:border-green-500"
          >
            <option value="all">All Status</option>
            <option value="online">Online</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
            <option value="offline">Offline</option>
            <option value="blocked">Blocked</option>
          </select>
          {isAdmin && (
            <button
              onClick={() => handleOpenModal()}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20"
            >
              <Plus className="h-4 w-4" /> Add Device
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <SkeletonTable rows={8} cols={7} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Cpu} title="No devices found" description="No devices match your search or filter criteria." />
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/50 bg-slate-800/30 backdrop-blur-sm"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Device</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Location</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Status</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Device ID / MQTT ID</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Last Updated</th>
                <th className="px-6 py-4 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((device) => {
                const deviceId = device._id || device.id;
                const isBlocked = device.status === 'blocked';
                const hasThingspeak = device.thingspeak?.channelId || device.thingspeak?.tempChannelId;
                return (
                  <tr key={deviceId} className="border-b border-slate-700/30 transition-colors hover:bg-slate-800/50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className={`rounded-lg p-2 ${isBlocked ? 'bg-red-500/10' : 'bg-green-500/10'}`}>
                          <Cpu className={`h-4 w-4 ${isBlocked ? 'text-red-400' : 'text-green-400'}`} />
                        </div>
                        <div>
                          <p className={`font-medium ${isBlocked ? 'text-slate-400 line-through' : 'text-white'}`}>{device.name}</p>
                          <p className="text-[10px] text-slate-500 font-mono">{deviceId.substring(0, 8)}...</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1.5 text-slate-400">
                        <MapPin className="h-3.5 w-3.5" />
                        {device.location}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${isBlocked ? 'bg-slate-800 border-slate-700 text-slate-400' : getStatusBg(device.status)}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${isBlocked ? 'bg-slate-500' : getStatusDot(device.status)}`} />
                        {device.status}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1.5 font-mono text-xs text-blue-400">
                        <Radio className="h-3.5 w-3.5" />
                        <span>{device.mqttId || deviceId}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-400 text-xs">{formatTimestamp(device.lastUpdated)}</td>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => {
                            setSelectedDeviceIdDetails(deviceId);
                            setShowDetailsModal(true);
                            setShowDetailsPassword(false);
                            setShowDetailsWriteKey(false);
                            setShowDetailsReadKey(false);
                          }}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-blue-500/10 hover:text-blue-400"
                          title="View Device Details"
                        >
                          <Info className="h-4 w-4" />
                        </button>

                        <button
                          onClick={() => navigate(`/monitoring?device=${deviceId}`)}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-green-500/10 hover:text-green-400"
                          title="View Live Data"
                        >
                          <Activity className="h-4 w-4" />
                        </button>

                        {isAdmin && (
                          <>
                            <div className="w-px h-4 bg-slate-700/50 mx-1"></div>

                            {isSuperAdmin && (
                              <button
                                onClick={() => handleToggleBlock(deviceId)}
                                className={`rounded-lg p-2 transition-colors ${isBlocked ? 'text-orange-400 hover:bg-orange-500/10' : 'text-slate-400 hover:bg-slate-700 hover:text-white'}`}
                                title={isBlocked ? "Unblock Device" : "Block Device"}
                              >
                                <PowerOff className="h-4 w-4" />
                              </button>
                            )}
                            <button
                              onClick={() => handleOpenModal(device)}
                              className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-blue-500/10 hover:text-blue-400"
                              title="Edit"
                            >
                              <Edit2 className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => handleDelete(deviceId)}
                              className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
                              title="Delete"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      )}

      {/* ADD/EDIT DEVICE MODAL */}
      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title={editingDevice ? 'Edit Device' : 'Add New Device'} size="md">
        <form onSubmit={handleSubmit} className="flex flex-col max-h-[85vh]">
          {/* Scrollable Content */}
          <div className="flex-1 overflow-y-auto pr-3 space-y-6 custom-scrollbar">
            {error && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-3 flex gap-2 text-red-400 text-sm">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <p>{error}</p>
              </div>
            )}

            {/* Device Info Section */}
            <div className="space-y-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-2">
                <Cpu className="h-3.5 w-3.5" /> Device Information
              </h4>
              <div className="space-y-3 pl-1">
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-300">Device Name</label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    placeholder="e.g. Node-Alpha-01"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-300">Location</label>
                  <input
                    type="text"
                    required
                    value={formData.location}
                    onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    placeholder="e.g. Greenhouse 1, Sector A"
                  />
                </div>



                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-300">Device Type</label>
                  <select
                    value={formData.deviceType}
                    onChange={(e) => setFormData({ ...formData, deviceType: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                  >
                    <option value="system2">Standard System (system2.py)</option>
                    <option value="controlling">InHydro Controller (controlling.py)</option>
                    <option value="monit">Monnet Controller (monit.py)</option>
                    <option value="monnet">Monnet Controller (monnet.py)</option>
                    <option value="almora">Almora Machine (almora1.py)</option>
                    <option value="almora2">Almora Machine 2 (CO2/Temp/Hum)</option>
                    <option value="almora2_full">Almora Machine 2 Full Controller (almora2_full.py)</option>
                    <option value="multi_sensor">Cold Storage (Multi-Sensor)</option>
                    <option value="light_motor_pump">Light Motor Pump (esp8266_controller)</option>
                    <option value="office_control">Office Control (control.py)</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-300">Device ID / MQTT Topic ID (e.g. almora1) *Required*</label>
                  <input
                    type="text"
                    required
                    value={formData.mqttId}
                    onChange={(e) => setFormData({ ...formData, mqttId: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    placeholder="Must match device_id.txt on Raspberry Pi"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="mb-1 block text-sm font-medium text-slate-300">Client Name</label>
                    <input
                      type="text"
                      value={formData.clientName || ''}
                      onChange={(e) => setFormData({ ...formData, clientName: e.target.value })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                      placeholder="e.g. Acme Corp"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-slate-300">Nickname by Client</label>
                    <input
                      type="text"
                      value={formData.nicknameByClient || ''}
                      onChange={(e) => setFormData({ ...formData, nicknameByClient: e.target.value })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                      placeholder="e.g. Pump-01"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="mb-1 block text-sm font-medium text-slate-300">Location Code</label>
                    <input
                      type="text"
                      value={formData.locationCode || ''}
                      onChange={(e) => setFormData({ ...formData, locationCode: e.target.value })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                      placeholder="e.g. LOC-012"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-slate-300">Model</label>
                    <input
                      type="text"
                      value={formData.model || ''}
                      onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                      placeholder="e.g. Inhydro-V3"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="mb-1 block text-sm font-medium text-slate-300">Unit</label>
                    <input
                      type="text"
                      value={formData.unit || ''}
                      onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                      placeholder="e.g. Unit-A"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-slate-300">MQTT Port</label>
                    <input
                      type="number"
                      value={formData.thingspeak?.port || 1883}
                      onChange={(e) => setFormData({
                        ...formData,
                        thingspeak: { ...(formData.thingspeak || {}), port: Number(e.target.value) || 1883 }
                      })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                      placeholder="1883"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Persistent Footer */}
          <div className="pt-6 flex justify-end gap-3 border-t border-slate-700/50 mt-4 bg-slate-900/10">
            <button
              type="button"
              onClick={() => setShowModal(false)}
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={formLoading}
              className="rounded-xl border border-transparent bg-green-500 px-6 py-2 text-sm font-semibold text-white shadow-lg shadow-green-500/20 hover:bg-green-600 disabled:opacity-50 transition-all"
            >
              {formLoading ? 'Saving...' : 'Save Device'}
            </button>
          </div>
        </form>
      </Modal>

      {/* DEVICE DETAILS MODAL */}
      <Modal
        isOpen={showDetailsModal}
        onClose={() => {
          setShowDetailsModal(false);
          setSelectedDeviceIdDetails(null);
        }}
        title="Device Details"
        size="lg"
      >
        {selectedDeviceDetails && (
          <div className="flex flex-col max-h-[85vh] text-slate-200">
            {/* Scrollable Content */}
            <div className="flex-1 overflow-y-auto pr-2 space-y-6 custom-scrollbar pb-4">

              {/* Header Info */}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between bg-slate-900/30 p-4 rounded-xl border border-slate-700/30">
                <div className="flex items-center gap-3">
                  <div className={`rounded-xl p-3 ${selectedDeviceDetails.status === 'blocked' ? 'bg-red-500/10' : 'bg-green-500/10'}`}>
                    <Cpu className={`h-6 w-6 ${selectedDeviceDetails.status === 'blocked' ? 'text-red-400' : 'text-green-400'}`} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-white leading-tight">{selectedDeviceDetails.name}</h3>
                    <p className="text-xs text-slate-400 mt-1 font-mono">
                      Type: <span className="text-slate-300 font-semibold">{
                        selectedDeviceDetails.deviceType === 'system2' ? 'Standard System' :
                          selectedDeviceDetails.deviceType === 'controlling' ? 'InHydro Controller' :
                            selectedDeviceDetails.deviceType === 'almora' ? 'Almora Machine' :
                              selectedDeviceDetails.deviceType === 'almora2' ? 'Almora Machine 2' :
                                selectedDeviceDetails.deviceType === 'multi_sensor' ? 'Cold Storage (Multi)' :
                                  selectedDeviceDetails.deviceType === 'light_motor_pump' ? 'Light Motor Pump' :
                                    selectedDeviceDetails.deviceType === 'office_control' ? 'Office Control' :
                                      selectedDeviceDetails.deviceType === 'monit' || selectedDeviceDetails.deviceType === 'monnet' ? 'Monnet Controller' :
                                        selectedDeviceDetails.deviceType || 'Unknown'
                      }</span>
                    </p>
                  </div>
                </div>
                <div>
                  <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider ${selectedDeviceDetails.status === 'blocked' ? 'bg-slate-800 border-slate-700 text-slate-400' : getStatusBg(selectedDeviceDetails.status)}`}>
                    <span className={`h-2 w-2 rounded-full ${selectedDeviceDetails.status === 'blocked' ? 'bg-slate-500' : getStatusDot(selectedDeviceDetails.status)}`} />
                    {selectedDeviceDetails.status}
                  </span>
                </div>
              </div>

              {/* Grid Content */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

                {/* General Details Card */}
                <div className="rounded-xl border border-slate-700/30 bg-slate-900/10 p-5 space-y-4">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-700/50 pb-2 flex items-center gap-1.5">
                    <Cpu className="h-4 w-4 text-green-400" /> General Specifications
                  </h4>

                  <div className="space-y-3.5 text-sm">
                    <div className="flex justify-between items-center py-0.5">
                      <span className="text-slate-400 font-medium">Device ID</span>
                      <div className="flex items-center gap-1.5 font-mono text-xs bg-slate-900/60 px-2 py-1 rounded border border-slate-700/50 max-w-[180px] sm:max-w-xs">
                        <span className="truncate text-slate-300">{selectedDeviceDetails._id || selectedDeviceDetails.id}</span>
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard.writeText(selectedDeviceDetails._id || selectedDeviceDetails.id);
                            setCopiedId(true);
                            setTimeout(() => setCopiedId(false), 2000);
                          }}
                          className="text-slate-400 hover:text-white transition-colors p-0.5"
                          title="Copy ID"
                        >
                          {copiedId ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
                        </button>
                      </div>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">Location</span>
                      <span className="text-white flex items-center gap-1">
                        <MapPin className="h-3.5 w-3.5 text-slate-400" />
                        {selectedDeviceDetails.location}
                      </span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">MQTT Topic ID</span>
                      <span className="text-white font-mono text-xs bg-slate-900/40 px-2 py-0.5 rounded border border-slate-700/30">
                        {selectedDeviceDetails.mqttId || 'Not set'}
                      </span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">Client Name</span>
                      <span className="text-white font-semibold">{selectedDeviceDetails.clientName || 'Not set'}</span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">Nickname by Client</span>
                      <span className="text-white italic">{selectedDeviceDetails.nicknameByClient || 'Not set'}</span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">Location Code</span>
                      <span className="text-white font-mono text-xs">{selectedDeviceDetails.locationCode || 'Not set'}</span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">Model</span>
                      <span className="text-white">{selectedDeviceDetails.model || 'Not set'}</span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">Unit</span>
                      <span className="text-white font-mono text-xs">{selectedDeviceDetails.unit || 'Not set'}</span>
                    </div>

                    <div className="flex justify-between items-center border-t border-slate-800/60 pt-2.5">
                      <span className="text-slate-400 font-medium">MQTT Port</span>
                      <span className="text-white font-mono text-xs bg-slate-900/40 px-2 py-0.5 rounded border border-slate-700/30">
                        {selectedDeviceDetails.thingspeak?.port || 1883}
                      </span>
                    </div>
                  </div>
                </div>

                {/* System Timestamps & Diagnostics */}
                <div className="rounded-xl border border-slate-700/30 bg-slate-900/10 p-5 space-y-4">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-700/50 pb-2 flex items-center gap-1.5">
                    <Activity className="h-4 w-4 text-green-400" /> Activity & Diagnostics
                  </h4>

                  <div className="space-y-4 text-sm">
                    <div className="flex items-start gap-3">
                      <div className="p-2 rounded-lg bg-slate-800 text-slate-400 mt-0.5">
                        <Clock className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-xs text-slate-400 font-medium">Last Connection / Update</p>
                        <p className="text-white mt-0.5 font-medium">{formatTimestamp(selectedDeviceDetails.lastUpdated)}</p>
                      </div>
                    </div>

                    <div className="flex items-start gap-3 border-t border-slate-800/60 pt-3">
                      <div className="p-2 rounded-lg bg-slate-800 text-slate-400 mt-0.5">
                        <Calendar className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-xs text-slate-400 font-medium">Created On</p>
                        <p className="text-white mt-0.5 font-medium">{selectedDeviceDetails.createdAt ? new Date(selectedDeviceDetails.createdAt).toLocaleString() : 'N/A'}</p>
                      </div>
                    </div>

                    <div className="flex items-start gap-3 border-t border-slate-800/60 pt-3">
                      <div className="p-2 rounded-lg bg-slate-800 text-slate-400 mt-0.5">
                        <Calendar className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-xs text-slate-400 font-medium">Last Modified</p>
                        <p className="text-white mt-0.5 font-medium">{selectedDeviceDetails.updatedAt ? new Date(selectedDeviceDetails.updatedAt).toLocaleString() : 'N/A'}</p>
                      </div>
                    </div>
                  </div>
                </div>

              </div>
            </div>

            {/* Persistent Footer Actions */}
            <div className="pt-4 flex flex-wrap justify-between items-center gap-3 border-t border-slate-700/50 mt-4 bg-slate-800">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowDetailsModal(false);
                    navigate(`/monitoring?device=${selectedDeviceDetails._id || selectedDeviceDetails.id}`);
                  }}
                  className="flex items-center gap-1.5 rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-2 text-xs font-semibold text-green-400 hover:bg-green-500 hover:text-white transition-all shadow-md shadow-green-500/5"
                >
                  <Activity className="h-3.5 w-3.5" /> Live Monitoring
                </button>
              </div>

              <button
                type="button"
                onClick={() => {
                  setShowDetailsModal(false);
                  setSelectedDeviceIdDetails(null);
                }}
                className="rounded-xl border border-slate-700 px-5 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default DevicesPage;
