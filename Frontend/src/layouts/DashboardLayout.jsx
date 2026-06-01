import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopNavbar from './TopNavbar';
import { motion } from 'framer-motion';

const pageTitles = {
  '/dashboard': 'Dashboard',
  // '/locations': 'Locations',
   '/superadmin-dashboard': 'Super Admin Dashboard',
  '/devices': 'Devices',
  '/monitoring': 'Live Monitoring',
  '/analytics': 'Analytics',
  '/admins': 'Admin Management',
  '/users': 'User Management',
  '/settings': 'Settings',
  '/user-dashboard': 'User Dashboard',
};

const DashboardLayout = ({ userRole: initialUserRole }) => {
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 1024);
  const location = useLocation();
  const pageTitle = pageTitles[location.pathname] || 'Dashboard';
  
  const [userRole, setUserRole] = useState(initialUserRole || 'user');

  useEffect(() => {
    try {
      const userStr = localStorage.getItem('user');
      if (userStr) {
        
        const parsed = JSON.parse(userStr);
        const bestRole = parsed.role === 'superadmin' ? 'superadmin' : (parsed.role || parsed.accountType || 'user');
        setUserRole(bestRole);
      }
    } catch (e) {}
  }, []);

  useEffect(() => {
    const handleResize = () => {
      const mobile = window.innerWidth < 1024;
      setIsMobile(mobile);
      if (!mobile) {
        setMobileOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleSidebarToggle = () => {
    if (isMobile) {
      setMobileOpen((prev) => !prev);
      return;
    }
    setDesktopCollapsed((prev) => !prev);
  };

  const closeMobileSidebar = () => {
    if (isMobile) setMobileOpen(false);
  };

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Sidebar */}
      <Sidebar
        collapsed={isMobile ? false : desktopCollapsed}
        setCollapsed={handleSidebarToggle}
        isMobile={isMobile}
        isOpen={isMobile ? mobileOpen : true}
        onItemClick={closeMobileSidebar}
        userRole={userRole}
      />

      {/* Main Content */}
      <motion.div
        initial={false}
        animate={{ marginLeft: isMobile ? 0 : (desktopCollapsed ? 72 : 260) }}
        transition={{ duration: 0.3, ease: 'easeInOut' }}
        className="flex min-h-screen flex-col"
      >
        <TopNavbar pageTitle={pageTitle} collapsed={desktopCollapsed} setCollapsed={handleSidebarToggle} />
        <main className="flex-1 p-4 lg:p-6">
          <Outlet />
        </main>
      </motion.div>

      {/* Mobile overlay for sidebar */}
      {isMobile && mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={closeMobileSidebar}
        />
      )}
    </div>
  );
};

export default DashboardLayout;
