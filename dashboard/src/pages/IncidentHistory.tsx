import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clock, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { fetchIncidents, type IncidentStats } from '../api/client';
import { formatDistanceToNow } from 'date-fns';
import { clsx } from 'clsx';

const MOCK_INCIDENTS: IncidentStats = {
  totalIncidents: 47,
  resolvedIncidents: 44,
  mttrSeconds: 94,
  incidents: [
    {
      id: 47,
      timestamp: new Date(Date.now() - 5 * 60_000).toISOString(),
      service: 'backend',
      namespace: 'production',
      metric: 'http_error_rate',
      anomalyScore: 0.92,
      severity: 'critical',
      rootCauseAnalysis: 'Deployment regression causing database connection pool exhaustion.',
      healingAction: 'rollback',
      healingSuccess: true,
      healingDurationSeconds: 87,
      resolvedAt: new Date(Date.now() - 3 * 60_000).toISOString(),
    },
    {
      id: 46,
      timestamp: new Date(Date.now() - 2 * 3600_000).toISOString(),
      service: 'frontend',
      namespace: 'production',
      metric: 'memory_usage',
      anomalyScore: 0.78,
      severity: 'warning',
      rootCauseAnalysis: 'Memory leak in Express middleware.',
      healingAction: 'restart',
      healingSuccess: true,
      healingDurationSeconds: 45,
      resolvedAt: new Date(Date.now() - 2 * 3600_000 + 45_000).toISOString(),
    },
    {
      id: 45,
      timestamp: new Date(Date.now() - 6 * 3600_000).toISOString(),
      service: 'backend',
      namespace: 'production',
      metric: 'cpu_usage',
      anomalyScore: 0.85,
      severity: 'warning',
      rootCauseAnalysis: 'Traffic spike from marketing campaign.',
      healingAction: 'scale-up',
      healingSuccess: true,
      healingDurationSeconds: 120,
      resolvedAt: new Date(Date.now() - 6 * 3600_000 + 120_000).toISOString(),
    },
  ],
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function ActionBadge({ action }: { action: string | null }) {
  if (!action) return <span className="text-gray-600 text-xs">—</span>;
  const classes: Record<string, string> = {
    rollback: 'badge-red',
    restart: 'badge-yellow',
    'scale-up': 'badge-blue',
    'notify-only': 'badge-green',
  };
  return <span className={classes[action] ?? 'badge-blue'}>{action}</span>;
}

export default function IncidentHistory() {
  const { data } = useQuery<IncidentStats>({
    queryKey: ['incidents'],
    queryFn: fetchIncidents,
    refetchInterval: 30_000,
    placeholderData: MOCK_INCIDENTS,
  });

  const stats = data ?? MOCK_INCIDENTS;
  const resolutionRate =
    stats.totalIncidents > 0
      ? ((stats.resolvedIncidents / stats.totalIncidents) * 100).toFixed(1)
      : '0';

  return (
    <div className="p-8 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Incident History</h2>
        <p className="text-gray-400 mt-1">Complete audit trail of all self-healing actions</p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="stat-card">
          <AlertTriangle className="w-8 h-8 text-yellow-400" />
          <div className="stat-value">{stats.totalIncidents}</div>
          <div className="stat-label">Total Incidents</div>
        </div>
        <div className="stat-card">
          <CheckCircle className="w-8 h-8 text-green-400" />
          <div className="stat-value">{stats.resolvedIncidents}</div>
          <div className="stat-label">Auto-Resolved</div>
        </div>
        <div className="stat-card">
          <Clock className="w-8 h-8 text-blue-400" />
          <div className="stat-value">{formatDuration(stats.mttrSeconds)}</div>
          <div className="stat-label">Mean Time to Recovery</div>
          <div className="text-xs text-gray-600">vs ~15min manual response</div>
        </div>
        <div className="stat-card">
          <CheckCircle className="w-8 h-8 text-purple-400" />
          <div className="stat-value">{resolutionRate}%</div>
          <div className="stat-label">Auto-Resolution Rate</div>
        </div>
      </div>

      {/* Timeline */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-6">Incident Timeline</h3>
        <div className="space-y-4">
          {stats.incidents.map((incident, idx) => (
            <div key={incident.id} className="flex gap-4">
              {/* Timeline line */}
              <div className="flex flex-col items-center">
                <div
                  className={clsx(
                    'w-3 h-3 rounded-full flex-shrink-0 mt-1',
                    incident.healingSuccess ? 'bg-green-500' : 'bg-red-500'
                  )}
                />
                {idx < stats.incidents.length - 1 && (
                  <div className="w-px flex-1 bg-gray-800 mt-1" />
                )}
              </div>

              {/* Content */}
              <div className="flex-1 pb-6">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-white">#{incident.id}</span>
                      <span className="text-blue-400 font-mono text-sm">{incident.service}</span>
                      <ActionBadge action={incident.healingAction} />
                      {incident.healingSuccess ? (
                        <span className="flex items-center gap-1 text-green-400 text-xs">
                          <CheckCircle className="w-3 h-3" /> Resolved
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-red-400 text-xs">
                          <XCircle className="w-3 h-3" /> Failed
                        </span>
                      )}
                    </div>
                    <p className="text-gray-400 text-sm mt-1">{incident.rootCauseAnalysis}</p>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-xs text-gray-500">
                      {formatDistanceToNow(new Date(incident.timestamp), { addSuffix: true })}
                    </p>
                    {incident.healingDurationSeconds && (
                      <p className="text-xs text-gray-600 mt-0.5">
                        Healed in {formatDuration(incident.healingDurationSeconds)}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
