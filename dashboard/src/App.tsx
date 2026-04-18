import React from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  Clock,
  DollarSign,
  Zap,
  Server,
} from 'lucide-react';
import ClusterHealth from './pages/ClusterHealth';
import AnomalyFeed from './pages/AnomalyFeed';
import IncidentHistory from './pages/IncidentHistory';
import CostOptimizer from './pages/CostOptimizer';
import ChaosMode from './pages/ChaosMode';

const navItems = [
  { to: '/', label: 'Cluster Health', icon: Activity },
  { to: '/anomalies', label: 'Anomaly Feed', icon: AlertTriangle },
  { to: '/incidents', label: 'Incident History', icon: Clock },
  { to: '/cost', label: 'Cost Optimizer', icon: DollarSign },
  { to: '/chaos', label: 'Chaos Mode', icon: Zap },
];

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex">
        {/* Sidebar */}
        <aside className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
          {/* Logo */}
          <div className="p-6 border-b border-gray-800">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
                <Server className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-white font-bold text-lg leading-none">InfraGPT</h1>
                <p className="text-gray-500 text-xs mt-0.5">AI-Powered K8s Platform</p>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-4 space-y-1">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-400 hover:text-white hover:bg-gray-800'
                  }`
                }
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {label}
              </NavLink>
            ))}
          </nav>

          {/* Footer */}
          <div className="p-4 border-t border-gray-800">
            <p className="text-xs text-gray-600 text-center">
              v1.0.0 · Self-Healing Active
            </p>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<ClusterHealth />} />
            <Route path="/anomalies" element={<AnomalyFeed />} />
            <Route path="/incidents" element={<IncidentHistory />} />
            <Route path="/cost" element={<CostOptimizer />} />
            <Route path="/chaos" element={<ChaosMode />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
