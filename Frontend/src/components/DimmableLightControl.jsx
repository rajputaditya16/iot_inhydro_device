import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Sun, Power, Clock, Settings, ToggleRight, Zap, Calendar, ChevronDown } from 'lucide-react';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// ─── Day picker ───────────────────────────────────────────────────────────────
const DayPicker = ({ days = [1,1,1,1,1,1,1], onChange }) => (
  <div className="flex gap-1 flex-wrap">
    {DAY_LABELS.map((d, i) => {
      const isActive = days[i] === 1;
      return (
        <button
          key={i}
          type="button"
          onClick={() => {
            const next = [...days];
            next[i] = next[i] === 1 ? 0 : 1;
            onChange(next);
          }}
          className={`rounded-lg px-2 py-1 text-[10px] font-bold transition-all ${
            isActive
              ? 'bg-amber-500/20 text-amber-400 ring-1 ring-amber-500/40'
              : 'bg-slate-800 text-slate-500 hover:text-slate-300'
          }`}
        >
          {d}
        </button>
      );
    })}
  </div>
);

// ─── Field input ──────────────────────────────────────────────────────────────
const Field = ({ label, value, onChange, type = 'text', placeholder = '' }) => (
  <div className="flex flex-col gap-1">
    <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</label>
    <input
      type={type}
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-white outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/40 transition-all"
    />
  </div>
);

