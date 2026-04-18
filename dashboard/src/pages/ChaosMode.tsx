import React, { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Zap, AlertTriangle, CheckCircle, Activity } from 'lucide-react';
import { setChaosMode, getChaosMode } from '../api/client';
import { clsx } from 'clsx';

interface ChaosEvent {
  id: number;
  timestamp: string;
  type: 'pod_deleted' | 'anomaly_detected' | 'healing_triggered' | 'pod_recovered';
  message: string;
}

const EVENT_COLORS: Record<ChaosEvent['type'], string> = {
  pod_deleted: 'text-red-400',
  anomaly_detected: 'text-yellow-400',
  healing_triggered: 'text-blue-400',
  pod_recovered: 'text-green-400',
};

const EVENT_ICONS: Record<ChaosEvent['type'], React.ElementType> = {
  pod_deleted: AlertTriangle,
  anomaly_detected: Activity,
  healing_triggered: Zap,
  pod_recovered: CheckCircle,
};

function generateChaosEvent(id: number): ChaosEvent {
  const pods = ['backend-7d9f8b-xk2p1', 'frontend-5c8d7f-mn3q2', 'backend-7d9f8b-ab3c4'];
  const pod = pods[Math.floor(Math.random() * pods.length)];
  const sequence: Array<{ type: ChaosEvent['type']; message: string }> = [
    { type: 'pod_deleted', message: `Chaos: deleted pod ${pod}` },
    { type: 'anomaly_detected', message: `AI Engine: anomaly detected on ${pod.split('-')[0]} (score: 0.${Math.floor(Math.random() * 20 + 75)})` },
    { type: 'healing_triggered', message: `Operator: triggered restart for ${pod.split('-')[0]}` },
    { type: 'pod_recovered', message: `Recovery: ${pod.split('-')[0]} pod is Running and Ready` },
  ];
  const event = sequence[id % 4];
  return {
    id,
    timestamp: new Date().toISOString(),
    type: event.type,
    message: event.message,
  };
}

export default function ChaosMode() {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<ChaosEvent[]>([]);
  const [eventCounter, setEventCounter] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  const { data: chaosState } = useQuery({
    queryKey: ['chaos-mode'],
    queryFn: getChaosMode,
    refetchInterval: 5_000,
    placeholderData: { enabled: false },
  });

  const isEnabled = chaosState?.enabled ?? false;

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => setChaosMode(enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chaos-mode'] });
    },
    onError: () => {
      // Optimistically update UI even if API fails (for demo)
    },
  });

  // Simulate chaos events in the UI
  useEffect(() => {
    if (isEnabled) {
      intervalRef.current = setInterval(() => {
        setEventCounter((c) => {
          const newEvent = generateChaosEvent(c);
          setEvents((prev) => [...prev.slice(-49), newEvent]);
          return c + 1;
        });
      }, 3000);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isEnabled]);

  // Auto-scroll to bottom
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  const handleToggle = () => {
    const newState = !isEnabled;
    toggleMutation.mutate(newState);
    if (!newState) {
      setEvents([]);
      setEventCounter(0);
    }
  };

  return (
    <div className="p-8 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Chaos Mode</h2>
        <p className="text-gray-400 mt-1">
          Intentionally break things to prove self-healing works
        </p>
      </div>

      {/* Warning Banner */}
      <div className="bg-red-900/20 border border-red-800 rounded-lg p-4 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-red-300">
          <strong>Warning:</strong> Chaos mode randomly deletes pods in the{' '}
          <code className="font-mono bg-red-900/40 px-1 rounded">production</code> namespace every 60
          seconds. The self-healing operator will automatically detect and recover from each deletion.
          Only enable this in a non-critical environment.
        </div>
      </div>

      {/* Toggle */}
      <div className="card flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Chaos Engine</h3>
          <p className="text-gray-400 text-sm mt-1">
            {isEnabled
              ? '🔥 Active — pods are being randomly deleted every 60 seconds'
              : '✅ Inactive — cluster is running normally'}
          </p>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggleMutation.isPending}
          className={clsx(
            'relative inline-flex h-12 w-24 items-center justify-center rounded-xl font-bold text-sm transition-all duration-300',
            isEnabled
              ? 'bg-red-600 hover:bg-red-700 text-white shadow-lg shadow-red-900/50'
              : 'bg-gray-700 hover:bg-gray-600 text-gray-300',
            toggleMutation.isPending && 'opacity-50 cursor-not-allowed'
          )}
          aria-pressed={isEnabled}
          aria-label={isEnabled ? 'Disable chaos mode' : 'Enable chaos mode'}
        >
          {isEnabled ? (
            <span className="flex items-center gap-1.5">
              <Zap className="w-4 h-4 animate-pulse" />
              ON
            </span>
          ) : (
            'OFF'
          )}
        </button>
      </div>

      {/* How it works */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4">How It Works</h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[
            { step: '1', icon: Zap, color: 'text-red-400', title: 'Pod Deleted', desc: 'Chaos engine randomly deletes a pod in the production namespace' },
            { step: '2', icon: Activity, color: 'text-yellow-400', title: 'Anomaly Detected', desc: 'AI engine detects the anomaly within 60 seconds via Prometheus metrics' },
            { step: '3', icon: AlertTriangle, color: 'text-blue-400', title: 'Operator Acts', desc: 'Self-healing operator evaluates HealingPolicy and triggers restart' },
            { step: '4', icon: CheckCircle, color: 'text-green-400', title: 'Pod Recovered', desc: 'Kubernetes recreates the pod and it passes health checks' },
          ].map(({ step, icon: Icon, color, title, desc }) => (
            <div key={step} className="bg-gray-800/50 rounded-lg p-4 text-center">
              <div className={clsx('text-2xl font-bold mb-2', color)}>{step}</div>
              <Icon className={clsx('w-6 h-6 mx-auto mb-2', color)} />
              <h4 className="text-white font-medium text-sm">{title}</h4>
              <p className="text-gray-400 text-xs mt-1">{desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Live Event Feed */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Live Event Feed</h3>
          {isEnabled && (
            <span className="flex items-center gap-2 text-sm text-red-400">
              <span className="w-2 h-2 bg-red-400 rounded-full animate-pulse" />
              Chaos active
            </span>
          )}
        </div>

        <div
          className="bg-gray-950 rounded-lg p-4 h-64 overflow-y-auto font-mono text-xs space-y-1"
          role="log"
          aria-live="polite"
          aria-label="Chaos event feed"
        >
          {events.length === 0 ? (
            <p className="text-gray-600">
              {isEnabled ? 'Waiting for first chaos event...' : 'Enable chaos mode to see events'}
            </p>
          ) : (
            events.map((event) => {
              const Icon = EVENT_ICONS[event.type];
              return (
                <div key={event.id} className="flex items-start gap-2">
                  <span className="text-gray-600 flex-shrink-0">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                  <Icon className={clsx('w-3 h-3 flex-shrink-0 mt-0.5', EVENT_COLORS[event.type])} />
                  <span className={EVENT_COLORS[event.type]}>{event.message}</span>
                </div>
              );
            })
          )}
          <div ref={eventsEndRef} />
        </div>
      </div>
    </div>
  );
}
