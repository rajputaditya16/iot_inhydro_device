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

    if (Math.abs(diff) < 0.01 || duration === 0 || (typeof document !== 'undefined' && document.hidden)) {
      setDisplayValue(end);
      prevValue.current = end;
      return;
    }

    let startTime = null;
    let animationFrameId = null;

    const step = (timestamp) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      setDisplayValue(start + diff * eased);

      if (progress < 1) {
        animationFrameId = requestAnimationFrame(step);
      } else {
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
