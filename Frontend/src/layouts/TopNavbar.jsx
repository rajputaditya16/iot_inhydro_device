import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bell, ChevronDown,Settings, LogOut, Wifi, WifiOff, Menu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

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

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target)) setShowNotifications(false);
      if (profileRef.current && !profileRef.current.contains(e.target)) setShowProfile(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

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
