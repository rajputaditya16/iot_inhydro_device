import { useState, useEffect, useRef } from 'react';

/**
 * Animated counter hook for live values
 */
export const useAnimatedCounter = (targetValue, duration = 400) => {
  const [displayValue, setDisplayValue] = useState(targetValue);
  const prevValue = useRef(targetValue);

  useEffect(() => {
    const start = prevValue.current;
    const end = targetValue;
    const diff = end - start;

    // For minor sensor pings (< 0.1 difference) or hidden tab, jump directly to end value to save CPU cycles
    if (Math.abs(diff) < 0.1 || duration === 0 || (typeof document !== 'undefined' && document.hidden)) {
      setDisplayValue(end);
      prevValue.current = end;
      return;
    }

    let startTime = null;
    let animationFrameId = null;
    let lastRenderTime = 0;

    const step = (timestamp) => {
      if (!startTime) startTime = timestamp;
      
      // Throttle animation state updates to ~30 FPS (every 33ms) max to halve React renders
      if (timestamp - lastRenderTime >= 33 || timestamp - startTime >= duration) {
        lastRenderTime = timestamp;
        const progress = Math.min((timestamp - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        setDisplayValue(start + diff * eased);
      }

      if (timestamp - startTime < duration) {
        animationFrameId = requestAnimationFrame(step);
      } else {
        setDisplayValue(end);
        prevValue.current = end;
      }
    };

    animationFrameId = requestAnimationFrame(step);

    return () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
      }
    };
  }, [targetValue, duration]);

  return displayValue;
};

/**
 * Simulates live data fluctuation
 */
export const useLiveData = (baseValue, variance = 0.5, intervalMs = 3000) => {
  const [value, setValue] = useState(baseValue);

  useEffect(() => {
    if (baseValue === 0) {
      setValue(0);
      return;
    }
    const interval = setInterval(() => {
      setValue(baseValue + (Math.random() - 0.5) * variance * 2);
    }, intervalMs);
    return () => clearInterval(interval);
  }, [baseValue, variance, intervalMs]);

  return value;
};
