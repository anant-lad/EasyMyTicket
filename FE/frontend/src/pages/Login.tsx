import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import toast from 'react-hot-toast';
import ParticleBackground from '../components/auth/ParticleBackground';

const Login: React.FC = () => {
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'user' | 'technician' | 'super_admin' | 'org_admin'>('user');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(userId, password, role);
      toast.success('Welcome back!');
      navigate(
        role === 'user' ? '/user/dashboard' :
          role === 'technician' ? '/technician/dashboard' :
            role === 'org_admin' ? '/org/dashboard' :
              '/admin/dashboard'
      );
    } catch (error: any) {
      toast.error(error.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen flex bg-white font-sans overflow-hidden">
      <style>{`
            @keyframes blob {
                0% { transform: translate(0px, 0px) scale(1); }
                33% { transform: translate(30px, -50px) scale(1.1); }
                66% { transform: translate(-20px, 20px) scale(0.9); }
                100% { transform: translate(0px, 0px) scale(1); }
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            @keyframes float {
                0%, 100% { transform: translateY(0); }
                50% { transform: translateY(-10px); }
            }
            @keyframes gridMove {
                0% { background-position: 0 0; }
                100% { background-position: 40px 40px; }
            }
            .animate-blob { animation: blob 10s infinite; }
            .animate-delay-2000 { animation-delay: 2s; }
            .animate-delay-4000 { animation-delay: 4s; }
            .animate-float { animation: float 6s ease-in-out infinite; }
            .animate-grid { animation: gridMove 20s linear infinite; }
            .animate-grid-slow { animation: gridMove 30s linear infinite; }
            .fade-in-up { animation: fadeIn 0.6s ease-out forwards; opacity: 0; }
            .delay-100 { animation-delay: 0.1s; }
            .delay-200 { animation-delay: 0.2s; }
            .delay-300 { animation-delay: 0.3s; }
        `}</style>

      {/* Unified Particle Background */}
      <div className="absolute inset-0 z-0">
        <ParticleBackground />
        <div className="absolute inset-0 bg-white/40 z-0"></div> {/* Subtle overlay to ensure readability */}
      </div>

      <div className="flex w-full h-full relative z-10">
        {/* Left Column - Auth Form */}
        <div className="flex-1 flex flex-col justify-center px-4 sm:px-6 lg:px-20 xl:px-24 relative overflow-hidden">
          <div className="w-full max-w-md mx-auto relative z-10">
            {/* Glass Card Container */}
            <div className="bg-white/60 backdrop-blur-xl border border-white/60 rounded-3xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] p-8 sm:p-10 fade-in-up">

              {/* Mobile Logo */}
              <div className="lg:hidden mb-8">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                  </div>
                  <span className="text-2xl font-bold text-gray-900">EaseMyTkt</span>
                </div>
              </div>

              <div className="mb-8">
                <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Welcome back</h1>
                <p className="mt-2 text-sm text-slate-500">
                  Please enter your details to sign in to your workspace.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5">
                {/* Role Selector */}
                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Select Account Type</label>
                  <div className="grid grid-cols-2 gap-3">
                    {(['user', 'technician', 'org_admin', 'super_admin'] as const).map((r) => (
                      <button
                        key={r}
                        type="button"
                        onClick={() => setRole(r)}
                        className={`
                                px-3 py-2.5 text-sm font-medium rounded-xl border transition-all duration-200 flex items-center justify-center
                                ${role === r
                            ? 'bg-indigo-600 border-indigo-600 text-white shadow-md shadow-indigo-200 transform scale-[1.02]'
                            : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-300'}
                            `}
                      >
                        {r === 'super_admin' ? 'Super Admin' :
                          r === 'org_admin' ? 'Org Admin' :
                            r.charAt(0).toUpperCase() + r.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="group">
                    <label className="block text-sm font-medium text-slate-700 mb-1.5 ml-1">User ID</label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                        <svg className="h-5 w-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                        </svg>
                      </div>
                      <input
                        type="text"
                        required
                        value={userId}
                        onChange={(e) => setUserId(e.target.value)}
                        className="w-full pl-11 pr-4 py-3 rounded-xl border border-slate-200 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all bg-white/50 hover:bg-white text-slate-900 placeholder-slate-400"
                        placeholder="Enter your ID"
                      />
                    </div>
                  </div>

                  <div className="group">
                    <label className="block text-sm font-medium text-slate-700 mb-1.5 ml-1">Password</label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                        <svg className="h-5 w-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                      </div>
                      <input
                        type="password"
                        required
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="w-full pl-11 pr-4 py-3 rounded-xl border border-slate-200 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all bg-white/50 hover:bg-white text-slate-900 placeholder-slate-400"
                        placeholder="••••••••"
                      />
                    </div>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex justify-center py-3.5 px-4 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-700 hover:to-violet-700 text-white rounded-xl shadow-lg shadow-indigo-500/30 text-sm font-semibold tracking-wide transition-all duration-300 transform hover:-translate-y-0.5 disabled:opacity-70 disabled:cursor-not-allowed"
                >
                  {loading ? (
                    <span className="flex items-center gap-2">
                      <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Signing in...
                    </span>
                  ) : 'Sign in'}
                </button>
              </form>
            </div>

            <div className="mt-8 text-center space-y-2 fade-in-up delay-200">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/50 backdrop-blur-sm border border-indigo-100/50">
                <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
                <span className="text-[10px] font-semibold text-indigo-700 uppercase tracking-wider">System Operational</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column - Visuals */}
        <div className="hidden lg:flex lg:w-1/2 relative items-center justify-center p-8">

          <div className="relative z-10 max-w-lg px-8 animate-float">
            <div className="bg-white/40 backdrop-blur-xl border border-white/40 p-8 rounded-3xl shadow-2xl shadow-indigo-100/20">
              <div className="mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-600 text-white shadow-sm">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </span>
                  <span className="text-sm font-bold tracking-wider text-indigo-900 uppercase">EaseMyTkt</span>
                </div>

                <h2 className="text-3xl font-extrabold text-gray-900 mb-3 bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-purple-600 leading-tight">
                  Enterprise Grade Ticketing Software
                </h2>
                <p className="text-slate-700 text-lg leading-relaxed font-medium">
                  Experience the power of automated classification. Our AI instant-routes 95% of tickets to the right expert in seconds.
                </p>
              </div>

              {/* Stats / Interactive Element */}
              <div className="grid grid-cols-2 gap-4 mt-8">
                <div className="bg-white/60 p-4 rounded-2xl shadow-sm border border-indigo-50/50">
                  <div className="text-3xl font-bold text-indigo-600 mb-1">98%</div>
                  <div className="text-xs text-gray-600 font-bold uppercase tracking-wide">Accuracy</div>
                </div>
                <div className="bg-white/60 p-4 rounded-2xl shadow-sm border border-indigo-50/50">
                  <div className="text-3xl font-bold text-purple-600 mb-1">&lt;2min</div>
                  <div className="text-xs text-gray-600 font-bold uppercase tracking-wide">Response Time</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;
