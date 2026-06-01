import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { MapPin, Cpu, Wifi, Plus, Search, MoreVertical } from 'lucide-react';
import { mockLocations } from '../../data/mockData';
import { SkeletonTable } from '../../components/Skeleton';
import EmptyState from '../../components/EmptyState';

const LocationsPage = () => {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'table'

  useEffect(() => {
    const timer = setTimeout(() => {
      setLocations(mockLocations);
      setLoading(false);
    }, 1200);
    return () => clearTimeout(timer);
  }, []);

  const filtered = locations.filter(
    (l) => l.name.toLowerCase().includes(searchTerm.toLowerCase()) || l.address.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">All Locations</h2>
          <p className="text-sm text-slate-400">{locations.length} locations configured</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search locations..."
              className="w-full rounded-xl border border-slate-700 bg-slate-800/50 py-2.5 pl-10 pr-4 text-sm text-white placeholder-slate-500 outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 sm:w-64"
            />
          </div>
          <div className="flex gap-1 rounded-lg bg-slate-800/50 p-0.5">
            <button
              onClick={() => setViewMode('grid')}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${viewMode === 'grid' ? 'bg-green-500/20 text-green-400' : 'text-slate-400'}`}
            >
              Grid
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${viewMode === 'table' ? 'bg-green-500/20 text-green-400' : 'text-slate-400'}`}
            >
              Table
            </button>
          </div>
          <button className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-green-500/20 transition-all hover:shadow-green-500/30">
            <Plus className="h-4 w-4" /> Add Location
          </button>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        viewMode === 'grid' ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-5">
                <div className="skeleton mb-3 h-5 w-40 rounded" />
                <div className="skeleton mb-4 h-3 w-56 rounded" />
                <div className="flex gap-6">
                  <div className="skeleton h-4 w-20 rounded" />
                  <div className="skeleton h-4 w-20 rounded" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <SkeletonTable rows={5} cols={4} />
        )
      ) : filtered.length === 0 ? (
        <EmptyState icon={MapPin} title="No locations found" description="No locations match your search criteria." />
      ) : viewMode === 'grid' ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {filtered.map((loc, i) => (
            <motion.div
              key={loc.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              whileHover={{ scale: 1.02, y: -2 }}
              className="group cursor-pointer rounded-2xl border border-slate-700/50 bg-slate-800/50 p-5 backdrop-blur-sm transition-all hover:border-slate-600/50 hover:shadow-lg hover:shadow-green-500/5"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="rounded-xl bg-cyan-500/10 p-2.5">
                    <MapPin className="h-5 w-5 text-cyan-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white group-hover:text-green-400 transition-colors">{loc.name}</h3>
                    <p className="mt-0.5 text-xs text-slate-500">{loc.address}</p>
                  </div>
                </div>
                <button className="rounded-lg p-1 text-slate-500 hover:bg-slate-700 hover:text-white transition-colors">
                  <MoreVertical className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-4 flex gap-6 border-t border-slate-700/50 pt-4">
                <div className="flex items-center gap-2 text-xs">
                  <Cpu className="h-3.5 w-3.5 text-slate-500" />
                  <span className="text-slate-400">{loc.totalDevices} Devices</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-emerald-400">{loc.activeDevices} Active</span>
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-700/50 bg-slate-800/30">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Location</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Address</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Total Devices</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Active Devices</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((loc) => (
                <tr key={loc.id} className="border-b border-slate-700/30 transition-colors hover:bg-slate-800/50">
                  <td className="px-6 py-4 font-medium text-white">{loc.name}</td>
                  <td className="px-6 py-4 text-slate-400">{loc.address}</td>
                  <td className="px-6 py-4 text-slate-300">{loc.totalDevices}</td>
                  <td className="px-6 py-4">
                    <span className="text-emerald-400">{loc.activeDevices}</span>
                    <span className="text-slate-600"> / {loc.totalDevices}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default LocationsPage;
