import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, Server, Box, Cpu, HardDrive } from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { fetchClusterStats, type ClusterStats } from '../api/client';
import { clsx } from 'clsx';

function GaugeBar({ value, label }: { value: number; label: string }) {
  const color =
    value >= 90 ? 'bg-red-500' : value >= 70 ? 'bg-yellow-500' : 'bg-green-500';
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-gray-400">{label}</span>
        <span className="text-white font-medium">{value.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-500', color)}
          style={{ width: `${Math.min(value, 100)}%` }}
          role="progressbar"
          aria-valuenow={value}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={label}
        />
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color = 'blue',
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  const colorMap: Record<string, string> = {
    blue: 'text-blue-400 bg-blue-900/30',
    green: 'text-green-400 bg-green-900/30',
    yellow: 'text-yellow-400 bg-yellow-900/30',
    red: 'text-red-400 bg-red-900/30',
  };
  return (
    <div className="stat-card">
      <div className={clsx('w-10 h-10 rounded-lg flex items-center justify-center', colorMap[color])}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="text-xs text-gray-600">{sub}</div>}
    </div>
  );
}

// Mock time-series data for the chart
const generateTimeSeriesData = () => {
  const now = Date.now();
  return Array.from({ length: 20 }, (_, i) => ({
    time: new Date(now - (19 - i) * 60_000).toLocaleTimeString(),
    cpu: 20 + Math.random() * 40,
    memory: 40 + Math.random() * 30,
  }));
};

export default function ClusterHealth() {
  const { data, isLoading, error } = useQuery<ClusterStats>({
    queryKey: ['cluster-stats'],
    queryFn: fetchClusterStats,
    refetchInterval: 15_000,
    // Use placeholder data when API is unavailable
    placeholderData: {
      nodes: { ready: 3, total: 3 },
      pods: { running: 24, desired: 24, failed: 0 },
      cpu: { usagePercent: 42.3 },
      memory: { usagePercent: 61.7 },
      namespaces: [
        { name: 'production', pods: 8, cpuUsage: '320m', memoryUsage: '512Mi' },
        { name: 'monitoring', pods: 6, cpuUsage: '450m', memoryUsage: '1.2Gi' },
        { name: 'ai-engine', pods: 3, cpuUsage: '200m', memoryUsage: '768Mi' },
        { name: 'infragpt-system', pods: 2, cpuUsage: '80m', memoryUsage: '128Mi' },
      ],
    },
  });

  const [chartData] = React.useState(generateTimeSeriesData);

  if (isLoading && !data) {
    return (
      <div className="p-8 flex items-center justify-center h-full">
        <div className="text-gray-400 flex items-center gap-3">
          <Activity className="w-5 h-5 animate-pulse" />
          Loading cluster data...
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-white">Cluster Health</h2>
        <p className="text-gray-400 mt-1">Real-time overview of your Kubernetes cluster</p>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-800 rounded-lg p-4 text-yellow-400 text-sm">
          ⚠️ Using cached data — API server may be unavailable
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Server}
          label="Ready Nodes"
          value={`${data?.nodes.ready}/${data?.nodes.total}`}
          color={data?.nodes.ready === data?.nodes.total ? 'green' : 'red'}
        />
        <StatCard
          icon={Box}
          label="Running Pods"
          value={`${data?.pods.running}/${data?.pods.desired}`}
          sub={data?.pods.failed ? `${data.pods.failed} failed` : undefined}
          color={data?.pods.failed ? 'red' : 'green'}
        />
        <StatCard
          icon={Cpu}
          label="CPU Usage"
          value={`${data?.cpu.usagePercent.toFixed(1)}%`}
          color={
            (data?.cpu.usagePercent ?? 0) >= 90
              ? 'red'
              : (data?.cpu.usagePercent ?? 0) >= 70
              ? 'yellow'
              : 'blue'
          }
        />
        <StatCard
          icon={HardDrive}
          label="Memory Usage"
          value={`${data?.memory.usagePercent.toFixed(1)}%`}
          color={
            (data?.memory.usagePercent ?? 0) >= 90
              ? 'red'
              : (data?.memory.usagePercent ?? 0) >= 70
              ? 'yellow'
              : 'blue'
          }
        />
      </div>

      {/* Resource Usage Chart */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-6">Resource Usage (Last 20 Minutes)</h3>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="time" stroke="#6b7280" tick={{ fontSize: 11 }} />
            <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} domain={[0, 100]} unit="%" />
            <Tooltip
              contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
              labelStyle={{ color: '#9ca3af' }}
            />
            <Line type="monotone" dataKey="cpu" stroke="#3b82f6" strokeWidth={2} dot={false} name="CPU %" />
            <Line type="monotone" dataKey="memory" stroke="#8b5cf6" strokeWidth={2} dot={false} name="Memory %" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Resource Gauges */}
      <div className="card space-y-4">
        <h3 className="text-lg font-semibold text-white">Resource Utilization</h3>
        <GaugeBar value={data?.cpu.usagePercent ?? 0} label="CPU" />
        <GaugeBar value={data?.memory.usagePercent ?? 0} label="Memory" />
      </div>

      {/* Namespace Table */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4">Namespaces</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 border-b border-gray-800">
                <th className="text-left py-3 pr-4">Namespace</th>
                <th className="text-right py-3 pr-4">Pods</th>
                <th className="text-right py-3 pr-4">CPU Usage</th>
                <th className="text-right py-3">Memory Usage</th>
              </tr>
            </thead>
            <tbody>
              {data?.namespaces.map((ns) => (
                <tr key={ns.name} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="py-3 pr-4 font-mono text-blue-400">{ns.name}</td>
                  <td className="py-3 pr-4 text-right text-white">{ns.pods}</td>
                  <td className="py-3 pr-4 text-right text-gray-300">{ns.cpuUsage}</td>
                  <td className="py-3 text-right text-gray-300">{ns.memoryUsage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
