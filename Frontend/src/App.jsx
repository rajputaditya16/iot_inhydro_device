import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import DashboardLayout from './layouts/DashboardLayout';
import LoginPage from './pages/LoginPage';
import ForgotPassword from './pages/ForgotPassword';
import AdminDashboard from './pages/AdminDashboard/AdminDashboard';
import SuperAdminDashboard from './pages/SuperAdminDashboard/SuperAdminDashboard';
import LiveMonitoring from './pages/AdminDashboard/LiveMonitoring';
import DevicesPage from './pages/AdminDashboard/DevicesPage';
import AnalyticsPage from './pages/AdminDashboard/AnalyticsPage';
import UserManagement from './pages/AdminDashboard/UserManagement';
import SettingsPage from './pages/SuperAdminDashboard/SettingsPage';
import AdminManagement from './pages/SuperAdminDashboard/AdminManagement';
// import AlmoraSettings from './pages/SuperAdminDashboard/AlmoraSettings';
import UserDashboard from './pages/UserDashboard/UserDashboard';
import ProtectedRoute from './components/ProtectedRoute';
import ColdStorageSettings from './pages/AdminDashboard/ColdStorageSettings';
import AlmoraSettings from './pages/AdminDashboard/AlmoraSettings';
import Almora2Settings from './pages/AdminDashboard/Almora2Settings';

const SharedLayoutRoute = () => (
  <ProtectedRoute allowedAccountTypes={['superadmin', 'admin', 'user']}>
    <DashboardLayout />
  </ProtectedRoute>
);

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Auth */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        {/* ── Shared Dashboard Layout ── */}
        <Route element={<SharedLayoutRoute />}>
          <Route path="/dashboard" element={<ProtectedRoute allowedAccountTypes={['admin']}><AdminDashboard /></ProtectedRoute>} />
          <Route path="/user-dashboard" element={<ProtectedRoute allowedAccountTypes={['user']}><UserDashboard /></ProtectedRoute>} />
          <Route path="/superadmin-dashboard" element={<ProtectedRoute allowedAccountTypes={['superadmin']}><SuperAdminDashboard /></ProtectedRoute>} />

          {/* Shared Routes */}

          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/monitoring" element={<LiveMonitoring />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/cold-storage" element={<ProtectedRoute allowedAccountTypes={['admin', 'superadmin']}><ColdStorageSettings /></ProtectedRoute>} />
          <Route path="/almora-settings" element={<ProtectedRoute allowedAccountTypes={['admin', 'superadmin']}><AlmoraSettings /></ProtectedRoute>} />
          <Route path="/almora2-settings" element={<ProtectedRoute allowedAccountTypes={['admin', 'superadmin']}><Almora2Settings /></ProtectedRoute>} />
          <Route path="/settings" element={<SettingsPage />} />

          {/* Admin only */}
          <Route path="/users" element={<ProtectedRoute allowedAccountTypes={['superadmin', 'admin']}><UserManagement /></ProtectedRoute>} />
          {/* Superadmin only */}
          <Route path="/admins" element={<ProtectedRoute allowedAccountTypes={['superadmin']}><AdminManagement /></ProtectedRoute>} />
        </Route>

        {/* Default redirect */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
