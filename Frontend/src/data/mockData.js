// Mock data for INHYDRO IoT Monitoring Platform

export const mockUser = {
  id: 1,
  name: 'Rajesh Kumar',
  email: 'rajesh@inhydro.com',
  role: 'admin',
  avatar: null,
};

export const mockLocations = [
  { id: 1, name: 'Mumbai Farm Zone A', address: 'Sector 12, Navi Mumbai, Maharashtra', totalDevices: 8, activeDevices: 7 },
  { id: 2, name: 'Pune Greenhouse B', address: 'Hinjewadi Phase 3, Pune, Maharashtra', totalDevices: 5, activeDevices: 5 },
  { id: 3, name: 'Nashik Vineyard C', address: 'Sula Road, Nashik, Maharashtra', totalDevices: 6, activeDevices: 4 },
  { id: 4, name: 'Kolhapur Sugarcane D', address: 'Rankala, Kolhapur, Maharashtra', totalDevices: 4, activeDevices: 3 },
  { id: 5, name: 'Nagpur Citrus E', address: 'MIHAN, Nagpur, Maharashtra', totalDevices: 3, activeDevices: 3 },
];

export const mockDevices = [
  { id: 'DEV-001', name: 'Soil Sensor Alpha', locationId: 1, location: 'Mumbai Farm Zone A', status: 'online', temp: 28.5, moisture: 62.3, ec: 1.8, ph: 6.7, lastUpdated: '2026-02-25T10:30:00Z', battery: 87 },
  { id: 'DEV-002', name: 'Soil Sensor Beta', locationId: 1, location: 'Mumbai Farm Zone A', status: 'online', temp: 30.1, moisture: 55.8, ec: 2.1, ph: 7.1, lastUpdated: '2026-02-25T10:29:00Z', battery: 92 },
  { id: 'DEV-003', name: 'Soil Sensor Gamma', locationId: 1, location: 'Mumbai Farm Zone A', status: 'warning', temp: 35.2, moisture: 38.4, ec: 3.2, ph: 5.3, lastUpdated: '2026-02-25T10:28:00Z', battery: 45 },
  { id: 'DEV-004', name: 'Soil Sensor Delta', locationId: 2, location: 'Pune Greenhouse B', status: 'online', temp: 26.8, moisture: 71.2, ec: 1.5, ph: 6.9, lastUpdated: '2026-02-25T10:30:00Z', battery: 95 },
  { id: 'DEV-005', name: 'Soil Sensor Epsilon', locationId: 2, location: 'Pune Greenhouse B', status: 'online', temp: 27.4, moisture: 68.5, ec: 1.6, ph: 7.0, lastUpdated: '2026-02-25T10:30:00Z', battery: 88 },
  { id: 'DEV-006', name: 'Soil Sensor Zeta', locationId: 3, location: 'Nashik Vineyard C', status: 'offline', temp: 0, moisture: 0, ec: 0, ph: 0, lastUpdated: '2026-02-24T18:45:00Z', battery: 12 },
  { id: 'DEV-007', name: 'Soil Sensor Eta', locationId: 3, location: 'Nashik Vineyard C', status: 'critical', temp: 42.1, moisture: 18.2, ec: 4.5, ph: 4.2, lastUpdated: '2026-02-25T10:30:00Z', battery: 23 },
  { id: 'DEV-008', name: 'Soil Sensor Theta', locationId: 4, location: 'Kolhapur Sugarcane D', status: 'online', temp: 29.3, moisture: 65.0, ec: 1.9, ph: 6.8, lastUpdated: '2026-02-25T10:29:00Z', battery: 76 },
  { id: 'DEV-009', name: 'Soil Sensor Iota', locationId: 4, location: 'Kolhapur Sugarcane D', status: 'offline', temp: 0, moisture: 0, ec: 0, ph: 0, lastUpdated: '2026-02-24T22:10:00Z', battery: 5 },
  { id: 'DEV-010', name: 'Soil Sensor Kappa', locationId: 5, location: 'Nagpur Citrus E', status: 'online', temp: 31.7, moisture: 52.1, ec: 2.0, ph: 6.5, lastUpdated: '2026-02-25T10:30:00Z', battery: 81 },
];

export const mockUsers = [
  { id: 1, name: 'Rajesh Kumar', email: 'rajesh@inhydro.com', role: 'admin', assignedLocations: ['All'], assignedDevices: ['All'], status: 'active' },
  { id: 2, name: 'Priya Sharma', email: 'priya@inhydro.com', role: 'manager', assignedLocations: ['Mumbai Farm Zone A', 'Pune Greenhouse B'], assignedDevices: ['DEV-001', 'DEV-002', 'DEV-004', 'DEV-005'], status: 'active' },
  { id: 3, name: 'Amit Patel', email: 'amit@inhydro.com', role: 'operator', assignedLocations: ['Nashik Vineyard C'], assignedDevices: ['DEV-006', 'DEV-007'], status: 'active' },
  { id: 4, name: 'Sneha Deshmukh', email: 'sneha@inhydro.com', role: 'viewer', assignedLocations: ['Kolhapur Sugarcane D'], assignedDevices: ['DEV-008', 'DEV-009'], status: 'inactive' },
  { id: 5, name: 'Vikram Joshi', email: 'vikram@inhydro.com', role: 'operator', assignedLocations: ['Nagpur Citrus E'], assignedDevices: ['DEV-010'], status: 'active' },
];

// Generate time series data for charts
const generateTimeSeries = (baseValue, variance, points = 24) => {
  const now = new Date();
  return Array.from({ length: points }, (_, i) => {
    const time = new Date(now.getTime() - (points - 1 - i) * 3600000);
    return {
      time: time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
      value: +(baseValue + (Math.random() - 0.5) * variance * 2).toFixed(1),
    };
  });
};

export const getChartData = (deviceId) => {
  const device = mockDevices.find((d) => d.id === deviceId) || mockDevices[0];
  return {
    temperature: generateTimeSeries(device.temp || 28, 4),
    moisture: generateTimeSeries(device.moisture || 60, 10),
    ec: generateTimeSeries(device.ec || 1.8, 0.5),
    ph: generateTimeSeries(device.ph || 6.7, 0.4),
  };
};

export const mockNotifications = [
  { id: 1, type: 'critical', message: 'DEV-007 temperature exceeds critical threshold (42.1°C)', time: '2 min ago', read: false },
  { id: 2, type: 'warning', message: 'DEV-003 moisture level below optimal range (38.4%)', time: '15 min ago', read: false },
  { id: 3, type: 'info', message: 'DEV-006 went offline — last signal 16h ago', time: '1 hr ago', read: false },
  { id: 4, type: 'success', message: 'DEV-004 firmware updated successfully', time: '3 hr ago', read: true },
  { id: 5, type: 'warning', message: 'DEV-009 battery critically low (5%)', time: '5 hr ago', read: true },
];
