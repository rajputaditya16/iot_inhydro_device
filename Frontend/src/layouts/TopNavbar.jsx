import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bell, ChevronDown,Settings, LogOut, Wifi, WifiOff, Menu } from 'lucide-react';
import { mockNotifications} from '../data/mockData';
import { useNavigate } from 'react-router-dom';
// import { mockNotifications } from '../data/mockData';

const TopNavbar = ({ pageTitle, collapsed, setCollapsed }) => {
  const [showNotifications, setShowNotifications] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [isOnline] = useState(true);
  const notifRef = useRef(null);
  const profileRef = useRef(null);
  const navigate = useNavigate();
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

  const unreadCount = mockNotifications.filter((n) => !n.read).length;

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target)) setShowNotifications(false);
      if (profileRef.current && !profileRef.current.contains(e.target)) setShowProfile(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const notifTypeColors = {
    critical: 'bg-red-500',
    warning: 'bg-yellow-500',
    info: 'bg-blue-500',
    success: 'bg-emerald-500',
  };

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-slate-700/50 bg-slate-900/80 px-4 backdrop-blur-xl lg:px-6">
      {/* Left Side */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white lg:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-lg font-semibold text-white">{pageTitle}</h1>
        </div>
      </div>

      {/* Right Side */}
      <div className="flex items-center gap-2">
        {/* Online Status */}
        <div className="hidden items-center gap-2 rounded-full border border-slate-700/50 bg-slate-800/50 px-3 py-1.5 sm:flex">
          {isOnline ? (
            <>
              <Wifi className="h-3.5 w-3.5 text-emerald-400" />
              <span className="text-xs font-medium text-emerald-400">Online</span>
            </>
          ) : (
            <>
              <WifiOff className="h-3.5 w-3.5 text-red-400" />
              <span className="text-xs font-medium text-red-400">Offline</span>
            </>
          )}
        </div>

        {/* Notifications */}
        {/* <div className="relative" ref={notifRef}>
          <button
            onClick={() => setShowNotifications(!showNotifications)}
            className="relative rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
          >
            <Bell className="h-5 w-5" />
            {unreadCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
                {unreadCount}
              </span>
            )}
          </button>

          <AnimatePresence>
            {showNotifications && (
              <motion.div
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.95 }}
                transition={{ duration: 0.2 }}
                className="absolute right-0 top-12 w-80 overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-2xl"
              >
                <div className="border-b border-slate-700 p-3">
                  <h3 className="text-sm font-semibold text-white">Notifications</h3>
                </div>
                <div className="max-h-80 overflow-y-auto">
                  {mockNotifications.map((notif) => (
                   <div
                      key={notif.id}
                      className={`flex gap-3 border-b border-slate-700/50 p-3 transition-colors hover:bg-slate-700/30 ${!notif.read ? 'bg-slate-700/10' : ''

                      }`}
                    >
                      <div className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${notifTypeColors[notif.type]}`} />
                      <div>
                        <p className="text-xs text-slate-300">{notif.message}</p>
                        <p className="mt-1 text-[10px] text-slate-500">{notif.time}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div> */}

        {/* Profile Dropdown */}
        <div className="relative" ref={profileRef}>
          <button
            onClick={() => setShowProfile(!showProfile)}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
          >
           <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-green-500 to-emerald-400 text-sm font-bold text-white uppercase">
              {currentUser.name.charAt(0)}
            </div>
            <span className="hidden text-sm font-medium text-slate-300 md:block">{currentUser.name}</span>
            <ChevronDown className="hidden h-4 w-4 md:block" />
          </button>

          <AnimatePresence>
            {showProfile && (
              <motion.div
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.95 }}
                transition={{ duration: 0.2 }}
                className="absolute right-0 top-12 w-56 overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-2xl"
              >
                <div className="border-b border-slate-700 p-3">
                 <p className="text-sm font-semibold text-white">{currentUser.name}</p>
                  <p className="text-xs text-slate-500">{currentUser.email}</p>
                  <span className="mt-1 inline-block rounded-full bg-green-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-green-400">
                    {currentUser.role}
                  </span>
                </div>
                <div className="p-1">
                  <button
                    onClick={() => { setShowProfile(false); navigate('/settings'); }}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-400 transition-colors hover:bg-slate-700 hover:text-white"
                  >
                    <Settings className="h-4 w-4" /> Settings
                  </button>
                   <button
                    onClick={() => {
                      setShowProfile(false);
                      localStorage.removeItem('token');
                      localStorage.removeItem('user');
                      navigate('/login');
                    }} 
                     className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-400 transition-colors hover:bg-slate-700 hover:text-white">
                    <LogOut className="h-4 w-4" /> Logout
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
};

export default TopNavbar;
