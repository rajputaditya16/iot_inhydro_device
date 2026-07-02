import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { User, Bell, Shield, Palette, Globe, Save, Moon, Sun, Monitor, Settings, CheckCircle2, X, Eye, EyeOff, AlertCircle } from 'lucide-react';
import DeviceSettings from '../AdminDashboard/DeviceSettings';
import AlmoraSettings from '../AdminDashboard/AlmoraSettings';
import Almora2Settings from '../AdminDashboard/Almora2Settings';
import ColdStorageSettings from '../AdminDashboard/ColdStorageSettings';
import LightMotorPumpSettings from '../AdminDashboard/LightMotorPumpSettings';
import OfficeControlSettings from '../AdminDashboard/OfficeControlSettings';
import ControllingDeviceSettings from '../AdminDashboard/ControllingDeviceSettings';

const SettingsPage = () => {
  const [activeTab, setActiveTab] = useState('profile');
  
  const [currentUser, setCurrentUser] = useState({ name: 'User', email: '', role: 'user' });
  const [showPopup, setShowPopup] = useState(false);
  const [popupText, setPopupText] = useState('');
  const [popupType, setPopupType] = useState('success'); // 'success' or 'error'

  const [nameInput, setNameInput] = useState('');
  const [emailInput, setEmailInput] = useState('');

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const handleSaveSettings = async (e) => {
    e.preventDefault();

    const triggerPopup = (text, type = 'success') => {
      setPopupText(text);
      setPopupType(type);
      setShowPopup(true);
      setTimeout(() => {
        setShowPopup(false);
      }, 4000);
    };

    if (!nameInput.trim()) {
      triggerPopup("Name cannot be empty.", "error");
      return;
    }
    if (!emailInput.trim()) {
      triggerPopup("Email cannot be empty.", "error");
      return;
    }

    const payload = {
      name: nameInput.trim(),
      email: emailInput.trim().toLowerCase(),
    };

    if (currentPassword || newPassword || confirmPassword) {
      if (!currentPassword) {
        triggerPopup("Please enter your current password to authorize updates.", "error");
        return;
      }
      if (!newPassword || !confirmPassword) {
        triggerPopup("Please enter and confirm your new password.", "error");
        return;
      }
      if (newPassword !== confirmPassword) {
        triggerPopup("New passwords do not match.", "error");
        return;
      }
      if (newPassword.length < 6) {
        triggerPopup("New password must be at least 6 characters.", "error");
        return;
      }
      payload.password = newPassword;
      payload.currentPassword = currentPassword;
    } else {
      if (!currentPassword) {
        triggerPopup("Please enter your current password under Security Settings to authorize changes.", "error");
        return;
      }
      payload.currentPassword = currentPassword;
    }

    try {
      const token = localStorage.getItem('token');
      const API_BASE = import.meta.env.VITE_API_URL || '';
      
      const res = await fetch(`${API_BASE}/api/auth/update-profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      
      const data = await res.json();
      
      if (res.ok && data.success) {
        const updatedUser = {
          ...currentUser,
          name: data.user.name,
          email: data.user.email,
          role: data.user.role || currentUser.role
        };
        setCurrentUser(updatedUser);
        
        const storedUser = localStorage.getItem('user');
        if (storedUser) {
          const parsedUser = JSON.parse(storedUser);
          const newStoredUser = {
            ...parsedUser,
            name: data.user.name,
            email: data.user.email,
            role: data.user.role || parsedUser.role,
            accountType: data.user.accountType || parsedUser.accountType || data.user.role
          };
          localStorage.setItem('user', JSON.stringify(newStoredUser));
        }

        triggerPopup(payload.password ? "Settings and password updated successfully!" : "Settings saved successfully!", "success");
        
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
      } else {
        triggerPopup(data.message || "Failed to update profile settings.", "error");
      }
    } catch (err) {
      console.error(err);
      triggerPopup("Network error while saving changes.", "error");
    }
  };

  useEffect(() => {
    try {
      const storedUser = localStorage.getItem('user');
      if (storedUser) {
        const parsedUser = JSON.parse(storedUser);
        const userInfo = {
          name: parsedUser.firstName ? `${parsedUser.firstName} ${parsedUser.lastName || ''}`.trim() : (parsedUser.name || parsedUser.username || 'User'),
          email: parsedUser.email || '',
          role: parsedUser.accountType || parsedUser.role || 'user'
        };
        setCurrentUser(userInfo);
        setNameInput(userInfo.name);
        setEmailInput(userInfo.email);
      }
    } catch (error) {
      console.error('Error parsing user data from localStorage', error);
    }
  }, []);
  const tabs = [
    { key: 'profile', label: 'Profile', icon: User },
    ...((currentUser.role === 'admin' || currentUser.role === 'superadmin') ? [
      {key: 'device_config', label: 'Device Control', icon: Settings},
      {key: 'almora_config', label: 'Almora Setup', icon: Monitor},
      {key: 'almora2_config', label: 'Almora Setup 2', icon: Monitor},
      {key: 'cold_storage_config', label: 'Cold Storage Setup', icon: Monitor},
      {key: 'light_motor_pump_config', label: 'Light Motor Pump Setup', icon: Monitor},
      {key: 'office_control_config', label: 'Office Control Setup', icon: Monitor},
      {key: 'controlling_config', label: 'Controller Setup', icon: Monitor},
    ] : []),
    // { key: 'notifications', label: 'Notifications', icon: Bell },
    // { key: 'appearance', label: 'Appearance', icon: Palette },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white">Settings</h2>
        <p className="text-sm text-slate-400">Manage your account and preferences</p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Tab Navigation */}
        <div className="w-full lg:w-56 shrink-0">
          <div className="flex gap-1 lg:flex-col rounded-xl bg-slate-800/30 p-1">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
               className={`flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-all ${activeTab === tab.key
                    ? 'bg-green-500/10 text-green-400'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                }`}
              >
                <tab.icon className="h-4 w-4 shrink-0" />
                <span className="hidden lg:block">{tab.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            className="rounded-2xl border border-slate-700/50 bg-slate-800/30 p-6"
          >
            {/* Device Control */}
            {activeTab === 'device_config' && (
              <DeviceSettings />
            )}

            {/* Almora Control */}
            {activeTab === 'almora_config' && (
              <AlmoraSettings />
            )}
            
            {/* Almora 2 Control */}
            {activeTab === 'almora2_config' && (
              <Almora2Settings />
            )}

            {/* Cold Storage (Multi-Sensor) Control */}
            {activeTab === 'cold_storage_config' && (
              <ColdStorageSettings />
            )}

            {/* Light Motor Pump Control */}
            {activeTab === 'light_motor_pump_config' && (
              <LightMotorPumpSettings/>
            )}

            {/* Office Control */}
            {activeTab === 'office_control_config' && (
              <OfficeControlSettings />
            )}

            {/* InHydro Controller */}
            {activeTab === 'controlling_config' && (
              <ControllingDeviceSettings />
            )}

            {/* Profile */}
            {activeTab === 'profile' && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-base font-semibold text-white mb-4">Profile Settings</h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">Full Name</label>
                      <input
                        type="text"
                        value={nameInput}
                        onChange={(e) => setNameInput(e.target.value)}
                        className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">Email</label>
                      <input
                        type="email"
                        value={emailInput}
                        onChange={(e) => setEmailInput(e.target.value)}
                        className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">Role</label>
                      <input
                        type="text"
                        value={currentUser.role}
                        disabled
                        className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-slate-500 outline-none uppercase"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">Timezone</label>
                      <select className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white outline-none focus:border-blue-500">
                        <option>Asia/Kolkata (IST)</option>
                        <option>UTC</option>
                        <option>America/New_York (EST)</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div className="border-t border-slate-700/50 pt-6">
                  <h3 className="text-base font-semibold text-white mb-4">Security Settings</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">Current Password</label>
                      <div className="relative">
                        <input
                          type={showCurrentPassword ? 'text' : 'password'}
                          placeholder="Enter current password"
                          value={currentPassword}
                          onChange={(e) => setCurrentPassword(e.target.value)}
                          className="w-full rounded-xl border border-slate-700 bg-slate-900/50 pl-4 pr-10 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                        >
                          {showCurrentPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">New Password</label>
                      <div className="relative">
                        <input
                          type={showNewPassword ? 'text' : 'password'}
                          placeholder="Enter new password"
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          className="w-full rounded-xl border border-slate-700 bg-slate-900/50 pl-4 pr-10 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => setShowNewPassword(!showNewPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                        >
                          {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-400">Confirm New Password</label>
                      <div className="relative">
                        <input
                          type={showConfirmPassword ? 'text' : 'password'}
                          placeholder="Confirm new password"
                          value={confirmPassword}
                          onChange={(e) => setConfirmPassword(e.target.value)}
                          className="w-full rounded-xl border border-slate-700 bg-slate-900/50 pl-4 pr-10 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                        >
                          {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="pt-4 border-t border-slate-700/30">
                  <button 
                    onClick={handleSaveSettings}
                    className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20 active:scale-95 transition-all"
                  >
                    <Save className="h-4 w-4" /> Save Changes
                  </button>
                </div>
              </div>
            )}

          </motion.div>
        </div>
      </div>

      {/* Toast Notification */}
      <AnimatePresence>
        {showPopup && (
          <motion.div
            initial={{ opacity: 0, y: 50, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.9 }}
            className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-2xl border bg-slate-900/90 px-4 py-3 shadow-xl backdrop-blur-md ${
              popupType === 'error'
                ? 'border-rose-500/20 text-rose-400 shadow-rose-500/5'
                : 'border-emerald-500/20 text-emerald-400 shadow-emerald-500/5'
            }`}
          >
            <div className={`rounded-full p-1.5 ${
              popupType === 'error' ? 'bg-rose-500/10' : 'bg-emerald-500/10'
            }`}>
              {popupType === 'error' ? (
                <AlertCircle className="h-5 w-5 text-rose-400" />
              ) : (
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
              )}
            </div>
            <div className="pr-4">
              <p className="text-xs font-semibold text-white">
                {popupType === 'error' ? 'Action Failed' : 'Update Complete'}
              </p>
              <p className="text-[11px] text-slate-400">{popupText}</p>
            </div>
            <button
              onClick={() => setShowPopup(false)}
              className="text-slate-500 hover:text-slate-300 transition-colors p-1"
            >
              <X className="h-4 w-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SettingsPage;