// ─── Mode toggle ──────────────────────────────────────────────────────────────
const ModeToggle = ({ mode, onChange }) => (
  <div className="flex gap-2">
    {['auto', 'manual'].map(m => (
      <button
        key={m}
        type="button"
        onClick={() => onChange(m)}
        className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold capitalize transition-all ${
          mode === m
            ? 'bg-amber-500/20 text-amber-400 ring-1 ring-amber-500/40'
            : 'bg-slate-800 text-slate-400 hover:text-white'
        }`}
      >
        {m === 'auto' ? <Clock className="h-3 w-3" /> : <Settings className="h-3 w-3" />}
        {m}
      </button>
    ))}
  </div>
);

const DimmableLightControl = ({ name = 'light', relay = {}, onChange }) => {
  const [showSchedule, setShowSchedule] = useState(false);

  // Defaults
  const mode = relay.mode || 'manual';
  const manualState = relay.manual_state ?? 0;
  const brightness = relay.brightness ?? 100;
  const start_time = relay.start_time || '08:00';
  const end_time = relay.end_time || '20:00';
  const on_min = relay.on_min ?? 0;
  const off_min = relay.off_min ?? 0;
  const days = relay.days || [1, 1, 1, 1, 1, 1, 1];
  const pin = relay.pin ?? 4;

  const update = (key, val) => {
    onChange({
      ...relay,
      [key]: val,
    });
  };

  const isLightOn = mode === 'manual' ? manualState === 1 : true; // In auto, assume active within window

  // Calculate dynamic glow styles based on brightness and on state
  const currentIntensity = isLightOn ? brightness : 0;
  const bulbColor = isLightOn
    ? `rgba(251, 191, 36, ${0.3 + (currentIntensity / 100) * 0.7})` // Warm amber glow
    : 'rgba(71, 85, 105, 0.4)'; // Slate unlit color
  
  const glowShadow = isLightOn
    ? `0 0 ${15 + (currentIntensity / 100) * 35}px rgba(245, 158, 11, ${0.2 + (currentIntensity / 100) * 0.6})`
    : 'none';

  return (
    <div 
      className="relative overflow-hidden rounded-2xl border bg-gradient-to-b from-slate-800/40 to-slate-900/60 p-6 backdrop-blur-md transition-all shadow-lg border-slate-700/50 hover:border-slate-600/50"
    >
      {/* Dynamic ambient backdrop light */}
      {isLightOn && (
        <div 
          className="absolute -right-24 -top-24 w-64 h-64 rounded-full blur-3xl pointer-events-none transition-all duration-700"
          style={{
            background: `radial-gradient(circle, rgba(245, 158, 11, ${0.05 + (currentIntensity / 100) * 0.15}) 0%, rgba(245, 158, 11, 0) 70%)`
          }}
        />
      )}

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div 
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 shadow-sm"
          >
            <Sun className={`h-5 w-5 ${isLightOn && currentIntensity > 0 ? 'animate-pulse' : ''}`} />
          </div>
          <div>
            <h4 className="text-sm font-bold text-white flex items-center gap-1.5 uppercase tracking-wide">
              {name} Dimmer
              <span className="text-[10px] text-slate-500 font-mono normal-case tracking-normal">pin {pin}</span>
            </h4>
            <p className="text-[11px] text-slate-400 mt-0.5">Control state & brightness intensity</p>
          </div>
        </div>
        <ModeToggle mode={mode} onChange={v => update('mode', v)} />
      </div>

      {/* Control Pane Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-center">
        {/* Left: Dynamic Lightbulb SVG Visualizer */}
        <div className="md:col-span-4 flex flex-col items-center justify-center p-4 rounded-xl bg-slate-950/20 border border-slate-800/40 min-h-[160px]">
          <div 
            className="relative flex items-center justify-center w-24 h-24 rounded-full transition-all duration-300"
            style={{ 
              backgroundColor: isLightOn ? `rgba(245, 158, 11, ${(currentIntensity / 100) * 0.15})` : 'transparent',
              boxShadow: glowShadow
            }}
          >
            {/* Rays around bulb */}
            {isLightOn && currentIntensity > 20 && (
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: currentIntensity / 100 }}
                className="absolute inset-0 border border-dashed border-amber-500/30 rounded-full scale-125 animate-[spin_40s_linear_infinite]"
              />
            )}
            
            <svg 
              className="w-12 h-12 transition-all duration-300" 
              viewBox="0 0 24 24" 
              fill="none" 
              stroke="currentColor" 
              strokeWidth="1.5"
              style={{ color: bulbColor }}
            >
              {/* Bulb Glass */}
              <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .6 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" fill={isLightOn ? `rgba(251, 191, 36, ${(currentIntensity / 100) * 0.4})` : 'transparent'} />
              {/* Filament */}
              {isLightOn && (
                <path d="M9 8h6 M12 6v4" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
              )}
              {/* Base */}
              <path d="M9 18h6" stroke="currentColor" strokeLinecap="round" />
              <path d="M10 21h4" stroke="currentColor" strokeLinecap="round" />
            </svg>
          </div>
          <span className="text-xs font-semibold text-slate-400 mt-3">
            {isLightOn ? `Intensity: ${currentIntensity}%` : 'Light is OFF'}
          </span>
        </div>

        {/* Right: State & Brightness Controls */}
        <div className="md:col-span-8 space-y-6">
          {/* Power State Trigger */}
          <div className="flex items-center justify-between p-4 rounded-xl bg-slate-900/30 border border-slate-800">
            <div>
              <span className="text-xs font-semibold text-slate-300 block">Switch Power</span>
              <span className="text-[10px] text-slate-500">Override relay hardware output</span>
            </div>
            <button
              type="button"
              onClick={() => update('manual_state', manualState === 1 ? 0 : 1)}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-md active:scale-95 ${
                manualState === 1
                  ? 'bg-gradient-to-r from-amber-500 to-yellow-500 text-slate-950 shadow-amber-500/20'
                  : 'bg-slate-800 text-slate-400 border border-slate-700/60'
              }`}
            >
              <Power className="h-4 w-4" />
              {manualState === 1 ? 'ACTIVE / ON' : 'DISABLED / OFF'}
            </button>
          </div>

          {/* Intensity Slider */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                Brightness Regulator
              </span>
              <span className="text-xs font-bold text-amber-400 font-mono bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                {brightness}%
              </span>
            </div>
            
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-slate-500 font-bold">MIN</span>
              <input
                type="range"
                min="0"
                max="100"
                value={brightness}
                onChange={e => update('brightness', Number(e.target.value))}
                className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500 outline-none focus:ring-1 focus:ring-amber-500/30"
                style={{
                  background: `linear-gradient(to right, #f59e0b 0%, #fbbf24 ${brightness}%, #1e293b ${brightness}%, #1e293b 100%)`
                }}
              />
              <span className="text-[10px] text-slate-500 font-bold">MAX</span>
            </div>
          </div>
        </div>
      </div>

      {/* Scheduler details (Auto mode configurations) */}
      <div className="mt-6 border-t border-slate-800 pt-4">
        <button
          type="button"
          onClick={() => setShowSchedule(!showSchedule)}
          className="flex items-center justify-between w-full text-slate-400 hover:text-white transition-colors py-1"
        >
          <span className="text-xs font-semibold flex items-center gap-2">
            <Clock className="h-4 w-4 text-amber-500/70" />
            Light Schedule Configuration
            {mode === 'auto' ? (
              <span className="rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] px-2 py-0.5">Active</span>
            ) : (
              <span className="rounded-full bg-slate-800 text-slate-500 text-[9px] px-2 py-0.5">Inactive</span>
            )}
          </span>
          <ChevronDown className={`h-4 w-4 transition-transform duration-200 ${showSchedule ? 'rotate-180' : ''}`} />
        </button>

        <AnimatePresence>
          {showSchedule && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden space-y-4 pt-4"
            >
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Field label="Start Time" value={start_time} type="time" onChange={v => update('start_time', v)} />
                <Field label="End Time" value={end_time} type="time" onChange={v => update('end_time', v)} />
                <Field label="ON Duration (min)" value={on_min} type="number" onChange={v => update('on_min', Number(v))} />
                <Field label="OFF Duration (min)" value={off_min} type="number" onChange={v => update('off_min', Number(v))} />
              </div>

              <div className="flex flex-col gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                  <Calendar className="h-3 w-3" /> Scheduled Days
                </span>
                <DayPicker days={days} onChange={v => update('days', v)} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default DimmableLightControl;
