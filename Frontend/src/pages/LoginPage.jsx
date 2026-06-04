import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import logo from '../assets/logo.webp';
import white_stoke from '../assets/white-stroke.png';
import { Eye, EyeOff, ArrowRight, Shield, BarChart3, Leaf, Activity } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const LoginPage = () => { 
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [isFocused, setIsFocused] = useState({ email: false, password: false });
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      // Safe JSON parse — in production a misconfigured API URL returns HTML, not JSON
      const contentType = res.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        throw new Error(
          `Server returned unexpected response (${res.status}). Check VITE_API_URL in your deployment environment.`
        );
      } 

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || 'Login failed');
      }
      // Persist token & user info (includes accountType)
      localStorage.setItem('token', data.token);
      localStorage.setItem('user', JSON.stringify(data.user));

      // Role-based redirect
      if (data.accountType === 'superadmin') {
        navigate('/superadmin-dashboard');
      } else if (data.accountType === 'admin') {
        navigate('/dashboard');
      } else {
        navigate('/user-dashboard');
      }
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', fontFamily: "'Inter', 'Segoe UI', sans-serif" }}>
      {/* ─── Left Panel (Branding) ─── */}
      <div
        style={{
          flex: '1 1 50%',
          // background: 'linear-gradient(160deg, #0a1628 0%, #0f2035 30%, #132a42 55%, #0d1f33 100%)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          position: 'relative',
          overflow: 'hidden',
          padding: '3rem',
        }}
        className="login-left-panel"
      >
        {/* Gradient mesh overlay */}
        <div style={{
          position: 'absolute', inset: 0,
          // background: `
          //   radial-gradient(ellipse 600px 400px at 20% 20%, rgba(96,191,113,0.08) 0%, transparent 100%),
          //   radial-gradient(ellipse 500px 500px at 80% 80%, rgba(56,152,236,0.06) 0%, transparent 100%),
          //   radial-gradient(ellipse 400px 300px at 50% 50%, rgba(96,191,113,0.04) 0%, transparent 100%)
          // `,
        }} />

        {/* Animated floating orbs */}
        <div style={{
          position: 'absolute', top: '10%', left: '15%',
          width: '200px', height: '200px', borderRadius: '50%',
          // background: 'radial-gradient(circle, rgba(96,191,113,0.12) 0%, transparent 70%)',
          animation: 'floatOrb1 12s ease-in-out infinite',
          filter: 'blur(40px)',
        }} />
        <div style={{
          position: 'absolute', bottom: '15%', right: '10%',
          width: '280px', height: '280px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(56,152,236,0.1) 0%, transparent 70%)',
          animation: 'floatOrb2 15s ease-in-out infinite',
          filter: 'blur(50px)',
        }} />
        <div style={{
          position: 'absolute', top: '60%', left: '5%',
          width: '150px', height: '150px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(96,191,113,0.08) 0%, transparent 70%)',
          animation: 'floatOrb3 10s ease-in-out infinite',
          filter: 'blur(30px)',
        }} />

        {/* Subtle grid pattern */}
        <div style={{
          position: 'absolute', inset: 0, opacity: 0.03,
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.2) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.2) 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }} />

        {/* Diagonal accent line */}
        <div style={{
          position: 'absolute', top: 0, right: 0,
          width: '1px', height: '100%',
          background: 'linear-gradient(to bottom, transparent, rgba(96,191,113,0.2), transparent)',
        }} />

        {/* Content */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          style={{ position: 'relative', zIndex: 1, textAlign: 'center', maxWidth: '440px' }}
        >
          {/* Logo */}
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', delay: 0.3, duration: 0.8 }}

            style={{
              marginBottom: '2rem',
              filter: 'drop-shadow(2px 3px 3px #ccc)',
              padding: '40px',
              rotate : "12deg",
              backgroundImage : `url(${white_stoke})`,
              backgroundSize: '100% 100%',
              backgroundPosition: 'top',
              borderRadius: '9999px',
            }} 
          >
            <img
              src={logo}
              alt="INHYDRO Logo"
              style={{
                rotate : "-12deg",
                marginBottom: "20px",
                maxWidth: '200px', margin: '0 auto',

              }}
            />
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5, duration: 0.6 }}
            style={{
              fontSize: '2.25rem', fontWeight: 800, color: '#ffffff',
              marginBottom: '0.5rem', letterSpacing: '-0.03em',
              lineHeight: 1.15,
            }}
          >
            Smart
            <span style={{
              display: 'block',
              background: 'linear-gradient(135deg, #60bf71 0%, #3ecf8e 50%, #38d9a9 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              marginTop: '0.15rem',
            }}>
              Hydroponics System
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.7 }}
            style={{
              color: 'rgba(148,175,204,0.7)', fontSize: '0.95rem',
              lineHeight: 1.7, maxWidth: '340px', margin: '0 auto',
            }}
          >
            Precision agriculture through real-time IoT sensing and intelligent data analytics.
          </motion.p>

          {/* Feature pills */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.9, duration: 0.6 }}
            style={{
              display: 'flex', gap: '0.75rem', justifyContent: 'center',
              marginTop: '2.5rem', flexWrap: 'wrap',
            }}
          >
            {[
              { icon: <Shield size={14} />, label: 'Secure' },
              { icon: <Activity size={14} />, label: 'Real-time' },
              { icon: <BarChart3 size={14} />, label: 'Analytics' },
            ].map((item, i) => (
              <motion.div
                key={item.label}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 1.0 + i * 0.12 }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  padding: '0.45rem 0.9rem', borderRadius: '999px',
                  background: 'rgba(96,191,113,0.08)',
                  border: '1px solid rgba(96,191,113,0.15)',
                  color: '#60bf71', fontSize: '0.75rem', fontWeight: 600,
                  letterSpacing: '0.03em', textTransform: 'uppercase',
                  backdropFilter: 'blur(8px)',
                }}
              >
                {item.icon}
                {item.label}
              </motion.div>
            ))}
          </motion.div>

          {/* Stats row */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.3 }}
            style={{
              display: 'flex', justifyContent: 'center', gap: '2.5rem',
              marginTop: '3rem', paddingTop: '2rem',
              borderTop: '1px solid rgba(255,255,255,0.06)',
            }}
          >
            {[
              { value: '24/7', label: 'Monitoring' },
              { value: '99.9%', label: 'Uptime' }, 
            ].map((stat) => (
              <div key={stat.label} style={{ textAlign: 'center' }}>
                <div style={{
                  fontSize: '1.35rem', fontWeight: 800,
                  background: 'linear-gradient(135deg, #60bf71, #38d9a9)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                }}>
                  {stat.value}
                </div>
                <div style={{
                  fontSize: '0.7rem', color: 'rgba(148,175,204,0.5)',
                  marginTop: '0.25rem', textTransform: 'uppercase',
                  letterSpacing: '0.08em', fontWeight: 500, 
                }}>
                  {stat.label}
                </div>
              </div>
            ))}
          </motion.div>
        </motion.div>
      </div>

      {/* ─── Right Panel (Login Form) ─── */}
      <div
        style={{
          flex: '1 1 50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#fafbfc',
          padding: '2.5rem',
          position: 'relative',
          overflow: 'hidden',
        }}
        className="login-right-panel"
      >
        {/* Subtle decorative elements */}
        <div style={{
          position: 'absolute', top: '-100px', right: '-100px',
          width: '350px', height: '350px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(96,191,113,0.05) 0%, transparent 70%)',
        }} />
        <div style={{
          position: 'absolute', bottom: '-80px', left: '-80px',
          width: '280px', height: '280px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(15,32,53,0.03) 0%, transparent 70%)',
        }} />

        <motion.div
          initial={{ opacity: 0, x: 40 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.7, delay: 0.3 }}
          style={{ width: '100%', maxWidth: '420px', position: 'relative', zIndex: 1 }}
        >
          {/* Welcome heading */}
          <div style={{ marginBottom: '2rem' }}>
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.4 }}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                padding: '0.4rem 0.85rem', borderRadius: '999px',
                background: 'rgba(96,191,113,0.08)',
                border: '1px solid rgba(96,191,113,0.15)',
                color: '#4da85e', fontSize: '0.72rem', fontWeight: 600,
                marginBottom: '1.25rem', letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              <Leaf size={12} />
              Dashboard Access
            </motion.div>

            <motion.h2
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
              style={{
                fontSize: '1.85rem', fontWeight: 800, color: '#0f2035',
                marginBottom: '0.4rem', letterSpacing: '-0.025em',
                lineHeight: 1.2,
              }}
            >
              Welcome Back
            </motion.h2>
            <p style={{ color: '#7a8fa3', fontSize: '0.9rem', lineHeight: 1.5 }}>
              Sign in to access your IoT monitoring dashboard
            </p>
          </div>

          {/* ─── Login Card ─── */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.5 }}
            style={{
              background: '#ffffff',
              borderRadius: '1.25rem',
              border: '1px solid rgba(0,0,0,0.06)',
              padding: '2rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 32px rgba(0,0,0,0.06)',
            }}
          >
            <form onSubmit={handleLogin}>
              {/* Email Field */}
              <div style={{ marginBottom: '1.25rem' }}>
                <label style={{
                  display: 'block', fontSize: '0.78rem', fontWeight: 600,
                  color: '#374151', marginBottom: '0.5rem', letterSpacing: '0.02em',
                }}>
                  Email Address
                </label>
                <div style={{
                  position: 'relative',
                  borderRadius: '0.75rem',
                  border: isFocused.email
                    ? '2px solid #60bf71'
                    : '2px solid #e5e7eb',
                  background: isFocused.email ? 'rgba(96,191,113,0.02)' : '#f9fafb',
                  transition: 'all 0.25s cubic-bezier(0.4,0,0.2,1)',
                  boxShadow: isFocused.email ? '0 0 0 4px rgba(96,191,113,0.08)' : 'none',
                }}>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onFocus={() => setIsFocused(f => ({ ...f, email: true }))}
                    onBlur={() => setIsFocused(f => ({ ...f, email: false }))}
                    placeholder="you@company.com"
                    required
                    style={{
                      width: '100%', padding: '0.85rem 1rem',
                      border: 'none', outline: 'none',
                      background: 'transparent',
                      fontSize: '0.9rem', color: '#1f2937',
                      borderRadius: '0.75rem',
                    }}
                  />
                </div>
              </div>

              {/* Password Field */}
              <div style={{ marginBottom: '1.25rem' }}>
                <label style={{
                  display: 'block', fontSize: '0.78rem', fontWeight: 600,
                  color: '#374151', marginBottom: '0.5rem', letterSpacing: '0.02em',
                }}>
                  Password
                </label>
                <div style={{
                  position: 'relative',
                  borderRadius: '0.75rem',
                  border: isFocused.password
                    ? '2px solid #60bf71'
                    : '2px solid #e5e7eb',
                  background: isFocused.password ? 'rgba(96,191,113,0.02)' : '#f9fafb',
                  transition: 'all 0.25s cubic-bezier(0.4,0,0.2,1)',
                  boxShadow: isFocused.password ? '0 0 0 4px rgba(96,191,113,0.08)' : 'none',
                  display: 'flex', alignItems: 'center',
                }}>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onFocus={() => setIsFocused(f => ({ ...f, password: true }))}
                    onBlur={() => setIsFocused(f => ({ ...f, password: false }))}
                    placeholder="Enter your password"
                    required
                    style={{
                      flex: 1, padding: '0.85rem 1rem',
                      border: 'none', outline: 'none',
                      background: 'transparent',
                      fontSize: '0.9rem', color: '#1f2937',
                      borderRadius: '0.75rem',
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      padding: '0.5rem 0.85rem',
                      color: '#9ca3af', display: 'flex', alignItems: 'center',
                      transition: 'color 0.2s',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = '#60bf71')}
                    onMouseLeave={(e) => (e.currentTarget.style.color = '#9ca3af')}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {/* Remember & Forgot */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginBottom: '1.75rem', fontSize: '0.82rem',
              }}>
                <label style={{
                  display: 'flex', alignItems: 'center', gap: '0.5rem',
                  color: '#6b7280', cursor: 'pointer', userSelect: 'none',
                }}>
                  <input
                    type="checkbox"
                    defaultChecked
                    style={{
                      accentColor: '#60bf71',
                      width: '16px', height: '16px', cursor: 'pointer',
                    }}
                  />
                  Remember me
                </label>
                <button
                  type="button"
                  onClick={() => navigate('/forgot-password')}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: '#60bf71', fontWeight: 600, fontSize: '0.82rem',
                    transition: 'color 0.2s',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = '#3d945a')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = '#60bf71')}
                >
                  Forgot password?
                </button>
              </div>

              {/* Error banner */}
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  style={{
                    marginBottom: '1rem',
                    padding: '0.75rem 1rem',
                    borderRadius: '0.65rem',
                    background: 'rgba(239,68,68,0.06)',
                    border: '1px solid rgba(239,68,68,0.2)',
                    color: '#dc2626',
                    fontSize: '0.82rem',
                    fontWeight: 500,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                  }}
                >
                  ⚠ {error}
                </motion.div>
              )}

              {/* Submit Button */}
              <motion.button
                type="submit"
                disabled={isLoading}
                whileHover={{ scale: 1.01, boxShadow: '0 12px 40px rgba(96,191,113,0.3)' }}
                whileTap={{ scale: 0.985 }}
                style={{
                  width: '100%', padding: '0.95rem',
                  border: 'none', borderRadius: '0.75rem',
                  background: 'linear-gradient(135deg, #60bf71 0%, #4caf5e 50%, #3d9e52 100%)',
                  color: '#ffffff', fontSize: '0.95rem', fontWeight: 700,
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  opacity: isLoading ? 0.75 : 1,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                  boxShadow: '0 4px 16px rgba(96,191,113,0.25), 0 1px 3px rgba(0,0,0,0.08)',
                  transition: 'all 0.3s cubic-bezier(0.4,0,0.2,1)',
                  letterSpacing: '0.02em',
                }}
              >
                {isLoading ? (
                  <div style={{
                    width: '22px', height: '22px', borderRadius: '50%',
                    border: '3px solid rgba(255,255,255,0.3)',
                    borderTopColor: '#ffffff',
                    animation: 'spin 0.8s linear infinite',
                  }} />
                ) : (
                  <>
                    Sign In
                    <ArrowRight size={18} style={{ transition: 'transform 0.2s' }} />
                  </>
                )}
              </motion.button>
            </form>
          </motion.div>

          {/* Footer */}
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.2 }}
            style={{
              textAlign: 'center', fontSize: '0.75rem', color: '#9ca3af',
              marginTop: '2rem',
            }}
          >
            &copy; 2026 <span style={{ color: '#374151', fontWeight: 700 }}>INHYDRO</span>&ensp;·&ensp;All rights reserved
          </motion.p>
        </motion.div>
      </div>

      {/* ─── Global Styles ─── */}
      <style>{`
        @keyframes floatOrb1 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          25% { transform: translate(40px, -30px) scale(1.1); }
          50% { transform: translate(-20px, 40px) scale(0.9); }
          75% { transform: translate(30px, 20px) scale(1.05); }
        }
        @keyframes floatOrb2 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          33% { transform: translate(-40px, -20px) scale(1.08); }
          66% { transform: translate(30px, 30px) scale(0.92); }
        }
        @keyframes floatOrb3 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(25px, -35px) scale(1.12); }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        @media (max-width: 900px) {
          .login-left-panel {
            display: none !important;
          }
          .login-right-panel {
            flex: 1 1 100% !important;
            background: linear-gradient(180deg, #0f2035 0%, #132a42 50%, #0a1628 100%) !important;
          }
          .login-right-panel h2 {
            color: #ffffff !important;
          }
          .login-right-panel p {
            color: rgba(255,255,255,0.55) !important;
          }
          .login-right-panel label {
            color: rgba(255,255,255,0.7) !important;
          }
        }

        @media (max-width: 480px) {
          .login-right-panel {
            padding: 1.25rem !important;
          }
        }

        input::placeholder {
          color: #b0b8c4 !important;
        }
        input:focus {
          outline: none;
        }
      `}</style>
    </div>
  );
};

export default LoginPage;
