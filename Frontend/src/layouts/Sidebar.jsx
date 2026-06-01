import { NavLink, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import logo from '../assets/logo.webp';
import white_stoke from '../assets/white-stroke.png';
import {
  LayoutDashboard,
  Cpu,
  Activity,
  BarChart3,
  Users,
  Settings,
  LogOut,
  Shield,
  Snowflake,
  Droplets,
  Wind
} from 'lucide-react';

const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, path: '/dashboard' },
  { label: 'Devices', icon: Cpu, path: '/devices' },
  { label: 'Live Monitoring', icon: Activity, path: '/monitoring' },
  // { label: 'Cold Storage', icon: Snowflake, path: '/cold-storage', adminOnly: true },
  // { label: 'Almora Machine', icon: Droplets, path: '/almora-settings', adminOnly: true },
  // { label: 'Almora Machine 2', icon: Wind, path: '/almora2-settings', adminOnly: true },
  { label: 'Analytics', icon: BarChart3, path: '/analytics' },
  { label: 'User Management', icon: Users, path: '/users', adminOnly: true },
  { label: 'Admin Management', icon: Shield, path: '/admins', superadminOnly: true },
  { label: 'Settings', icon: Settings, path: '/settings' },
];

const Sidebar = ({ collapsed, isMobile = false, isOpen = true, onItemClick, userRole = 'admin' }) => {
  const navigate = useNavigate();
  const storedUser = (() => { try { return JSON.parse(localStorage.getItem('user') || '{}'); } catch { return {}; } })();
  const displayName = storedUser.name || 'User';
  const displayRole = storedUser.role || userRole;

  const handleLogout = () => {
    navigate('/login');
  };

  const filteredItems = navItems.filter(

    (item) => (!item.adminOnly || userRole === 'admin' || userRole === 'superadmin') &&
      (!item.superadminOnly || userRole === 'superadmin')
  );

  return (
    <motion.aside
      initial={false}
      animate={isMobile ? { x: isOpen ? 0 : -280, width: 260 } : { x: 0, width: collapsed ? 72 : 260 }}
      transition={{ duration: 0.3, ease: 'easeInOut' }}
      className="fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-slate-700/50 bg-slate-900/95 backdrop-blur-xl"
    >
      {/* Logo */}
      <div className="flex h-16 items-center justify-between px-4">
        <div className="flex items-center justify-center gap-2.5 overflow-hidden w-100" style={{
          marginTop: '2.5rem',
          padding: '30px',
          rotate: '15deg',
          // border: '1px solid #ccc',
          borderRadius: '30px',
          backgroundImage: `url(${white_stoke})`,
          backgroundSize: '100% 100%',
          backgroundPosition: 'top',
        }} >

          <img className='w-45 h-15 p-2' style={{ rotate: '-15deg', }} src={logo} alt="" srcset="" />
        </div>
      </div>

      {/* Navigation */}
      <nav className="mt-10 flex-1 space-y-1 overflow-y-auto px-3 border-1 border-slate-700/50 rounded-lg mx-3 py-4 mb-1">
        {filteredItems.map((item) => {
          let itemPath = item.path;
          if (item.label === 'Dashboard') {
            if (userRole === 'user') itemPath = '/user-dashboard';
            if (userRole === 'superadmin') itemPath = '/superadmin-dashboard';
          }
          return (
            <NavLink
              key={item.label}
              to={itemPath}
              onClick={onItemClick}
              className={({ isActive }) =>
                `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${isActive
                  ? 'bg-green-500/10 text-green-400 shadow-lg shadow-green-500/5'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                }`
              }
            >
              <item.icon className="h-5 w-5 shrink-0" />
              <AnimatePresence>
                {!collapsed && (
                  <motion.span
                    initial={{ opacity: 0, width: 0 }}
                    animate={{ opacity: 1, width: 'auto' }}
                    exit={{ opacity: 0, width: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden whitespace-nowrap"
                  >
                    {item.label}
                  </motion.span>
                )}
              </AnimatePresence>
            </NavLink>
          )
        })}
      </nav>

      {/* Bottom: user info + logout */}
      <div className="border-t border-slate-700/50 p-3 space-y-1">
        {/* User Info */}
        {!collapsed && (
          <div className="flex items-center gap-2.5 rounded-xl px-3 py-2.5 bg-slate-800/50 mb-1">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-green-500 to-emerald-400 text-xs font-bold text-white uppercase">
              {displayName.split(' ').map((n) => n[0]).join('').slice(0, 2)}
            </div>
            <div className="overflow-hidden">
              <p className="truncate text-xs font-semibold text-white">{displayName}</p>
              <p className={`text-[10px] font-semibold uppercase tracking-wider ${displayRole === 'superadmin' ? 'text-purple-400' :
                  displayRole === 'admin' ? 'text-red-400' : 'text-green-400'
                }`}>{displayRole}</p>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="flex justify-center mb-1">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-green-500 to-emerald-400 text-xs font-bold text-white uppercase" title={`${displayName} (${displayRole})`}>
              {displayName.split(' ').map((n) => n[0]).join('').slice(0, 2)}
            </div>
          </div>
        )}
        {/* Logout */}
        <button
          onClick={handleLogout}
          className="mt-1 flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-red-400/70 transition-colors hover:bg-red-500/10 hover:text-red-400"
        >
          <LogOut className="h-5 w-5 shrink-0" />
          <AnimatePresence>
            {!collapsed && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="overflow-hidden whitespace-nowrap"
              >
                Logout
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
