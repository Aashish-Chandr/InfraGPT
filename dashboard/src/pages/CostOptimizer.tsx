import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { DollarSign, TrendingDown, AlertCircle } from 'lucide-react';
import { fetchCostData, type PodCostInfo } from '../api/client';

const MOCK_COST_DATA: PodCostInfo[] = [
  {
    namespace: 'production',
    pod: 'backend-7d9f8b-xk2p1',
    container: 'backend',
    requestedCpu: 500,
    actualCpuP95: 48,
    requestedMemoryMi: 512,
    actualMemoryP95Mi: 89,
    cpuWastePercent: 90.4,
    memoryWastePercent: 82.6,
    estimatedMonthlySavingsUsd: 12.40,
    suggestedCpuRequest: '100m',
    suggestedMemoryRequest: '128Mi',
  },
  {
    namespace: 'production',
    pod: 'frontend-5c8d7f-mn3q2',
    container: 'frontend',
    requestedCpu: 500,
    actualCpuP95: 62,
    requestedMemoryMi: 512,
    actualMemoryP95Mi: 145,
    cpuWastePercent: 87.6,
    memoryWastePercent: 71.7,
    estimatedMonthlySavingsUsd: 10.80,
    suggestedCpuRequest: '150m',
    suggestedMemoryRequest: '200Mi',
  },
  {
    namespace: 'monitoring',
    pod: 'grafana-6b9c4d-pq7r3',
    container: 'grafana',
    requestedCpu: 500,
    actualCpuP95: 95,
    requestedMemoryMi: 512,
    actualMemoryP95Mi: 310,
    cpuWastePercent: 81.0,
    memoryWastePercent: 39.5,
    estimatedMonthlySavingsUsd: 7.20,
    suggestedCpuRequest: '200m',
    suggestedMemoryRequest: '400Mi',
  },
];

function WasteBar({ percent }: { percent: number }) {
  const color =
    percent >= 80 ? 'bg-red-500' : percent >= 60 ? 'bg-yellow-500' : 'bg-green-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-12 text-right">{percent.toFixed(1)}%</span>
    </div>
  );
}

export default function CostOptimizer() {
  const { data } = useQuery<PodCostInfo[]>({
    queryKey: ['cost-data'],
    queryFn: fetchCostData,
    refetchInterval: 60_000,
    placeholderData: MOCK_COST_DATA,
  });

  const pods = data ?? MOCK_COST_DATA;
  const totalSavings = pods.reduce((sum, p) => sum + p.estimatedMonthlySavingsUsd, 0);
  const avgCpuWaste = pods.reduce((sum, p) => sum + p.cpuWastePercent, 0) / pods.length;
  const avgMemWaste = pods.reduce((sum, p) => sum + p.memoryWastePercent, 0) / pods.length;

  return (
    <div className="p-8 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Cost Optimizer</h2>
        <p className="text-gray-400 mt-1">
          Identify over-provisioned pods and right-size resource requests
        </p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="stat-card">
          <DollarSign className="w-8 h-8 text-green-400" />
          <div className="stat-value text-green-400">${totalSavings.toFixed(2)}</div>
          <div className="stat-label">Estimated Monthly Savings</div>
          <div className="text-xs text-gray-600">by right-sizing {pods.length} containers</div>
        </div>
        <div className="stat-card">
          <TrendingDown className="w-8 h-8 text-yellow-400" />
          <div className="stat-value">{avgCpuWaste.toFixed(1)}%</div>
          <div className="stat-label">Avg CPU Over-Provisioning</div>
        </div>
        <div className="stat-card">
          <AlertCircle className="w-8 h-8 text-orange-400" />
          <div className="stat-value">{avgMemWaste.toFixed(1)}%</div>
          <div className="stat-label">Avg Memory Over-Provisioning</div>
        </div>
      </div>

      {/* Recommendations Table */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4">Right-Sizing Recommendations</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 border-b border-gray-800">
                <th className="text-left py-3 pr-4">Container</th>
                <th className="text-right py-3 pr-4">CPU Waste</th>
                <th className="text-right py-3 pr-4">Mem Waste</th>
                <th className="text-right py-3 pr-4">Suggested CPU</th>
                <th className="text-right py-3 pr-4">Suggested Mem</th>
                <th className="text-right py-3">Monthly Savings</th>
              </tr>
            </thead>
            <tbody>
              {pods
                .sort((a, b) => b.estimatedMonthlySavingsUsd - a.estimatedMonthlySavingsUsd)
                .map((pod) => (
                  <tr key={pod.pod} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-3 pr-4">
                      <div className="font-mono text-blue-400 text-xs">{pod.container}</div>
                      <div className="text-gray-500 text-xs mt-0.5">{pod.namespace}</div>
                    </td>
                    <td className="py-3 pr-4">
                      <WasteBar percent={pod.cpuWastePercent} />
                    </td>
                    <td className="py-3 pr-4">
                      <WasteBar percent={pod.memoryWastePercent} />
                    </td>
                    <td className="py-3 pr-4 text-right font-mono text-green-400 text-xs">
                      {pod.suggestedCpuRequest}
                    </td>
                    <td className="py-3 pr-4 text-right font-mono text-green-400 text-xs">
                      {pod.suggestedMemoryRequest}
                    </td>
                    <td className="py-3 text-right text-green-400 font-semibold">
                      ${pod.estimatedMonthlySavingsUsd.toFixed(2)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-blue-900/20 border border-blue-800 rounded-lg p-4 text-sm text-blue-300">
        <strong>Note:</strong> These recommendations are based on p95 actual usage over the last 7 days.
        Apply changes gradually and monitor for performance regressions. Use{' '}
        <code className="font-mono bg-blue-900/40 px-1 rounded">kubectl set resources</code> or update
        your Kustomize overlays.
      </div>
    </div>
  );
}
