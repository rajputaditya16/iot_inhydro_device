import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import logo from '../assets/logo.webp';
import white_stoke from '../assets/white-stroke.png';
import { ArrowLeft, Shield, BarChart3, Leaf, Activity, Mail, Key, KeyRound, CheckCircle2 } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const ForgotPassword = () => {
  const [step, setStep] = useState(1); // 1: Email, 2: OTP, 3: New Password, 4: Success
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [isFocused, setIsFocused] = useState({ email: false, otp: false, password: false });
  const navigate = useNavigate();

  // Step 1: Request OTP
  const handleRequestOtp = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Failed to send reset link');
      
      setStep(2);
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  // Step 2: Verify OTP
  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, otp }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Invalid or expired OTP');
      
      setStep(3);
    } catch (err) {
      setError(err.message || 'Invalid OTP. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  // Step 3: Reset Password
  const handleResetPassword = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, otp, password: newPassword }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Failed to reset password');
      
      setStep(4);
    } catch (err) {
      setError(err.message || 'Failed to update password. Please try again.');
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
        <div style={{
          position: 'absolute', inset: 0,
          background: `
            radial-gradient(ellipse 600px 400px at 20% 20%, rgba(96,191,113,0.08) 0%, transparent 100%),
            radial-gradient(ellipse 500px 500px at 80% 80%, rgba(56,152,236,0.06) 0%, transparent 100%),
            radial-gradient(ellipse 400px 300px at 50% 50%, rgba(96,191,113,0.04) 0%, transparent 100%)
          `,
        }} />

        <div style={{
          position: 'absolute', top: '10%', left: '15%',
          width: '200px', height: '200px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(96,191,113,0.12) 0%, transparent 70%)',
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

        <div style={{
          position: 'absolute', inset: 0, opacity: 0.03,
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.2) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.2) 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }} />

        <div style={{
          position: 'absolute', top: 0, right: 0,
          width: '1px', height: '100%',
          background: 'linear-gradient(to bottom, transparent, rgba(96,191,113,0.2), transparent)',
        }} />

        <motion.div 
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          style={{ position: 'relative', zIndex: 1, textAlign: 'center', maxWidth: '440px' }}
        >
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', delay: 0.3, duration: 0.8 }}
            style={{ marginBottom: '2rem', padding: '40px',
                     backgroundImage : `url(${white_stoke})`,
                     backgroundSize: '100% 100%',
                     backgroundPosition: 'top',
                     rotate : "12deg",
                     borderRadius: '9999px',
                     }}
          >
            <img
              src={logo}

              alt="INHYDRO Logo"
              style={{ maxWidth: '200px',  rotate : "-12deg", margin: '0 auto', marginBottom: "15px", filter: 'drop-shadow(0 8px 32px rgba(96,191,113,0.25))' }}
            />
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5, duration: 0.6 }}
            style={{
              fontSize: '2.25rem', fontWeight: 800, color: '#ffffff',
              marginBottom: '0.5rem', letterSpacing: '-0.03em', lineHeight: 1.15,
            }}
          >
            Smart Soil
            <span style={{
              display: 'block', background: 'linear-gradient(135deg, #60bf71 0%, #3ecf8e 50%, #38d9a9 100%)',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', marginTop: '0.15rem',
            }}>
              Monitoring System
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

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.9, duration: 0.6 }}
            style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', marginTop: '2.5rem', flexWrap: 'wrap' }}
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
                  background: 'rgba(96,191,113,0.08)', border: '1px solid rgba(96,191,113,0.15)',
                  color: '#60bf71', fontSize: '0.75rem', fontWeight: 600,
                  letterSpacing: '0.03em', textTransform: 'uppercase', backdropFilter: 'blur(8px)',
                }}
              >
                {item.icon}
                {item.label}
              </motion.div>
            ))}
          </motion.div>
        </motion.div>
      </div>

      {/* ─── Right Panel (Reset Flow) ─── */}
      <div
        style={{
          flex: '1 1 50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: '#fafbfc', padding: '2.5rem', position: 'relative', overflow: 'hidden',
        }}
        className="login-right-panel"
      >
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
          className="login-right-content-wrapper"
        >
          {/* Mobile Header (Only visible on screens <= 900px) */}
          <div className="mobile-header">
            <div style={{
              marginBottom: '1.25rem',
              filter: 'drop-shadow(2px 3px 3px rgba(255,255,255,0.15))',
              padding: '24px',
              rotate: "12deg",
              backgroundImage: `url(${white_stoke})`,
              backgroundSize: '100% 100%',
              backgroundPosition: 'center',
              borderRadius: '9999px',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <img
                src={logo}
                alt="INHYDRO Logo"
                style={{
                  rotate: "-12deg",
                  maxWidth: '120px',
                  height: 'auto',
                }}
              />
            </div>
            <h1 className="mobile-title" style={{
              fontSize: '1.85rem', fontWeight: 800, color: '#ffffff',
              marginBottom: '0.5rem', letterSpacing: '-0.025em',
              lineHeight: 1.2,
            }}>
              Smart Soil
              <span style={{
                display: 'block',
                background: 'linear-gradient(135deg, #60bf71 0%, #3ecf8e 50%, #38d9a9 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                marginTop: '0.15rem',
              }}>
                Monitoring System
              </span>
            </h1>
            <p className="mobile-subtitle" style={{
              color: 'rgba(148,175,204,0.7)', fontSize: '0.85rem',
              lineHeight: 1.5, maxWidth: '280px', margin: '0 auto 1.5rem auto',
            }}>
              Precision agriculture through real-time IoT sensing and intelligent analytics.
            </p>
          </div>

          <div style={{ marginBottom: '2rem' }} className="welcome-heading">
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.4 }}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                padding: '0.4rem 0.85rem', borderRadius: '999px',
                background: 'rgba(96,191,113,0.08)', border: '1px solid rgba(96,191,113,0.15)',
                color: '#4da85e', fontSize: '0.72rem', fontWeight: 600,
                marginBottom: '1.25rem', letterSpacing: '0.04em', textTransform: 'uppercase',
              }}
            >
              <Shield size={12} />
              Account Recovery
            </motion.div>

            <motion.h2
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
              style={{
                fontSize: '1.85rem', fontWeight: 800, color: '#0f2035',
                marginBottom: '0.4rem', letterSpacing: '-0.025em', lineHeight: 1.2,
              }}
            >
              {step === 1 && 'Forgot Password'}
              {step === 2 && 'Verify OTP'}
              {step === 3 && 'Reset Password'}
              {step === 4 && 'Password Reset'}
            </motion.h2>
            <p style={{ color: '#7a8fa3', fontSize: '0.9rem', lineHeight: 1.5 }} className="recovery-subtitle">
              {step === 1 && "Enter your registered email address to receive an OTP."}
              {step === 2 && "Enter the 6-digit code sent to your email."}
              {step === 3 && "Create a new strong password."}
              {step === 4 && "Your password has been successfully updated."}
            </p>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.5 }}
            className="login-card"
            style={{
              borderRadius: '1.25rem',
              padding: '2rem',
            }}
          >
            <AnimatePresence mode="wait">
              {/* === STEP 1: REQUEST OTP === */}
              {step === 1 && (
                <motion.form 
                  key="step1" 
                  initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}
                  onSubmit={handleRequestOtp}
                >
                  <div style={{ marginBottom: '1.5rem' }}>
                    <label className="login-label" style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: '0.5rem' }}>Email Address</label>
                    <div className={`login-input-container ${isFocused.email ? 'focused' : ''}`}>
                      <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} onFocus={() => setIsFocused(f => ({ ...f, email: true }))} onBlur={() => setIsFocused(f => ({ ...f, email: false }))} placeholder="you@company.com" required className="login-input" style={{ width: '100%', padding: '0.85rem 1rem', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.9rem' }} />
                    </div>
                  </div>
                  {error && <div style={{ color: '#dc2626', fontSize: '0.82rem', marginBottom: '1rem', background: 'rgba(239,68,68,0.06)', padding: '0.75rem', borderRadius: '0.65rem', border: '1px solid rgba(239,68,68,0.2)' }}>⚠ {error}</div>}
                  <motion.button type="submit" disabled={isLoading} whileTap={{ scale: 0.985 }} style={{ width: '100%', padding: '0.95rem', border: 'none', borderRadius: '0.75rem', background: 'linear-gradient(135deg, #60bf71 0%, #4caf5e 50%, #3d9e52 100%)', color: '#ffffff', fontSize: '0.95rem', fontWeight: 700, cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.75 : 1, display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '1.25rem' }}>
                    {isLoading ? 'Sending...' : <><Mail size={18} /> Send OTP</>}
                  </motion.button>
                </motion.form>
              )}

              {/* === STEP 2: VERIFY OTP === */}
              {step === 2 && (
                <motion.form 
                  key="step2" 
                  initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}
                  onSubmit={handleVerifyOtp}
                >
                  <div style={{ marginBottom: '1.5rem' }}>
                    <label className="login-label" style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: '0.5rem' }}>Enter OTP</label>
                    <div className={`login-input-container ${isFocused.otp ? 'focused' : ''}`}>
                      <input type="text" value={otp} onChange={(e) => setOtp(e.target.value)} onFocus={() => setIsFocused(f => ({ ...f, otp: true }))} onBlur={() => setIsFocused(f => ({ ...f, otp: false }))} placeholder="123456" maxLength={6} required className="login-input" style={{ width: '100%', padding: '0.85rem 1rem', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.9rem', letterSpacing: '4px', textAlign: 'center', fontWeight: 'bold' }} />
                    </div>
                  </div>
                  {error && <div style={{ color: '#dc2626', fontSize: '0.82rem', marginBottom: '1rem', background: 'rgba(239,68,68,0.06)', padding: '0.75rem', borderRadius: '0.65rem', border: '1px solid rgba(239,68,68,0.2)' }}>⚠ {error}</div>}
                  <motion.button type="submit" disabled={isLoading} whileTap={{ scale: 0.985 }} style={{ width: '100%', padding: '0.95rem', border: 'none', borderRadius: '0.75rem', background: 'linear-gradient(135deg, #60bf71 0%, #4caf5e 50%, #3d9e52 100%)', color: '#ffffff', fontSize: '0.95rem', fontWeight: 700, cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.75 : 1, display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '1.25rem' }}>
                    {isLoading ? 'Verifying...' : <><Key size={18} /> Verify OTP</>}
                  </motion.button>
                </motion.form>
              )}

              {/* === STEP 3: RESET PASSWORD === */}
              {step === 3 && (
                <motion.form 
                  key="step3" 
                  initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}
                  onSubmit={handleResetPassword}
                >
                  <div style={{ marginBottom: '1.5rem' }}>
                    <label className="login-label" style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: '0.5rem' }}>New Password</label>
                    <div className={`login-input-container ${isFocused.password ? 'focused' : ''}`}>
                      <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} onFocus={() => setIsFocused(f => ({ ...f, password: true }))} onBlur={() => setIsFocused(f => ({ ...f, password: false }))} placeholder="Minimum 6 characters" minLength={6} required className="login-input" style={{ width: '100%', padding: '0.85rem 1rem', border: 'none', outline: 'none', background: 'transparent', fontSize: '0.9rem' }} />
                    </div>
                  </div>
                  {error && <div style={{ color: '#dc2626', fontSize: '0.82rem', marginBottom: '1rem', background: 'rgba(239,68,68,0.06)', padding: '0.75rem', borderRadius: '0.65rem', border: '1px solid rgba(239,68,68,0.2)' }}>⚠ {error}</div>}
                  <motion.button type="submit" disabled={isLoading} whileTap={{ scale: 0.985 }} style={{ width: '100%', padding: '0.95rem', border: 'none', borderRadius: '0.75rem', background: 'linear-gradient(135deg, #60bf71 0%, #4caf5e 50%, #3d9e52 100%)', color: '#ffffff', fontSize: '0.95rem', fontWeight: 700, cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.75 : 1, display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '1.25rem' }}>
                    {isLoading ? 'Updating...' : <><KeyRound size={18} /> Update Password</>}
                  </motion.button>
                </motion.form>
              )}

              {/* === STEP 4: SUCCESS === */}
              {step === 4 && (
                <motion.div 
                  key="step4" 
                  initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}
                  style={{ textAlign: 'center', padding: '1rem 0' }}
                >
                  <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '64px', height: '64px', borderRadius: '50%', background: 'rgba(96,191,113,0.1)', color: '#60bf71', marginBottom: '1rem' }}>
                    <CheckCircle2 size={32} />
                  </div>
                  <h3 className="success-title" style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>All Done!</h3>
                  <p className="success-p" style={{ fontSize: '0.9rem', marginBottom: '1.5rem' }}>Your password has been securely reset.</p>
                  
                  <motion.button onClick={() => navigate('/login')} whileTap={{ scale: 0.985 }} style={{ width: '100%', padding: '0.95rem', border: 'none', borderRadius: '0.75rem', background: '#1f2937', color: '#ffffff', fontSize: '0.95rem', fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}>
                    Go to Login <ArrowLeft size={16} style={{ transform: 'rotate(180deg)' }} />
                  </motion.button>
                </motion.div>
              )}
            </AnimatePresence>

            {step < 4 && (
              <div style={{ textAlign: 'center' }}>
                <button
                  type="button"
                  onClick={() => navigate('/login')}
                  className="back-btn"
                  style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem', transition: 'color 0.2s', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
                >
                  <ArrowLeft size={16} /> Back to Login
                </button>
              </div>
            )}
          </motion.div>

          {/* Footer */}
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.2 }} className="login-footer" style={{ textAlign: 'center', fontSize: '0.75rem', marginTop: '2rem' }}>
            &copy; 2026 <span className="login-footer-brand">INHYDRO</span>&ensp;·&ensp;All rights reserved
          </motion.p>
        </motion.div>
      </div>

      <style>{`
        @keyframes floatOrb1 { 0%, 100% { transform: translate(0, 0) scale(1); } 25% { transform: translate(40px, -30px) scale(1.1); } 50% { transform: translate(-20px, 40px) scale(0.9); } 75% { transform: translate(30px, 20px) scale(1.05); } }
        @keyframes floatOrb2 { 0%, 100% { transform: translate(0, 0) scale(1); } 33% { transform: translate(-40px, -20px) scale(1.08); } 66% { transform: translate(30px, 30px) scale(0.92); } }
        @keyframes floatOrb3 { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(25px, -35px) scale(1.12); } }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Desktop Styles */
        .mobile-header {
          display: none !important;
        }
        .login-card {
          background: #ffffff;
          border: 1px solid rgba(0,0,0,0.06);
          box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 8px 32px rgba(0,0,0,0.06);
        }
        .login-label {
          color: #374151;
        }
        .login-input-container {
          position: relative;
          border-radius: 0.75rem;
          border: 2px solid #e5e7eb;
          background: #f9fafb;
          display: flex;
          align-items: center;
          transition: all 0.25s cubic-bezier(0.4,0,0.2,1);
        }
        .login-input-container.focused {
          border: 2px solid #60bf71;
          background: rgba(96,191,113,0.02);
          box-shadow: 0 0 0 4px rgba(96,191,113,0.08);
        }
        .login-input {
          color: #1f2937;
        }
        input::placeholder {
          color: #b0b8c4 !important;
        }
        .success-title {
          color: #1f2937;
        }
        .success-p {
          color: #6b7280;
        }
        .back-btn {
          color: #60bf71;
        }
        .back-btn:hover {
          color: #3d945a;
        }
        .login-footer {
          color: #9ca3af;
        }
        .login-footer-brand {
          color: #374151;
          font-weight: 700;
        }

        /* Mobile Styles */
        @media (max-width: 900px) {
          .login-left-panel {
            display: none !important;
          }
          .login-right-panel {
            flex: 1 1 100% !important;
            background: linear-gradient(180deg, #0f2035 0%, #132a42 50%, #0a1628 100%) !important;
            overflow-y: auto !important;
            padding: 2rem 1.5rem !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: flex-start !important;
            align-items: center !important;
          }
          .login-right-content-wrapper {
            margin: 2rem 0 !important;
          }
          .mobile-header {
            display: flex !important;
            flex-direction: column;
            align-items: center;
            text-align: center;
          }
          .welcome-heading {
            display: none !important;
          }
          .login-card {
            background: rgba(30, 41, 59, 0.45) !important;
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25) !important;
          }
          .login-label {
            color: rgba(255, 255, 255, 0.9) !important;
          }
          .login-input-container {
            border: 2px solid rgba(255, 255, 255, 0.1) !important;
            background: rgba(15, 23, 42, 0.5) !important;
          }
          .login-input-container.focused {
            border: 2px solid #60bf71 !important;
            background: rgba(96,191,113,0.04) !important;
            box-shadow: 0 0 0 4px rgba(96,191,113,0.15) !important;
          }
          .login-input {
            color: #ffffff !important;
          }
          input::placeholder {
            color: #64748b !important;
          }
          .success-title {
            color: #ffffff !important;
          }
          .success-p {
            color: rgba(255, 255, 255, 0.6) !important;
          }
          .back-btn {
            color: #60bf71 !important;
          }
          .back-btn:hover {
            color: #8dd99b !important;
          }
          .login-footer {
            color: rgba(255, 255, 255, 0.4) !important;
          }
          .login-footer-brand {
            color: rgba(255, 255, 255, 0.7) !important;
          }
        }

        @media (max-width: 480px) {
          .login-right-panel {
            padding: 1.25rem !important;
          }
          .login-right-content-wrapper {
            margin: 1rem 0 !important;
          }
        }

        input:focus {
          outline: none;
        }
      `}</style>
    </div>
  );
};

export default ForgotPassword;