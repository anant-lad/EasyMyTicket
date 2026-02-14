import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { User } from '../types';
import api from '../services/api';

interface AuthContextType {
  user: User | null;
  login: (userId: string, password: string, role: 'user' | 'technician' | 'super_admin' | 'org_admin') => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedUser = localStorage.getItem('user');
    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser));
      } catch (error) {
        localStorage.removeItem('user');
      }
    }
    setLoading(false);
  }, []);

  const login = async (userId: string, password: string, role: 'user' | 'technician' | 'super_admin' | 'org_admin') => {
    setLoading(true);
    try {
      const response = await api.post('/auth/login', {
        user_id: userId,
        password: password,
        role: role
      });

      let userData: User | null = null;
      let companyId = '';

      if (response.data.success) {
        userData = response.data.user;
        companyId = userData?.companyid || '';

        // Fetch organization details
        if (companyId) {
          try {
            const orgResponse = await api.get(`/organizations/${companyId}`);
            if (orgResponse.data.success) {
              userData!.organization = orgResponse.data.organization;
            }
          } catch (error) {
            console.error('Failed to fetch organization details', error);
          }
        }

        setUser(userData);
        localStorage.setItem('user', JSON.stringify(userData));
        localStorage.setItem('token', response.data.token || '');
      } else {
        throw new Error(response.data.message || 'Login failed');
      }

    } catch (error: any) {
      throw new Error(error.response?.data?.detail || error.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem('user');
    localStorage.removeItem('token');
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
