import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { User, Bell, Shield, Palette, Globe, Save, Moon, Sun, Monitor, Settings } from 'lucide-react';
import DeviceSettings from '../AdminDashboard/DeviceSettings';
import AlmoraSettings from '../AdminDashboard/AlmoraSettings';
import Almora2Settings from '../AdminDashboard/Almora2Settings';
import ColdStorageSettings from '../AdminDashboard/ColdStorageSettings';
import LightMotorPumpSettings from '../AdminDashboard/LightMotorPumpSettings';
import OfficeControlSettings from '../AdminDashboard/OfficeControlSettings';
import DimmableLightSettings from '../AdminDashboard/DimmableLightSettings';

const SettingsPage = () => {
  const [activeTab, setActiveTab] = useState('profile');
  
  const [currentUser, setCurrentUser] = useState({ name: 'User', email: '', role: 'user' });

  useEffect(() => {
    try {
      const storedUser = localStorage.getItem('user');
      if (storedUser) {
        const parsedUser = JSON.parse(storedUser);
        setCurrentUser({
          name: parsedUser.firstName ? `${parsedUser.firstName} ${parsedUser.lastName || ''}`.trim() : (parsedUser.name || parsedUser.username || 'User'),
          email: parsedUser.email || '',
          role: parsedUser.accountType || parsedUser.role || 'user'
        });
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
      {key: 'dimmable_light_config', label: 'Dimmable Light Setup', icon: Sun},
      {key: 'office_control_config', label: 'Office Control Setup', icon: Monitor},
    ] : []),
    // { key: 'notifications', label: 'Notifications', icon: Bell },
    { key: 'security', label: 'Security', icon: Shield },
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

            {/* Dimmable Light Control */}
            {activeTab === 'dimmable_light_config' && (
              <DimmableLightSettings />
            )}

            {/* Office Control */}
            {activeTab === 'office_control_config' && (
              <OfficeControlSettings />
            )}

            {/* Profile */}
            {activeTab === 'profile' && (
              <div className="space-y-6">
                <h3 className="text-base font-semibold text-white">Profile Settings</h3>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">Full Name</label>
                    <input
                      type="text"
                       defaultValue={currentUser.name}
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">Email</label>
                    <input
                      type="email"
                     defaultValue={currentUser.email}
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
                <button className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20">
                  <Save className="h-4 w-4" /> Save Changes
                </button>
              </div>
            )}

           
            {/* Security */}
            {activeTab === 'security' && (
              <div className="space-y-6">
                <h3 className="text-base font-semibold text-white">Security Settings</h3>
                <div className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">Current Password</label>
                    <input
                      type="password"
                      placeholder="Enter current password"
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">New Password</label>
                    <input
                      type="password"
                      placeholder="Enter new password"
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">Confirm New Password</label>
                    <input
                      type="password"
                      placeholder="Confirm new password"
                      className="w-full rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20"
                    />
                  </div>
                  <button className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20">
                    <Shield className="h-4 w-4" /> Update Password
                  </button>
                </div>

              </div>
            )}

          </motion.div>
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
