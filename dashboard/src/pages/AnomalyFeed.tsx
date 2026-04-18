import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, X, TrendingUp } from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { fetchAnomalies, type AnomalyEvent } from '../api/client';
import { formatDistanceToNow } from 'date-fns';
import { clsx } from 'clsx';

const MOCK_ANOMALIES: AnomalyEvent[] = [
  {
    id: 1,
    timestamp: new Date(Date.now() - 5 * 60_000).toISOString(),
    service: 'backend',
    namespace: 'production',
    metric: 'http_error_rate',
    anomalyScore: 0.92,
    severity: 'critical',
    currentValue: 0.18,
    rootCauseAnalysis:
      '**What\'s happening:** The backend service is returning HTTP 5xx errors at 18% — significantly above the predicted 2% baseline.\n**Likely cause:** A new deployment was rolled out 45 minutes ago correlating with the error spike. The deployment likely introduced a regression in the database connection pool.\n**Recommended action:** Rollback to the previous deployment revision immediately.',
  },
  {
    id: 2,
    timestamp: new Date(Date.now() - 22 * 60_000).toISOString(),
    service: 'frontend',
    namespace: 'production',
    metric: 'memory_usage',
    anomalyScore: 0.78,
    severity: 'warning',
    currentValue: 445_000_000,
    rootCauseAnalysis:
      '**What\'s happening:** Frontend memory usage has been growing linearly for the past 2 hours.\n**Likely cause:** Possible memory leak in the Node.js event listener registration — a common issue with Express middleware.\n**Recommended action:** Restart the frontend pods to reclaim memory while investigating the root cause.',
  },
  {
    id: 3,
    timestamp: new Date(Date.now() - 67 * 60_000).toISOString(),
    service: 'backend',
    namespace: 'production',
    metric: 'request_latency_p99',
    anomalyScore: 0.81,
    severity: 'warning',
    currentValue: 3.2,
    rootCauseAnalysis:
      '**What\'s happening:** p99 request latency has increased to 3.2s, well above the predicted 0.4s baseline.\n**Likely cause:** Database query performance degradation — likely a missing index on a recently added query.\n**Recommended action:** Check slow query logs and add appropriate indexes.',
  },
];

function SeverityBadge({ severity }: { severity: string }) {
  const classes = {
    critical: 'badge-red',
    warning: 'badge-yellow',
    info: 'badge-blue',
  }[severity] ?? 'badge-blue';
  return <span className={classes}>{severity.toUpperCase()}</span>;
}

function ScoreBar({ score }: { score: number }) {
  const color =
    score >= 0.9 ? 'bg-red-500' : score >= 0.75 ? 'bg-yellow-500' : 'bg-green-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full', color)}
          style={{ width: `${score * 100}%` }}
        />
      </div>
      <span className="text-xs font-mono text-gray-400 w-10 text-right">
        {score.toFixed(2)}
      </span>
    </div>
  );
}

// Generate mock time-series for the modal chart
function generateAnomalyChart(score: number) {
  const now = Date.now();
  return Array.from({ length: 30 }, (_, i) => {
    const isAnomaly = i >= 22;
    return {
      time: new Date(now - (29 - i) * 2 * 60_000).toLocaleTimeString(),
      value: isAnomaly ? 0.05 + Math.random() * 0.15 + score * 0.1 : 0.01 + Math.random() * 0.03,
      upper: 0.06,
      lower: 0,
    };
  });
}

function AnomalyModal({
  event,
  onClose,
}: {
  event: AnomalyEvent;
  onClose: () => void;
}) {
  const chartData = React.useMemo(() => generateAnomalyChart(event.anomalyScore), [event.anomalyScore]);

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-gray-800 flex items-start justify-between">
          <div>
            <h3 id="modal-title" className="text-lg font-bold text-white">
              Anomaly Detail — {event.service}
            </h3>
            <p className="text-gray-400 text-sm mt-1">
              {formatDistanceToNow(new Date(event.timestamp), { addSuffix: true })}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors p-1"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Metric chart */}
          <div>
            <h4 className="text-sm font-medium text-gray-400 mb-3">
              {event.metric} — Last 60 Minutes
            </h4>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="time" stroke="#6b7280" tick={{ fontSize: 10 }} interval={4} />
                <YAxis stroke="#6b7280" tick={{ fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
                />
                <ReferenceLine y={0.06} stroke="#ef4444" strokeDasharray="4 4" label={{ value: 'Threshold', fill: '#ef4444', fontSize: 10 }} />
                <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} name="Value" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Root cause analysis */}
          <div>
            <h4 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
              <TrendingUp className="w-4 h-4" />
              AI Root Cause Analysis
            </h4>
            <div className="bg-gray-800/50 rounded-lg p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-line">
              {event.rootCauseAnalysis}
            </div>
          </div>

          {/* Metadata */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            {[
              ['Service', event.service],
              ['Namespace', event.namespace],
              ['Metric', event.metric],
              ['Anomaly Score', event.anomalyScore.toFixed(3)],
              ['Current Value', event.currentValue.toFixed(4)],
              ['Severity', event.severity.toUpperCase()],
            ].map(([label, value]) => (
              <div key={label}>
                <span className="text-gray-500">{label}</span>
                <p className="text-white font-medium mt-0.5">{value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AnomalyFeed() {
  const [selectedEvent, setSelectedEvent] = useState<AnomalyEvent | null>(null);

  const { data, isLoading } = useQuery<AnomalyEvent[]>({
    queryKey: ['anomalies'],
    queryFn: () => fetchAnomalies(50),
    refetchInterval: 15_000,
    placeholderData: MOCK_ANOMALIES,
  });

  const events = data ?? MOCK_ANOMALIES;

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Anomaly Feed</h2>
          <p className="text-gray-400 mt-1">Live AI-detected anomalies across your cluster</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-green-400">
          <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
          Live monitoring active
        </div>
      </div>

      {isLoading && events.length === 0 ? (
        <div className="text-gray-400 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 animate-pulse" />
          Loading anomaly feed...
        </div>
      ) : events.length === 0 ? (
        <div className="card text-center py-12">
          <AlertTriangle className="w-12 h-12 text-green-400 mx-auto mb-4" />
          <p className="text-white font-medium">No anomalies detected</p>
          <p className="text-gray-400 text-sm mt-1">All services are operating within normal parameters</p>
        </div>
      ) : (
        <div className="space-y-3">
          {events.map((event) => (
            <button
              key={event.id}
              onClick={() => setSelectedEvent(event)}
              className="card w-full text-left hover:border-gray-600 transition-colors cursor-pointer"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-semibold text-white">{event.service}</span>
                    <SeverityBadge severity={event.severity} />
                    <span className="text-gray-500 text-xs font-mono">{event.metric}</span>
                  </div>
                  <p className="text-gray-400 text-sm mt-2 line-clamp-2">
                    {event.rootCauseAnalysis.split('\n')[0].replace(/\*\*/g, '')}
                  </p>
                </div>
                <div className="flex-shrink-0 w-32 space-y-1">
                  <ScoreBar score={event.anomalyScore} />
                  <p className="text-xs text-gray-500 text-right">
                    {formatDistanceToNow(new Date(event.timestamp), { addSuffix: true })}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {selectedEvent && (
        <AnomalyModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  );
}
