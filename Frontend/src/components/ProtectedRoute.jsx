import { Navigate } from 'react-router-dom';

/**
 * ProtectedRoute
 * Props:
 *  - allowedAccountTypes: string[] — e.g. ['admin'] or ['user'] or ['admin','user']
 *  - children
 */
const ProtectedRoute = ({ allowedAccountTypes = [], children }) => {
  const token = localStorage.getItem('token');
  const userRaw = localStorage.getItem('user');

  if (!token || !userRaw) {
    return <Navigate to="/login" replace />;
  }

  try {
    const user = JSON.parse(userRaw);
     const accountType = user.role === 'superadmin' ? 'superadmin' : user.accountType;

    if (allowedAccountTypes.length > 0 && !allowedAccountTypes.includes(accountType)) {
      // Redirect to correct dashboard based on actual account type
      if (accountType === 'superadmin') return <Navigate to="/superadmin-dashboard" replace />;
      if (accountType === 'admin') return <Navigate to="/dashboard" replace />;
      if (accountType === 'user') return <Navigate to="/user-dashboard" replace />;
      return <Navigate to="/login" replace />;
    }

    return children;
  } catch {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    return <Navigate to="/login" replace />;
  }
};

export default ProtectedRoute;
